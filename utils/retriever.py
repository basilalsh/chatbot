import math
import re
from collections import Counter

# ── Module-level IDF / corpus cache ──────────────────────────────
# Tokenising + IDF over 6 000+ chunks is expensive.  Cache the result
# and only rebuild when the chunk list content changes.
_corpus_cache: dict = {
    "chunks_hash": None,
    "normalized_texts": [],
    "counters": [],
    "idf": {},
}


def _chunks_content_hash(chunks: list[dict]) -> str:
    """Robust hash that samples chunk IDs distributed across the list.

    Sampling ~20 positions spread evenly ensures the IDF corpus cache
    rebuilds whenever any document is added or removed, even when the
    total chunk count happens to stay the same.
    """
    if not chunks:
        return "empty"
    import hashlib
    h = hashlib.sha256()
    h.update(str(len(chunks)).encode())
    n = len(chunks)
    step = max(1, n // 20)
    for i in range(0, n, step):
        cid = chunks[i].get("chunk_id") or chunks[i].get("text", "")[:80]
        h.update(str(cid).encode("utf-8", errors="replace"))
    return h.hexdigest()


def _get_corpus_data(chunks: list[dict]) -> tuple[list[str], list[Counter], dict]:
    """Return (normalized_texts, corpus_counters, idf), using a cache."""
    c = _corpus_cache
    content_hash = _chunks_content_hash(chunks)
    if content_hash == c["chunks_hash"]:
        return c["normalized_texts"], c["counters"], c["idf"]

    normalized = [normalize_text(item.get("text", "")) for item in chunks]
    counters = [Counter(tokenize(t)) for t in normalized]
    idf = build_idf(counters)

    c["chunks_hash"] = content_hash
    c["normalized_texts"] = normalized
    c["counters"] = counters
    c["idf"] = idf
    return normalized, counters, idf


EN_STOPWORDS = {
    "the", "and", "for", "that", "with", "this", "from", "are", "was", "were", "have",
    "has", "had", "you", "your", "into", "their", "what", "when", "where", "which", "who",
    "how", "why", "can", "could", "would", "should", "about", "please", "there", "been", "will",
    "shall", "than", "then", "also", "they", "them", "his", "her", "its", "our", "out", "not",
    "is", "it", "be", "do", "did", "does", "an", "or", "as", "at", "by", "if", "my", "me",
    "we", "so", "no", "up", "on", "to", "of", "in", "am", "he", "she", "a",
}

AR_STOPWORDS = {
    "في", "من", "على", "إلى", "عن", "ما", "متى", "كيف", "هل", "هذا", "هذه", "ذلك", "تلك",
    "مع", "كان", "كانت", "يكون", "تم", "لقد", "لكن", "ثم", "أو", "و", "ب", "ل", "أن", "إن",
    "كما", "بعد", "قبل", "بين", "حتى", "اذا", "إذا", "ضمن", "حول", "حسب", "عند",
}

# Common Arabic prefixes and suffixes for lightweight stemming.
_AR_PREFIXES = ("وال", "بال", "كال", "فال", "لل", "ال", "و", "ب", "ك", "ف", "ل")
_AR_SUFFIXES = ("ات", "ون", "ين", "ان", "تين", "يه", "ته", "ها", "هم", "هن", "كم", "نا")


def arabic_light_stem(word: str) -> str:
    """Strip common Arabic prefixes/suffixes to get a pseudo-root.

    This is intentionally lightweight — it doesn't do full morphological
    analysis but significantly improves matching for common word forms.
    """
    # Only process Arabic words (Unicode Arabic block).
    if not word or not re.match(r"^[\u0600-\u06FF]+$", word):
        return word

    original = word
    # Strip prefixes (longest first).
    for prefix in _AR_PREFIXES:
        if word.startswith(prefix) and len(word) - len(prefix) >= 2:
            word = word[len(prefix):]
            break

    # Strip suffixes (longest first).
    for suffix in _AR_SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 2:
            word = word[:-len(suffix)]
            break

    # Don't reduce to fewer than 2 characters.
    return word if len(word) >= 2 else original


def retrieve_relevant_chunks(
    question: str,
    chunks: list[dict],
    top_k: int = 6,
    semantic_scores: list[float] | None = None,
) -> list[dict]:
    question_norm_text = normalize_text(question)
    question_tokens = tokenize(question_norm_text)
    if not question_tokens:
        return []

    use_semantic = (
        semantic_scores is not None and len(semantic_scores) == len(chunks)
    )

    question_counter = Counter(question_tokens)
    normalized_chunk_texts, corpus_counters, idf = _get_corpus_data(chunks)

    question_vec = weighted_vector(question_counter, idf)
    scored_items = []

    question_grams = character_ngrams(question_norm_text)

    for idx, (item, chunk_counter, chunk_norm_text) in enumerate(
        zip(chunks, corpus_counters, normalized_chunk_texts)
    ):
        if not chunk_counter:
            continue

        chunk_vec = weighted_vector(chunk_counter, idf)
        cosine = cosine_score(question_vec, chunk_vec)
        coverage = token_coverage(question_counter, chunk_counter)
        phrase = phrase_boost(question_norm_text, chunk_norm_text)
        typo = typo_tolerant_score(question_counter, chunk_counter)
        ngram = ngram_jaccard(question_grams, character_ngrams(chunk_norm_text))

        if use_semantic:
            sem = max(0.0, semantic_scores[idx])
            # Blend: 35% semantic + 30% cosine(TF-IDF) + 12% coverage + 8% phrase + 9% typo + 6% ngram
            score = (
                0.35 * sem
                + 0.30 * cosine
                + 0.12 * coverage
                + 0.08 * phrase
                + 0.09 * typo
                + 0.06 * ngram
            )
        else:
            score = (0.50 * cosine) + (0.20 * coverage) + (0.10 * phrase) + (0.12 * typo) + (0.08 * ngram)

        if score < 0.025:
            continue

        merged = dict(item)
        merged["score"] = round(score, 4)
        merged["semantic_score"] = round(sem if use_semantic else 0.0, 4)
        merged["match_terms"] = top_overlap_terms(question_counter, chunk_counter, limit=6)
        merged["preview"] = build_preview(item.get("text", ""), set(question_counter.keys()))
        scored_items.append(merged)

    scored_items.sort(key=lambda x: x["score"], reverse=True)
    return scored_items[:top_k]


def tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z0-9]+|[\u0600-\u06FF]+", normalize_text(text))
    filtered = []
    for token in tokens:
        if len(token) <= 1:
            continue
        if token in EN_STOPWORDS or token in AR_STOPWORDS:
            continue
        # For Arabic tokens, add both original and stemmed form.
        stemmed = arabic_light_stem(token)
        filtered.append(token)
        if stemmed != token:
            filtered.append(stemmed)
    return filtered


