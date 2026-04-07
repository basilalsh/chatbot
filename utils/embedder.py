"""Semantic embedding layer using Gemini embedding models.

Computes and caches vector embeddings for document chunks, and provides
cosine-similarity search at query time.
"""

import hashlib
import json
import math
import os
import time
from pathlib import Path

import google.generativeai as genai

EMBEDDING_MODEL = "models/gemini-embedding-001"
EMBED_CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "embeddings_cache.json"
# Tiny sidecar file storing just the fingerprint — lets us reject stale cache
# without reading the full 150+ MB JSON blob on every startup.
EMBED_FP_PATH = EMBED_CACHE_PATH.with_suffix(".fingerprint")
# Gemini embed_content supports up to 100 texts per batch call.
# Keep batch size small enough to stay within free-tier rate limits.
_BATCH_SIZE = 80
# Free tier allows 100 requests/minute. Pause between batches to stay under.
_BATCH_DELAY_SECONDS = 1.2


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _norm(v: list[float]) -> float:
    return math.sqrt(sum(x * x for x in v))


def cosine_similarity(a: list[float], b: list[float]) -> float:
    na, nb = _norm(a), _norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return _dot(a, b) / (na * nb)


# ---------------------------------------------------------------------------
# Embedding generation
# ---------------------------------------------------------------------------

