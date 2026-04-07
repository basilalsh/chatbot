"""One-time script to build the semantic embedding cache.

Run this once (or whenever PDFs change):
    python build_embeddings.py

It reads the indexed chunks, calls Gemini's embedding API with rate-limiting,
and saves the cache to data/embeddings_cache.json.
Subsequent server starts will load from cache instantly.

The script saves progress incrementally — if it gets rate-limited and stops,
just run it again and it will resume from where it left off.
"""

import json
import os
import sys
import time

from dotenv import load_dotenv
import google.generativeai as genai

from utils.embedder import (
    EMBED_CACHE_PATH,
    EMBEDDING_MODEL,
    _chunks_fingerprint,
    load_cached_embeddings,
    save_embeddings_cache,
)

STORE_PATH = os.path.join(os.path.dirname(__file__), "data", "chunks.json")
PARTIAL_CACHE_PATH = EMBED_CACHE_PATH.with_suffix(".partial.json")
BATCH_SIZE = 100
# Paid tier: higher limits.  Keep some headroom.
REQUESTS_PER_MINUTE = 200
DELAY_BETWEEN_BATCHES = 60.0 / REQUESTS_PER_MINUTE  # 0.3s


def _load_partial_progress(fingerprint: str) -> list[list[float]]:
    """Load partially completed embeddings if the fingerprint matches."""
    if not PARTIAL_CACHE_PATH.exists():
        return []
    try:
        with PARTIAL_CACHE_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("fingerprint") == fingerprint:
            return data.get("embeddings", [])
    except (json.JSONDecodeError, OSError):
        pass
    return []


def _save_partial_progress(fingerprint: str, embeddings: list[list[float]]) -> None:
    """Save partial progress so the script can resume.
    Never overwrites a larger cache with a smaller one.
    """
    if not embeddings:
        return  # nothing to save — don't clobber an existing partial cache
    # Don't replace an existing partial that has more embeddings
    existing = _load_partial_progress(fingerprint)
    if len(existing) >= len(embeddings):
        return
    with PARTIAL_CACHE_PATH.open("w", encoding="utf-8") as f:
        json.dump({"fingerprint": fingerprint, "embeddings": embeddings}, f)


def main():
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        print("ERROR: GEMINI_API_KEY not set in .env")
        sys.exit(1)

    genai.configure(api_key=api_key)

    # Load chunks
    with open(STORE_PATH, "r", encoding="utf-8") as f:
        store = json.load(f)
    chunks = store.get("chunks", [])
    if not chunks:
        print("No chunks found in store. Run the server once first to index PDFs.")
        sys.exit(1)

    print(f"Found {len(chunks)} chunks.")

    # Check if cache is already up-to-date
    cached = load_cached_embeddings(chunks)
    if cached is not None:
        print(f"Cache already exists and is up-to-date ({len(cached)} embeddings). Nothing to do.")
        return

    fingerprint = _chunks_fingerprint(chunks)
    texts = [chunk.get("text", "") for chunk in chunks]
    total_batches = (len(texts) + BATCH_SIZE - 1) // BATCH_SIZE

    # Resume from partial progress if available
    all_embeddings = _load_partial_progress(fingerprint)
    already_done = len(all_embeddings)
    start_batch = already_done // BATCH_SIZE
    if already_done > 0:
        # Trim to exact batch boundary to avoid partial batch data
        aligned = start_batch * BATCH_SIZE
        all_embeddings = all_embeddings[:aligned]
        already_done = len(all_embeddings)
        start_batch = already_done // BATCH_SIZE
        print(f"Resuming from batch {start_batch + 1}/{total_batches} ({already_done} embeddings cached).\n")
    else:
        print(f"Starting fresh — {total_batches} batches of up to {BATCH_SIZE} texts.")

    remaining_batches = total_batches - start_batch
    est_minutes = (remaining_batches * DELAY_BETWEEN_BATCHES) / 60
    print(f"Rate: ~{REQUESTS_PER_MINUTE} requests/min. Estimated remaining: ~{est_minutes:.1f} min.\n")

    start_time = time.time()

    for batch_num_offset, start_idx in enumerate(
        range(already_done, len(texts), BATCH_SIZE)
    ):
        batch_num = start_batch + batch_num_offset + 1
        batch = texts[start_idx : start_idx + BATCH_SIZE]

        # Retry with back-off on rate-limit errors
        success = False
        for attempt in range(6):
            try:
                result = genai.embed_content(
                    model=EMBEDDING_MODEL,
                    content=batch,
                )
                all_embeddings.extend(result["embedding"])
                success = True
                break
            except Exception as exc:
                exc_str = str(exc)
                is_rate_limit = "429" in exc_str
                is_daily_quota = "PerDay" in exc_str or "free_tier" in exc_str.lower() or "daily" in exc_str.lower()
                if is_rate_limit and not is_daily_quota and attempt < 5:
                    # Per-minute throttle — back off and retry
                    wait = max(DELAY_BETWEEN_BATCHES, 2 ** attempt * 5)
                    print(f"  Rate limited on batch {batch_num}/{total_batches}, waiting {wait:.0f}s...")
                    time.sleep(wait)
                else:
                    # Daily quota exceeded or non-retriable error — save and exit
                    if is_daily_quota:
                        print(f"\nDaily quota exhausted on batch {batch_num}. Quota resets at midnight Pacific Time (~11 AM Gulf time).")
                    else:
                        print(f"\nERROR on batch {batch_num}: {exc}")
                    _save_partial_progress(fingerprint, all_embeddings)
                    if all_embeddings:
                        print(f"Saved partial progress ({len(all_embeddings)} embeddings). Run this script again tomorrow to resume.")
                    else:
                        print("No new embeddings to save. Run this script again tomorrow.")
                    sys.exit(1)

        if not success:
            _save_partial_progress(fingerprint, all_embeddings)
            print(f"Saved partial progress ({len(all_embeddings)} embeddings). Run again to resume.")
            sys.exit(1)

        # Save partial progress every 5 batches
        if batch_num % 5 == 0:
            _save_partial_progress(fingerprint, all_embeddings)

        if batch_num % 5 == 0 or batch_num == total_batches:
            elapsed = time.time() - start_time
            pct = batch_num / total_batches * 100
            print(f"  [{pct:5.1f}%] Batch {batch_num}/{total_batches} done ({elapsed:.0f}s elapsed)")

        # Respect rate limits
        if batch_num < total_batches:
            time.sleep(DELAY_BETWEEN_BATCHES)

    # All done — save final cache and clean up partial file
    save_embeddings_cache(chunks, all_embeddings)
    if PARTIAL_CACHE_PATH.exists():
        PARTIAL_CACHE_PATH.unlink()

    total_time = time.time() - start_time
    print(f"\nDone! {len(all_embeddings)} embeddings saved to {EMBED_CACHE_PATH}")
    print(f"Total time: {total_time:.0f}s ({total_time/60:.1f} min)")
    cache_mb = EMBED_CACHE_PATH.stat().st_size / (1024 * 1024)
    print(f"Cache size: {cache_mb:.1f} MB")


if __name__ == "__main__":
    main()