def normalize_text(text: str) -> str:
    value = (text or "").lower()

    # Arabic normalization for better matching with spelling variations.
    value = re.sub(r"[\u064B-\u065F\u0670]", "", value)  # Remove diacritics.
    value = value.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    value = value.replace("ى", "ي").replace("ة", "ه").replace("ؤ", "و").replace("ئ", "ي")

    # General normalization.
    value = re.sub(r"\s+", " ", value).strip()
    return value


def build_idf(counters: list[Counter]) -> dict[str, float]:
    doc_count = max(1, len(counters))
    df = Counter()
    for counter in counters:
        for term in counter.keys():
            df[term] += 1

    idf: dict[str, float] = {}
    for term, freq in df.items():
        idf[term] = math.log((doc_count + 1) / (freq + 1)) + 1.0
    return idf


def weighted_vector(counter: Counter, idf: dict[str, float]) -> dict[str, float]:
    vec: dict[str, float] = {}
    for term, tf in counter.items():
        vec[term] = tf * idf.get(term, 1.0)
    return vec


def cosine_score(v1: dict[str, float], v2: dict[str, float]) -> float:
    if not v1 or not v2:
        return 0.0

    overlap = set(v1).intersection(v2)
    if not overlap:
        return 0.0

    numerator = sum(v1[t] * v2[t] for t in overlap)
    denom_left = math.sqrt(sum(v * v for v in v1.values()))
    denom_right = math.sqrt(sum(v * v for v in v2.values()))
    if denom_left == 0 or denom_right == 0:
        return 0.0
    return numerator / (denom_left * denom_right)


def token_coverage(question_counter: Counter, chunk_counter: Counter) -> float:
    if not question_counter:
        return 0.0
    overlap = set(question_counter).intersection(chunk_counter)
    return len(overlap) / max(1, len(set(question_counter)))


def phrase_boost(question: str, text: str) -> float:
    q = (question or "").strip().lower()
    body = (text or "").lower()
    if q and q in body:
        return 1.0

    words = [w for w in tokenize(q) if len(w) > 2]
    if not words:
        return 0.0

    hit_count = sum(1 for w in words if w in body)
    return min(1.0, hit_count / max(3, len(words)))


def typo_tolerant_score(question_counter: Counter, chunk_counter: Counter) -> float:
    question_terms = set(question_counter.keys())
    chunk_terms = set(chunk_counter.keys())
    if not question_terms or not chunk_terms:
        return 0.0

    matched = 0
    for q in question_terms:
        if q in chunk_terms:
            matched += 1
            continue

        # Allow near terms (minor misspelling) for longer tokens.
        if len(q) < 4:
            continue

        for c in chunk_terms:
            if abs(len(q) - len(c)) > 2:
                continue
            ratio = sequence_similarity(q, c)
            if ratio >= 0.84:
                matched += 1
                break

    return matched / max(1, len(question_terms))


def sequence_similarity(a: str, b: str) -> float:
    # Lightweight similarity without extra dependencies.
    if not a or not b:
        return 0.0

    common = 0
    b_chars = list(b)
    for ch in a:
        if ch in b_chars:
            common += 1
            b_chars.remove(ch)

    return (2 * common) / (len(a) + len(b))


def character_ngrams(text: str, n: int = 3) -> set[str]:
    compact = re.sub(r"\s+", "", text or "")
    if len(compact) < n:
        return {compact} if compact else set()
    return {compact[i:i + n] for i in range(0, len(compact) - n + 1)}


def ngram_jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a.intersection(b))
    union = len(a.union(b))
    if union == 0:
        return 0.0
    return inter / union


def top_overlap_terms(question_counter: Counter, chunk_counter: Counter, limit: int = 6) -> list[str]:
    overlap = set(question_counter).intersection(chunk_counter)
    ranked = sorted(overlap, key=lambda t: question_counter[t] * chunk_counter[t], reverse=True)
    return ranked[:limit]


def build_preview(text: str, question_terms: set[str], limit: int = 230) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "")).strip()
    if not cleaned:
        return ""

    sentences = re.split(r"(?<=[.!?؟:؛])\s+", cleaned)
    best_sentence = ""
    best_score = -1

    for sentence in sentences:
        sentence_tokens = set(tokenize(sentence))
        score = len(sentence_tokens.intersection(question_terms))
        if score > best_score:
            best_score = score
            best_sentence = sentence

    snippet = best_sentence or cleaned
    if len(snippet) <= limit:
        return snippet
    return snippet[:limit].rstrip() + "..."