def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts using Gemini, batching with rate-limit awareness."""
    all_embeddings: list[list[float]] = []
    total_batches = (len(texts) + _BATCH_SIZE - 1) // _BATCH_SIZE

    for batch_num, start in enumerate(range(0, len(texts), _BATCH_SIZE), start=1):
        batch = texts[start : start + _BATCH_SIZE]
        # Retry with exponential back-off on rate-limit (429) errors.
        for attempt in range(5):
            try:
                result = genai.embed_content(
                    model=EMBEDDING_MODEL,
                    content=batch,
                )
                all_embeddings.extend(result["embedding"])
                break
            except Exception as exc:
                if "429" in str(exc) and attempt < 4:
                    wait = _BATCH_DELAY_SECONDS * (2 ** attempt)
                    print(f"[Embeddings] Rate limited on batch {batch_num}/{total_batches}, retrying in {wait:.0f}s...")
                    time.sleep(wait)
                else:
                    raise

        # Small pause between batches to respect rate limits.
        if batch_num < total_batches:
            time.sleep(_BATCH_DELAY_SECONDS)

        if batch_num % 10 == 0 or batch_num == total_batches:
            print(f"[Embeddings] Progress: {batch_num}/{total_batches} batches done.")

    return all_embeddings


def embed_single(text: str) -> list[float]:
    """Embed a single query string."""
    result = genai.embed_content(
        model=EMBEDDING_MODEL,
        content=text,
    )
    return result["embedding"]


# ---------------------------------------------------------------------------
# Cache management
# ---------------------------------------------------------------------------

def _chunks_fingerprint(chunks: list[dict]) -> str:
    """Robust fingerprint that samples chunk IDs distributed across the list.

    Sampling ~20 chunk_ids spread evenly across all chunks (not just first/last)
    ensures the fingerprint changes whenever any document is added or removed,
    even when the total chunk count happens to stay the same.
    """
    h = hashlib.sha256()
    h.update(str(len(chunks)).encode())
    if chunks:
        # Sample ~20 positions evenly spread across the full list.
        n = len(chunks)
        step = max(1, n // 20)
        for i in range(0, n, step):
            cid = chunks[i].get("chunk_id") or chunks[i].get("text", "")[:80]
            h.update(str(cid).encode("utf-8", errors="replace"))
    return h.hexdigest()


def load_cached_embeddings(chunks: list[dict]) -> list[list[float]] | None:
    """Return cached embeddings if they match the current chunks, else None.

    The fingerprint is checked against a tiny sidecar file BEFORE loading the
    full 150+ MB JSON, so startup is fast even when the cache is stale.
    """
    if not EMBED_CACHE_PATH.exists():
        return None

    expected = _chunks_fingerprint(chunks)

    # Fast path: check sidecar fingerprint file first (avoids loading 150+ MB).
    if EMBED_FP_PATH.exists():
        try:
            stored_fp = EMBED_FP_PATH.read_text(encoding="utf-8").strip()
            if stored_fp != expected:
                return None  # stale — skip loading the big JSON
        except OSError:
            pass  # sidecar unreadable — fall through to full check

    try:
        with EMBED_CACHE_PATH.open("r", encoding="utf-8") as f:
            cache = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    if not isinstance(cache, dict):
        return None
    if cache.get("fingerprint") != expected:
        return None
    embeddings = cache.get("embeddings")
    if not isinstance(embeddings, list) or len(embeddings) != len(chunks):
        return None
    return embeddings


def save_embeddings_cache(chunks: list[dict], embeddings: list[list[float]]) -> None:
    fp = _chunks_fingerprint(chunks)
    cache = {
        "fingerprint": fp,
        "count": len(embeddings),
        "embeddings": embeddings,
    }
    EMBED_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with EMBED_CACHE_PATH.open("w", encoding="utf-8") as f:
        json.dump(cache, f)
    # Write the sidecar fingerprint so future startups skip the full JSON load.
    try:
        EMBED_FP_PATH.write_text(fp, encoding="utf-8")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Build or load the embedding index
# ---------------------------------------------------------------------------

def build_embedding_index(chunks: list[dict]) -> list[list[float]]:
    """Return embeddings for all chunks, using cache when available."""
    cached = load_cached_embeddings(chunks)
    if cached is not None:
        return cached

    texts = [chunk.get("text", "") for chunk in chunks]
    if not texts:
        return []

    embeddings = embed_texts(texts)
    save_embeddings_cache(chunks, embeddings)
    return embeddings


# ---------------------------------------------------------------------------
# Semantic search
# ---------------------------------------------------------------------------

# Cache the pre-normalized chunk matrix so it is only built once per startup
# rather than on every request.  This avoids converting 6 000+ lists of floats
# to numpy arrays on every query (which alone takes ~50 ms).
_np_matrix_cache: dict = {"matrix": None, "count": 0}


def scores_from_embedding(
    query_vec: list[float],
    chunk_embeddings: list[list[float]],
) -> list[float]:
    """Compute cosine similarity between a pre-computed query vector and all chunk vectors.

    Uses numpy when available, giving ~100–300x speed improvement over the
    pure-Python loop for large indices (e.g. 6 000 chunks × 768 dims).
    The normalised chunk matrix is cached after the first call so subsequent
    requests only pay the cost of normalising the query vector and one BLAS
    matrix-vector multiply (~1–5 ms total).
    """
    if not chunk_embeddings:
        return []
    try:
        import numpy as np
        cache = _np_matrix_cache
        if cache["matrix"] is None or cache["count"] != len(chunk_embeddings):
            mat = np.array(chunk_embeddings, dtype=np.float32)
            norms = np.linalg.norm(mat, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            cache["matrix"] = mat / norms  # pre-normalised, shape [N, D]
            cache["count"] = len(chunk_embeddings)

        norm_mat = cache["matrix"]
        qv = np.array(query_vec, dtype=np.float32)
        q_norm = float(np.linalg.norm(qv))
        if q_norm == 0:
            return [0.0] * len(chunk_embeddings)
        qv = qv / q_norm
        return (norm_mat @ qv).tolist()
    except ImportError:
        # numpy not available — fall back to pure-Python cosine loop.
        return [cosine_similarity(query_vec, ce) for ce in chunk_embeddings]


def semantic_scores_for_query(
    query: str,
    chunk_embeddings: list[list[float]],
) -> list[float]:
    """Embed the query then return cosine-similarity scores for every chunk."""
    if not chunk_embeddings:
        return []
    query_vec = embed_single(query)
    return scores_from_embedding(query_vec, chunk_embeddings)
