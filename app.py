import concurrent.futures
import hashlib
import json
import logging
import os
import re
import shutil
import threading
import time
from pathlib import Path

from dotenv import load_dotenv

# ── Structured logging ────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.INFO,
)
log = logging.getLogger("charbot")
from flask import Flask, Response, jsonify, request, send_from_directory
from google.api_core.exceptions import GoogleAPIError
import google.generativeai as genai
from utils.pdf_loader import process_pdf_file
from utils.retriever import retrieve_relevant_chunks
from utils.embedder import semantic_scores_for_query, embed_single, scores_from_embedding


BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
DATA_DIR = BASE_DIR / "data"
STORE_PATH = DATA_DIR / "chunks.json"

# ── Dynamic index state (updated by background reindex thread) ────
_live_lock = threading.Lock()
_live_state: dict = {
    "embedding_index": [],   # list[list[float]]
    "status": "ready",       # ready | processing | embedding | error
    "message": "",
    "progress": 0,           # 0-100 during embedding build
}
_reindex_thread: threading.Thread | None = None
PREFERRED_MODELS = [
    "models/gemini-2.5-flash",
    "models/gemini-2.5-pro",
    "models/gemini-2.0-flash",
    "models/gemini-1.5-flash",
    "models/gemini-1.5-pro",
]

# Faster models used for lightweight utility tasks (translation, reranking).
# Ordered fastest-first — no need for premium quality on these calls.
_UTILITY_MODELS = [
    "models/gemini-2.0-flash",
    "models/gemini-1.5-flash",
    "models/gemini-2.5-flash",
]

# Simple translation cache — avoids a full LLM round-trip for repeated/similar Arabic queries.
_translate_cache: dict[str, str] = {}
_TRANSLATE_CACHE_MAX = 200

# Response cache — returns the full answer instantly for repeated identical questions
# that arrive without conversation history (the most common case across separate sessions).
_response_cache: dict[str, dict] = {}
_RESPONSE_CACHE_MAX = 500

FALLBACK_MESSAGES = {
    "en": "I could not find a clear answer in the uploaded documents.",
    "ar": "لم أتمكن من العثور على إجابة واضحة في المستندات المرفوعة.",
}

MODE_PROFILES = {
    "accurate": {
        "retrieval_top_k": 7,          # 10→7: fewer chunks = smaller prompt, same coverage
        "gemini_temperature": 0.1,
        "enable_rerank": True,
        "enable_retry": True,
        "retrieval_overfetch_multiplier": 2,  # 3→2: 14 chunks fetched instead of 30
        "context_snippet_limit": 1000,  # 1500→1000: still comprehensive, ~30% less tokens
    },
    "balanced": {
        "retrieval_top_k": 6,
        "gemini_temperature": 0.2,
        "enable_rerank": True,
        "enable_retry": True,
        "retrieval_overfetch_multiplier": 2,
        "context_snippet_limit": 900,
    },
    "fast": {
        "retrieval_top_k": 4,
        "gemini_temperature": 0.1,
        "enable_rerank": False,
        "enable_retry": False,
        "retrieval_overfetch_multiplier": 1,
        "context_snippet_limit": 450,
    },
}


def create_app() -> Flask:
    load_dotenv()
    runtime_config = resolve_runtime_config()
    log.info(
        "Runtime mode=%s top_k=%d rerank=%s retry=%s context_limit=%d",
        runtime_config["assistant_mode"],
        runtime_config["retrieval_top_k"],
        runtime_config["enable_rerank"],
        runtime_config["enable_retry"],
        runtime_config["context_snippet_limit"],
    )

    # Serve the React production build from static/dist/
    dist_dir = BASE_DIR / "static" / "dist"
    app = Flask(
        __name__,
        static_folder=str(dist_dir),
        static_url_path="",
    )
    app.config["MAX_CONTENT_LENGTH"] = 150 * 1024 * 1024  # 150 MB — allow large PDFs

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if gemini_api_key:
        genai.configure(api_key=gemini_api_key)

    # One-time migration: move any root-level PDF into uploads/ so users
    # don't have to manage files in the source tree.
    _migrate_root_pdfs_to_uploads()

    # Build/load the chunk store and embeddings on startup.
    rebuild_documents_store_if_needed()

    store = load_store()
    _needs_reindex = False
    with _live_lock:
        if store["chunks"]:
            from utils.embedder import load_cached_embeddings
            cached = load_cached_embeddings(store["chunks"])
            if cached is not None:
                _live_state["embedding_index"] = cached
                log.info("Embeddings loaded: %d chunks", len(cached))
            else:
                log.info(
                    "Embedding cache invalid or missing — starting background rebuild..."
                )
                _needs_reindex = True
    # trigger_reindex() acquires _live_lock internally, so it must be called
    # OUTSIDE the lock block above to avoid a deadlock.
    if _needs_reindex:
        trigger_reindex()

    # Watch uploads/ for changes made outside the API (manual delete/add).
    _start_upload_watcher(interval=30)

    @app.route("/")
    def index():
        return send_from_directory(str(dist_dir), "index.html")

    @app.errorhandler(404)
    def fallback(e):
        """SPA catch-all: serve index.html for any unknown route."""
        return send_from_directory(str(dist_dir), "index.html")

    # ── Document management endpoints ────────────────────────────

    @app.route("/documents", methods=["GET"])
    def list_documents():
        """Return the list of managed PDF documents and current index status."""
        pdfs = sorted(UPLOAD_DIR.glob("*.pdf"))
        docs = []
        for p in pdfs:
            stat = p.stat()
            docs.append({
                "name": p.name,
                "size_bytes": stat.st_size,
                "modified": stat.st_mtime,
            })
        with _live_lock:
            status_snapshot = {
                "status": _live_state["status"],
                "message": _live_state["message"],
                "progress": _live_state["progress"],
            }
        return jsonify({"documents": docs, "index": status_snapshot})

    @app.route("/documents/upload", methods=["POST"])
    def upload_document():
        """Upload a PDF file and trigger a background reindex."""
        if "file" not in request.files:
            return jsonify({"error": "No file provided."}), 400

        f = request.files["file"]
        filename = (f.filename or "").strip()
        if not filename:
            return jsonify({"error": "Empty filename."}), 400

        # Security: sanitise the filename — only allow PDF, strip path separators.
        safe_name = re.sub(r"[^\w\s\-_.]", "", filename.replace("/", "_").replace("\\", "_"))
        if not safe_name.lower().endswith(".pdf"):
            return jsonify({"error": "Only PDF files are accepted."}), 400

        dest = UPLOAD_DIR / safe_name
        f.save(str(dest))
        log.info("Document uploaded: %s (%.1f MB)", safe_name, dest.stat().st_size / 1_048_576)

        trigger_reindex()
        return jsonify({"message": f"'{safe_name}' uploaded successfully. Reindexing in background.", "name": safe_name}), 202

    @app.route("/documents/<path:doc_name>", methods=["DELETE"])
    def delete_document(doc_name: str):
        """Remove a managed PDF and trigger a background reindex."""
        # Prevent path traversal: strip any directory components.
        safe_name = Path(doc_name).name
        target = UPLOAD_DIR / safe_name
        if not target.exists() or not target.is_file():
            return jsonify({"error": "Document not found."}), 404
        target.unlink()
        log.info("Document deleted: %s", safe_name)

        # Immediately strip the deleted document from chunks.json and the
        # in-memory embedding index so that queries between now and the
        # background reindex completing cannot cite the deleted document.
        old_store = load_store()
        keep_mask = [
            i for i, ch in enumerate(old_store["chunks"])
            if ch.get("document_name") != safe_name
        ]
        filtered_chunks = [old_store["chunks"][i] for i in keep_mask]
        filtered_docs = [d for d in old_store["documents"] if d != safe_name]
        save_store({"documents": filtered_docs, "chunks": filtered_chunks})

        with _live_lock:
            old_idx = _live_state["embedding_index"]
            if old_idx and len(old_idx) == len(old_store["chunks"]):
                _live_state["embedding_index"] = [old_idx[i] for i in keep_mask]
            else:
                _live_state["embedding_index"] = []

        _response_cache.clear()
        trigger_reindex()
        return jsonify({"message": f"'{safe_name}' deleted. Reindexing in background."})

    @app.route("/documents/view/<path:doc_name>", methods=["GET"])
    def view_document(doc_name: str):
        """Serve a managed PDF file so the browser can open it with page anchors."""
        safe_name = Path(doc_name).name
        target = UPLOAD_DIR / safe_name
        if not target.exists() or not target.is_file():
            return jsonify({"error": "Document not found."}), 404
        return send_from_directory(str(UPLOAD_DIR), safe_name, mimetype="application/pdf")

    @app.route("/documents/status", methods=["GET"])
    def index_status():
        """Polling endpoint for the frontend to check reindex progress."""
        with _live_lock:
            return jsonify({
                "status": _live_state["status"],
                "message": _live_state["message"],
                "progress": _live_state["progress"],
            })

    @app.route("/api/suggestions", methods=["GET"])
    def get_suggestions():
        """Return curated starter questions shown on the empty-state screen.

        Picks a balanced set of EN/AR questions that showcase what the assistant
        can answer.  Falls back gracefully when called from the frontend.
        """
        suggestions = [
            "What are the annual leave entitlements?",
            "ما هي حقوق الإجازة السنوية؟",
            "What is the notice period for termination?",
            "ما هي مدة الإشعار لإنهاء العقد؟",
            "Explain the claims process for motor insurance",
            "What documents are needed for a new policy?",
            "ما هي إجراءات المطالبة بالتأمين الطبي؟",
            "What are the overtime rules?",
        ]
        return jsonify({"suggestions": suggestions})

    @app.route("/ask", methods=["POST"])
    def ask_question():
        req_start = time.perf_counter()
        payload = request.get_json(silent=True) or {}
        question = (payload.get("question") or "").strip()
        language = detect_language(question)
        log.info("ASK  q=%s  lang=%s", question[:80], language)

        if not question:
            return jsonify({"error": localize_text("Please enter a question before sending.", language)}), 400

        if len(question) > 2000:
            return jsonify({"error": "Question too long (max 2 000 characters)."}), 400

        if is_greeting(question):
            return jsonify({"answer": greeting_response(language), "sources": [], "follow_up_questions": [], "language": language, "confidence": "high"})

        faq_answer = find_faq_answer(question, language)
        if faq_answer:
            return jsonify({"answer": faq_answer, "sources": [], "follow_up_questions": [], "language": language, "confidence": "high"})

        # Fast path: identical questions with no conversation history are served
        # from an in-process cache, skipping the entire RAG pipeline.
        _cache_key = normalize_for_compare(question) + "|" + language
        if not payload.get("history") and _cache_key in _response_cache:
            log.info("ASK cache hit: %s", question[:60])
            return jsonify(_response_cache[_cache_key])

        history = sanitize_history(payload.get("history"))
        search_query = expand_query_with_history(question, history)

        store = load_store()
        all_chunks = store["chunks"]
        if not all_chunks:
            return jsonify({"answer": fallback_message(language), "sources": [], "follow_up_questions": [], "language": language})

        # For Arabic: run translation (TF-IDF needs English) and embedding (for semantic
        # scoring) in parallel — Gemini embedding-001 is multilingual so the Arabic
        # query vector still produces meaningful cosine similarities against English docs.
        # For English: single sequential embed call.
        sem_scores = None
        _emb_idx = _live_state["embedding_index"]
        if language == "ar":
            if _emb_idx and len(_emb_idx) == len(all_chunks):
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as _ex:
                    _trans_fut = _ex.submit(translate_query_for_retrieval, search_query)
                    _embed_fut = _ex.submit(embed_single, search_query)
                    search_query = _trans_fut.result()
                    try:
                        sem_scores = scores_from_embedding(_embed_fut.result(), _emb_idx)
                    except Exception:
                        log.exception("Parallel embed failed: %s", search_query[:80])
            else:
                search_query = translate_query_for_retrieval(search_query)
        elif _emb_idx and len(_emb_idx) == len(all_chunks):
            try:
                sem_scores = semantic_scores_for_query(search_query, _emb_idx)
            except Exception:
                log.exception("Semantic scoring failed for query: %s", search_query[:80])

        t0 = time.perf_counter()
        retrieval_k = runtime_config["retrieval_top_k"]
        overfetch = runtime_config["retrieval_overfetch_multiplier"]
        top_chunks = retrieve_relevant_chunks(
            search_query,
            all_chunks,
            top_k=retrieval_k * overfetch,
            semantic_scores=sem_scores,
        )

        # Merge adjacent chunks so answers spanning two chunks aren't cut off.
        top_chunks = merge_adjacent_chunks(top_chunks, all_chunks)
        log.info("Retrieval: %d chunks in %.1fms | query=%s", len(top_chunks), (time.perf_counter() - t0) * 1000, question[:60])

        if not top_chunks:
            return jsonify(
                {
                    "answer": fallback_message(language),
                    "sources": [],
                    "follow_up_questions": [],
                    "language": language,
                }
            )

        gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not gemini_key:
            return jsonify({"error": "Server is missing GEMINI_API_KEY environment variable."}), 500

        # Re-rank: ask LLM to pick the most relevant chunks.
        # Keep the full set for a possible retry with broader context.
        all_retrieved_chunks = list(top_chunks)
        if runtime_config["enable_rerank"] and len(top_chunks) > runtime_config["retrieval_top_k"]:
            top_chunks = rerank_chunks_with_llm(
                question, top_chunks, runtime_config["retrieval_top_k"]
            )

        context_blocks = []
        for idx, item in enumerate(top_chunks, start=1):
            page_info = f", page {item.get('page_start')}" if item.get("page_start") else ""
            chunk_text = summarize_snippet(item.get("text", ""), limit=runtime_config["context_snippet_limit"])
            context_blocks.append(
                f"Source {idx} ({item['document_name']}{page_info}, chunk {item.get('chunk_id', 'n/a')}):\n{chunk_text}"
            )
        context_text = "\n\n".join(context_blocks)

        prompt = build_assistant_prompt(
            question=question,
            language=language,
            context_text=context_text,
            history=history,
        )

        try:
            response = generate_with_model_fallback(prompt, runtime_config["gemini_temperature"])
            llm_text = ((response.text or "") if response else "").strip()
        except Exception as exc:
            log.exception("Generation error")
            return jsonify({"error": f"Generation error: {exc}"}), 502

        answer_payload = parse_answer_payload(llm_text, language)
        answer_text = answer_payload["answer"]
        follow_ups = answer_payload["follow_up_questions"]
        confidence = answer_payload["confidence"]

        # Automatic retry: if the LLM returned the fallback but we DO have
        # retrieved chunks, try once more with lower temperature, a softer
        # prompt, and the FULL set of retrieved chunks (before re-ranking)
        # plus a secondary retrieval with expanded terms to capture
        # definitional chunks that TF-IDF might have missed.
        _retry_triggered = runtime_config["enable_retry"] and is_fallback_answer(answer_text) and bool(all_retrieved_chunks)
        if _retry_triggered:
            # Secondary retrieval with expanded queries to find definitions.
            expanded_chunks = _expanded_retrieval(
                question, all_chunks, runtime_config["retrieval_top_k"],
                semantic_scores=sem_scores,
            )
            # Merge original + expanded, deduplicate by chunk_id.
            seen_ids = {c["chunk_id"] for c in all_retrieved_chunks}
            combined = list(all_retrieved_chunks)
            for c in expanded_chunks:
                if c["chunk_id"] not in seen_ids:
                    combined.append(c)
                    seen_ids.add(c["chunk_id"])

            retry_blocks = []
            for idx, item in enumerate(combined, start=1):
                page_info = f", page {item.get('page_start')}" if item.get("page_start") else ""
                chunk_text = summarize_snippet(item.get("text", ""), limit=runtime_config["context_snippet_limit"])
                retry_blocks.append(
                    f"Source {idx} ({item['document_name']}{page_info}, chunk {item.get('chunk_id', 'n/a')}):\n{chunk_text}"
                )
            retry_context = "\n\n".join(retry_blocks)

            retry_prompt = build_assistant_prompt_retry(
                question=question,
                language=language,
                context_text=retry_context,
                history=history,
            )
            try:
                retry_resp = generate_with_model_fallback(retry_prompt, 0.0)
                retry_text = ((retry_resp.text or "") if retry_resp else "").strip()
                retry_payload = parse_answer_payload(retry_text, language)
                if not is_fallback_answer(retry_payload["answer"]):
                    answer_text = retry_payload["answer"]
                    follow_ups = retry_payload["follow_up_questions"]
                    confidence = retry_payload["confidence"]
                    top_chunks = combined
            except Exception as exc:
                log.warning("Retry failed: %s", exc)

        if is_fallback_answer(answer_text):
            sources = []
            follow_ups = []
        else:
            sources = [
                {
                    "document_name": item["document_name"],
                    "snippet": summarize_snippet(item.get("preview") or item["text"]),
                    "chunk_id": item.get("chunk_id"),
                    "page": item.get("page_start"),
                    "score": item["score"],
                }
                for item in top_chunks
            ]

        log.info("ASK done in %.0fms  confidence=%s  q=%s", (time.perf_counter() - req_start) * 1000, confidence, question[:60])

        result = {
            "answer": answer_text,
            "sources": sources,
            "follow_up_questions": follow_ups,
            "language": language,
            "confidence": confidence,
        }

        # Store successful answers in the response cache for future identical questions.
        if not history and not is_fallback_answer(answer_text):
            if len(_response_cache) >= _RESPONSE_CACHE_MAX:
                _response_cache.pop(next(iter(_response_cache)))
            _response_cache[_cache_key] = result

        return jsonify(result)

    @app.route("/ask-stream", methods=["POST"])
    def ask_question_stream():
        """SSE streaming endpoint — sends answer tokens as they arrive."""
        payload = request.get_json(silent=True) or {}
        question = (payload.get("question") or "").strip()
        language = detect_language(question)
        log.info("STREAM  q=%s  lang=%s", question[:80], language)

        if not question:
            return jsonify({"error": localize_text("Please enter a question before sending.", language)}), 400

        if len(question) > 2000:
            return jsonify({"error": "Question too long (max 2 000 characters)."}), 400

        if is_greeting(question):
            return jsonify(
                {
                    "answer": greeting_response(language),
                    "sources": [],
                    "follow_up_questions": [],
                    "language": language,
                    "confidence": "high",
                }
            )

        faq_answer = find_faq_answer(question, language)
        if faq_answer:
            return jsonify(
                {
                    "answer": faq_answer,
                    "sources": [],
                    "follow_up_questions": [],
                    "language": language,
                    "confidence": "high",
                }
            )

        # Fast path: serve cached answer directly (no SSE overhead for repeated questions).
        _stream_cache_key = normalize_for_compare(question) + "|" + language
        if not payload.get("history") and _stream_cache_key in _response_cache:
            log.info("STREAM cache hit: %s", question[:60])
            return jsonify(_response_cache[_stream_cache_key])

        history = sanitize_history(payload.get("history"))
        search_query = expand_query_with_history(question, history)

        store = load_store()
        all_chunks = store["chunks"]
        if not all_chunks:
            return jsonify(
                {
                    "answer": fallback_message(language),
                    "sources": [],
                    "follow_up_questions": [],
                    "language": language,
                }
            )

        # Parallel Arabic: translate for TF-IDF and embed the original query for
        # semantic scoring simultaneously.  English queries use a single embed call.
        sem_scores = None
        _emb_idx = _live_state["embedding_index"]
        if language == "ar":
            if _emb_idx and len(_emb_idx) == len(all_chunks):
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as _ex:
                    _trans_fut = _ex.submit(translate_query_for_retrieval, search_query)
                    _embed_fut = _ex.submit(embed_single, search_query)
                    search_query = _trans_fut.result()
                    try:
                        sem_scores = scores_from_embedding(_embed_fut.result(), _emb_idx)
                    except Exception:
                        log.exception("Parallel embed failed (stream): %s", search_query[:80])
            else:
                search_query = translate_query_for_retrieval(search_query)
        elif _emb_idx and len(_emb_idx) == len(all_chunks):
            try:
                sem_scores = semantic_scores_for_query(search_query, _emb_idx)
            except Exception:
                log.exception("Semantic scoring failed (stream): %s", search_query[:80])

        top_chunks = retrieve_relevant_chunks(
            search_query,
            all_chunks,
            top_k=runtime_config["retrieval_top_k"] * runtime_config["retrieval_overfetch_multiplier"],
            semantic_scores=sem_scores,
        )
        top_chunks = merge_adjacent_chunks(top_chunks, all_chunks)

        if not top_chunks:
            return jsonify(
                {
                    "answer": fallback_message(language),
                    "sources": [],
                    "follow_up_questions": [],
                    "language": language,
                }
            )

        gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not gemini_key:
            return jsonify({"error": "Server is missing GEMINI_API_KEY environment variable."}), 500

        all_retrieved_chunks = list(top_chunks)
        if runtime_config["enable_rerank"] and len(top_chunks) > runtime_config["retrieval_top_k"]:
            top_chunks = rerank_chunks_with_llm(
                question, top_chunks, runtime_config["retrieval_top_k"]
            )

        context_blocks = []
        for idx, item in enumerate(top_chunks, start=1):
            page_info = f", page {item.get('page_start')}" if item.get("page_start") else ""
            chunk_text = summarize_snippet(item.get("text", ""), limit=runtime_config["context_snippet_limit"])
            context_blocks.append(
                f"Source {idx} ({item['document_name']}{page_info}, chunk {item.get('chunk_id', 'n/a')}):\n{chunk_text}"
            )
        context_text = "\n\n".join(context_blocks)

        prompt = build_assistant_prompt(
            question=question,
            language=language,
            context_text=context_text,
            history=history,
        )

        sources = [
            {
                "document_name": item["document_name"],
                "snippet": summarize_snippet(item.get("preview") or item["text"]),
                "chunk_id": item.get("chunk_id"),
                "page": item.get("page_start"),
                "score": item["score"],
            }
            for item in top_chunks
        ]

        def generate_sse():
            try:
                full_text = []

                discovered = _get_cached_models()
                candidates = order_model_candidates(discovered)
                stream = None
                for model_name in candidates:
                    try:
                        model = genai.GenerativeModel(model_name)
                        gen_cfg = genai.GenerationConfig(temperature=runtime_config["gemini_temperature"], max_output_tokens=2500)
                        stream = model.generate_content(prompt, generation_config=gen_cfg, stream=True)
                        break
                    except Exception as e:
                        log.warning("Stream model %s failed: %s", model_name, e)
                        continue

                if stream is None:
                    fallback = fallback_message(language)
                    yield f"data: {json.dumps({'token': fallback})}\n\n"
                    yield f"data: {json.dumps({'done': True, 'sources': [], 'language': language})}\n\n"
                    return

                for chunk in stream:
                    try:
                        token = chunk.text or ""
                    except (ValueError, AttributeError):
                        token = ""
                    if token:
                        full_text.append(token)
                        yield f"data: {json.dumps({'token': token})}\n\n"

                # Parse the complete response for follow-ups and confidence.
                llm_text = "".join(full_text).strip()
                answer_payload = parse_answer_payload(llm_text, language)
                answer_text = answer_payload["answer"]
                follow_ups = answer_payload["follow_up_questions"]
                confidence = answer_payload["confidence"]

                # If the model wrapped the answer in JSON/fences, overwrite the
                # streamed tokens with the clean extracted answer so the frontend
                # renders plain text rather than a raw JSON blob.
                if answer_text.strip() != llm_text:
                    yield f"data: {json.dumps({'replace': answer_text})}\n\n"

                # If the LLM returned fallback, try retry logic.
                if runtime_config["enable_retry"] and is_fallback_answer(answer_text) and all_retrieved_chunks:
                    expanded_chunks = _expanded_retrieval(
                        question, all_chunks, runtime_config["retrieval_top_k"],
                        semantic_scores=sem_scores,
                    )
                    seen_ids = {c["chunk_id"] for c in all_retrieved_chunks}
                    combined = list(all_retrieved_chunks)
                    for c in expanded_chunks:
                        if c["chunk_id"] not in seen_ids:
                            combined.append(c)
                            seen_ids.add(c["chunk_id"])

                    retry_blocks = []
                    for i, itm in enumerate(combined, start=1):
                        pi = f", page {itm.get('page_start')}" if itm.get("page_start") else ""
                        ct = summarize_snippet(itm.get("text", ""), limit=runtime_config["context_snippet_limit"])
                        retry_blocks.append(f"Source {i} ({itm['document_name']}{pi}, chunk {itm.get('chunk_id','n/a')}):\n{ct}")

                    retry_prompt = build_assistant_prompt_retry(
                        question=question,
                        language=language,
                        context_text="\n\n".join(retry_blocks),
                        history=history,
                    )
                    try:
                        retry_resp = generate_with_model_fallback(retry_prompt, 0.0)
                        retry_text = ((retry_resp.text or "") if retry_resp else "").strip()
                        retry_payload = parse_answer_payload(retry_text, language)
                        if not is_fallback_answer(retry_payload["answer"]):
                            # Send a replace event so frontend swaps the streamed text.
                            yield f"data: {json.dumps({'replace': retry_payload['answer']})}\n\n"
                            follow_ups = retry_payload["follow_up_questions"]
                            confidence = retry_payload["confidence"]
                            answer_text = retry_payload["answer"]
                    except Exception as e:
                        log.warning("Stream retry failed: %s", e)

                final_sources = sources if not is_fallback_answer(answer_text) else []
                final_followups = follow_ups if not is_fallback_answer(answer_text) else []

                # Populate server-side cache so repeated questions skip the full pipeline.
                # Only cache when there is no history (context-free questions) and the
                # answer is meaningful (not a fallback).
                if not history and not is_fallback_answer(answer_text):
                    cached_result = {
                        "answer": answer_text,
                        "sources": final_sources,
                        "follow_up_questions": final_followups,
                        "language": language,
                        "confidence": confidence,
                    }
                    if len(_response_cache) >= _RESPONSE_CACHE_MAX:
                        _response_cache.pop(next(iter(_response_cache)))
                    _response_cache[_stream_cache_key] = cached_result

                yield f"data: {json.dumps({'done': True, 'sources': final_sources, 'follow_up_questions': final_followups, 'language': language, 'confidence': confidence})}\n\n"

            except Exception as exc:
                log.exception("SSE stream error")
                yield f"data: {json.dumps({'error': str(exc)})}\n\n"

        return Response(generate_sse(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return app


# ── In-memory store cache ─────────────────────────────────────────
_store_cache: dict = {"data": None, "mtime": 0}


def load_store() -> dict:
    """Load chunks.json, caching in memory until the file changes."""
    if not STORE_PATH.exists():
        _store_cache["data"] = None
        _store_cache["mtime"] = 0
        return {"documents": [], "chunks": []}

    try:
        current_mtime = STORE_PATH.stat().st_mtime_ns
    except OSError:
        current_mtime = 0

    if _store_cache["data"] is not None and current_mtime == _store_cache["mtime"]:
        return _store_cache["data"]

    try:
        with STORE_PATH.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (json.JSONDecodeError, OSError):
        return {"documents": [], "chunks": []}

    documents = data.get("documents") if isinstance(data, dict) else []
    chunks = data.get("chunks") if isinstance(data, dict) else []

    if not isinstance(documents, list):
        documents = []
    if not isinstance(chunks, list):
        chunks = []

    result = {"documents": documents, "chunks": chunks}
    _store_cache["data"] = result
    _store_cache["mtime"] = current_mtime
    return result


def save_store(store: dict) -> None:
    with STORE_PATH.open("w", encoding="utf-8") as file:
        json.dump(store, file, ensure_ascii=False, indent=2)
    # Invalidate in-memory cache so next load_store() reads fresh data.
    _store_cache["data"] = None
    _store_cache["mtime"] = 0


HASH_PATH = DATA_DIR / "chunks_hash.txt"


def _compute_uploads_hash() -> str:
    """Return a hex digest that changes whenever any PDF in uploads/ *content* changes.

    Uses a fast partial-hash (first + last 64 KB of each file) so that
    file-system metadata updates (e.g. OneDrive sync touching mtime) do NOT
    trigger an unnecessary chunk rebuild.
    """
    SAMPLE = 65536  # 64 KB per end
    h = hashlib.sha256()
    for pdf_path in sorted(UPLOAD_DIR.glob("*.pdf")):
        try:
            size = pdf_path.stat().st_size
            h.update(f"{pdf_path.name}:{size}:".encode())
            with pdf_path.open("rb") as fh:
                h.update(fh.read(SAMPLE))
                if size > SAMPLE * 2:
                    fh.seek(-SAMPLE, 2)
                    h.update(fh.read(SAMPLE))
        except OSError:
            pass
    return h.hexdigest()


def _migrate_root_pdfs_to_uploads() -> None:
    """One-time migration: move any root-level .pdf files into uploads/."""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    legacy_names = ["MERGED_PUBLIC_PDF_FILES.pdf"]
    for name in legacy_names:
        src = BASE_DIR / name
        if src.exists() and not (UPLOAD_DIR / name).exists():
            shutil.move(str(src), str(UPLOAD_DIR / name))
            log.info("Migrated '%s' → uploads/%s", name, name)


def rebuild_documents_store_if_needed() -> None:
    """Skip the expensive PDF parsing when nothing has changed."""
    current_hash = _compute_uploads_hash()

    if STORE_PATH.exists() and HASH_PATH.exists():
        try:
            saved_hash = HASH_PATH.read_text(encoding="utf-8").strip()
            if saved_hash == current_hash:
                return  # PDFs unchanged – reuse cached chunks
        except OSError:
            pass

    log.info("PDF set changed – rebuilding chunk store...")
    _rebuild_documents_store()
    try:
        HASH_PATH.write_text(current_hash, encoding="utf-8")
    except OSError:
        pass


def _rebuild_documents_store() -> None:
    """Synchronously process all PDFs in uploads/ and write chunks.json."""
    rebuilt_documents: list[str] = []
    rebuilt_chunks: list[dict] = []

    for pdf_path in sorted(UPLOAD_DIR.glob("*.pdf")):
        if not pdf_path.is_file():
            continue
        chunks = process_pdf_file(pdf_path, pdf_path.name)
        if not chunks:
            continue
        rebuilt_documents.append(pdf_path.name)
        rebuilt_chunks.extend(chunks)

    save_store({"documents": rebuilt_documents, "chunks": rebuilt_chunks})
    log.info(
        "Chunk store rebuilt: %d documents, %d chunks.",
        len(rebuilt_documents),
        len(rebuilt_chunks),
    )


# ── Background reindex ────────────────────────────────────────────

def trigger_reindex() -> None:
    """Start a background reindex thread if one is not already running."""
    global _reindex_thread
    with _live_lock:
        if _live_state["status"] in ("processing", "embedding"):
            log.info("Reindex already in progress – skipping duplicate trigger.")
            return
        _live_state["status"] = "processing"
        _live_state["message"] = "Starting reindex..."
        _live_state["progress"] = 0
    t = threading.Thread(target=_do_reindex, daemon=True, name="reindex")
    _reindex_thread = t
    t.start()


def _start_upload_watcher(interval: int = 30) -> None:
    """Daemon thread: polls uploads/ every *interval* seconds and triggers a
    reindex if any PDF is added, removed, or replaced outside the API
    (e.g. user manually drops or deletes a file on disk)."""
    def _watch() -> None:
        # Let startup reindex get a head-start before the first poll.
        time.sleep(interval)
        last_hash = _compute_uploads_hash()
        while True:
            time.sleep(interval)
            new_hash = _compute_uploads_hash()
            if new_hash != last_hash:
                log.info(
                    "Upload folder changed outside the UI — triggering reindex..."
                )
                last_hash = new_hash
                trigger_reindex()

    t = threading.Thread(target=_watch, daemon=True, name="upload-watcher")
    t.start()


def _set_live_status(status: str, message: str, progress: int) -> None:
    with _live_lock:
        _live_state["status"] = status
        _live_state["message"] = message
        _live_state["progress"] = progress


def _do_reindex() -> None:
    """Background thread: rebuild chunk store + embeddings, then hot-swap the index."""
    try:
        # ── Step 1: Parse PDFs → chunks ──────────────────────────
        pdf_files = sorted(UPLOAD_DIR.glob("*.pdf"))
        total_pdfs = len(pdf_files)
        _set_live_status("processing", f"Processing {total_pdfs} PDF file(s)...", 5)

        all_documents: list[str] = []
        all_chunks: list[dict] = []

        for i, pdf_path in enumerate(pdf_files):
            _set_live_status(
                "processing",
                f"Processing '{pdf_path.name}' ({i + 1}/{total_pdfs})...",
                5 + int(25 * i / max(total_pdfs, 1)),
            )
            chunks = process_pdf_file(pdf_path, pdf_path.name)
            if chunks:
                all_documents.append(pdf_path.name)
                all_chunks.extend(chunks)

        save_store({"documents": all_documents, "chunks": all_chunks})
        current_hash = _compute_uploads_hash()
        try:
            HASH_PATH.write_text(current_hash, encoding="utf-8")
        except OSError:
            pass

        if not all_chunks:
            _set_live_status("ready", "No documents indexed.", 100)
            with _live_lock:
                _live_state["embedding_index"] = []
            return

        # ── Step 2: Check / build embeddings ─────────────────────
        _set_live_status("embedding", "Checking embedding cache...", 32)

        from utils.embedder import (
            load_cached_embeddings,
            save_embeddings_cache,
            embed_texts,
            _chunks_fingerprint,
            _BATCH_SIZE,
            _BATCH_DELAY_SECONDS,
        )

        cached = load_cached_embeddings(all_chunks)
        if cached is not None:
            with _live_lock:
                _live_state["embedding_index"] = cached
            _set_live_status(
                "ready",
                f"Ready. {len(all_documents)} document(s), {len(all_chunks)} chunks.",
                100,
            )
            log.info("Reindex complete (embeddings from cache). %d chunks.", len(all_chunks))
            # Invalidate response cache so next question uses fresh data.
            _response_cache.clear()
            return

        _set_live_status(
            "embedding",
            f"Building semantic index for {len(all_chunks)} chunks…",
            35,
        )

        texts = [c.get("text", "") for c in all_chunks]
        total_batches = (len(texts) + _BATCH_SIZE - 1) // _BATCH_SIZE
        all_embeddings: list[list[float]] = []

        for batch_num, start in enumerate(range(0, len(texts), _BATCH_SIZE), start=1):
            batch = texts[start : start + _BATCH_SIZE]
            for attempt in range(5):
                try:
                    result = genai.embed_content(model="models/gemini-embedding-001", content=batch)
                    all_embeddings.extend(result["embedding"])
                    break
                except Exception as exc:
                    if "429" in str(exc) and attempt < 4:
                        wait = _BATCH_DELAY_SECONDS * (2 ** attempt)
                        time.sleep(wait)
                    else:
                        # Fill missing embeddings with zeros so index stays aligned.
                        all_embeddings.extend([[0.0] * 768] * len(batch))
                        log.warning("Embedding batch %d failed: %s", batch_num, exc)
                        break
            if batch_num < total_batches:
                time.sleep(_BATCH_DELAY_SECONDS)
            progress = 35 + int(60 * batch_num / total_batches)
            _set_live_status(
                "embedding",
                f"Building semantic index… ({batch_num}/{total_batches} batches)",
                progress,
            )

        save_embeddings_cache(all_chunks, all_embeddings)

        with _live_lock:
            _live_state["embedding_index"] = all_embeddings

        _set_live_status(
            "ready",
            f"Ready. {len(all_documents)} document(s), {len(all_chunks)} chunks.",
            100,
        )
        log.info(
            "Reindex complete. %d documents, %d chunks, %d embeddings.",
            len(all_documents),
            len(all_chunks),
            len(all_embeddings),
        )
        # Invalidate response cache so next question uses fresh data.
        _response_cache.clear()

    except Exception:
        log.exception("Background reindex failed")
        _set_live_status("error", "Indexing failed. Check server logs.", 0)



def summarize_snippet(text: str, limit: int = 260) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rstrip() + "..."


def detect_language(text: str) -> str:
    arabic_chars = re.findall(r"[\u0600-\u06FF]", text or "")
    latin_chars = re.findall(r"[A-Za-z]", text or "")
    if arabic_chars and len(arabic_chars) >= max(2, len(latin_chars) // 2):
        return "ar"
    return "en"


def is_greeting(text: str) -> bool:
    normalized = normalize_for_compare(text)
    if not normalized:
        return False

    greeting_phrases = {
        "hi",
        "hello",
        "hey",
        "good morning",
        "good afternoon",
        "good evening",
        "salam",
        "السلام عليكم",
        "سلام عليكم",
        "السلام عليکم",
        "مرحبا",
        "اهلا",
        "اهلا وسهلا",
        "هلا",
        "هلو",
        "هاي",
    }

    if normalized in greeting_phrases:
        return True

    # Support short greeting messages with extra punctuation or added words.
    for phrase in greeting_phrases:
        if normalized.startswith(phrase + " ") or normalized.endswith(" " + phrase):
            return True

    return False


def greeting_response(language: str) -> str:
    if language == "ar":
        return "وعليكم السلام، أهلا وسهلا بك. كيف أقدر أساعدك اليوم؟"
    return "Hello, welcome. How can I help you today?"


# ── Pre-defined FAQ (instant answers, no RAG needed) ─────────────────────────
# Each entry: "en" = English patterns, "ar" = Arabic patterns (exact match),
# "ans_en" / "ans_ar" = pre-written answers.
_FAQ: list[dict] = [
    {
        "en": {"who are you", "what are you", "what is this", "what is this chatbot", "about you", "tell me about yourself"},
        "ar": {"من أنت", "من انت", "ما هذا", "ما هذا التطبيق", "عرفني بنفسك"},
        "ans_en": "I'm the Dhofar Insurance Enterprise AI Assistant — an AI trained on official company documents. I can answer questions about insurance products, policies, claims, and HR procedures in English or Arabic.",
        "ans_ar": "أنا المساعد الذكي لشركة ظفار للتأمين، مدرَّب على الوثائق الرسمية للشركة. يمكنني الإجابة على أسئلتك حول التأمين والمطالبات والسياسات وإجراءات الشركة بالعربية أو الإنجليزية.",
    },
    {
        "en": {"what can you do", "what do you do", "capabilities", "features", "how can you help", "how can you help me"},
        "ar": {"ماذا تستطيع أن تفعل", "ماذا تفعل", "كيف تساعدني", "كيف تساعدي", "ما هي قدراتك"},
        "ans_en": "I can answer questions about Dhofar Insurance products, policies, claims process, HR procedures, and company regulations — all sourced directly from official documents. I support both English and Arabic.",
        "ans_ar": "أستطيع الإجابة عن منتجات ظفار للتأمين وسياساتها وإجراءات المطالبات والموارد البشرية واللوائح — مباشرةً من الوثائق الرسمية. أدعم العربية والإنجليزية.",
    },
    {
        "en": {"help", "how does this work", "how to use this", "how do i use this", "what should i ask", "how to use"},
        "ar": {"مساعدة", "كيف يعمل هذا", "كيف أستخدم", "كيف أستخدم هذا", "ماذا أسأل"},
        "ans_en": "Type your question below in English or Arabic. For best results, be specific — for example: \"What is the motor insurance excess?\" or \"What are the annual leave rules?\"",
        "ans_ar": "اكتب سؤالك أدناه بالعربية أو الإنجليزية. للحصول على أفضل النتائج، كن محددًا — مثل: \"ما هو خصم تأمين السيارات؟\" أو \"ما هي قواعد الإجازة السنوية؟\"",
    },
    {
        "en": {"are you a bot", "are you ai", "are you a robot", "are you human", "are you real", "is this ai", "is this a bot", "are you a person"},
        "ar": {"هل أنت روبوت", "هل أنت ذكاء اصطناعي", "هل أنت انسان", "هل هذا ذكاء اصطناعي"},
        "ans_en": "Yes, I'm an AI assistant powered by Google Gemini and a document retrieval system trained on Dhofar Insurance's internal documents. I'm not a human.",
        "ans_ar": "نعم، أنا مساعد ذكاء اصطناعي مدعوم بنموذج Google Gemini ومدرَّب على وثائق ظفار للتأمين الداخلية. لستُ إنسانًا.",
    },
    {
        "en": {"what languages do you support", "do you speak arabic", "can you answer in arabic", "what language can i use", "do you understand arabic", "languages supported"},
        "ar": {"ما اللغات التي تدعمها", "هل تتكلم عربي", "هل تفهم العربية", "اللغات"},
        "ans_en": "I support both English and Arabic. Write your question in either language and I will respond in the same language.",
        "ans_ar": "أدعم العربية والإنجليزية. اكتب سؤالك بأي منهما وسأرد بنفس اللغة.",
    },
    {
        "en": {"what is dhofar insurance", "tell me about dhofar insurance", "about dhofar", "about dhofar insurance"},
        "ar": {"ما هي ظفار للتأمين", "عرفني بظفار للتأمين", "عن ظفار للتأمين", "ما هي شركة ظفار"},
        "ans_en": "Dhofar Insurance Company (S.A.O.G.) is an Omani insurance company offering a wide range of solutions including motor, medical, life, property, marine, and liability insurance. Ask me anything specific and I'll look it up in the official documents.",
        "ans_ar": "شركة ظفار للتأمين (ش.م.ع.ع) شركة تأمين عُمانية تقدم حلولًا شاملة تشمل: تأمين السيارات والتأمين الطبي وتأمين الحياة والممتلكات والبحري والمسؤولية. اسألني عن أي تفاصيل وسأبحث عنها في الوثائق الرسمية.",
    },
    {
        "en": {"thank you", "thanks", "thank u", "thx", "ty", "great thanks", "many thanks", "much appreciated"},
        "ar": {"شكرا", "شكرًا", "شكرا لك", "شكرا جزيلا", "جزيل الشكر", "مشكور"},
        "ans_en": "You're welcome! Feel free to ask if you have any other questions.",
        "ans_ar": "على الرحب والسعة! لا تتردد في السؤال إذا كان لديك أي استفسار آخر.",
    },
    {
        "en": {"bye", "goodbye", "see you", "see you later", "take care", "good night"},
        "ar": {"مع السلامة", "وداعا", "في أمان الله", "باي", "إلى اللقاء"},
        "ans_en": "Goodbye! Come back anytime you have questions.",
        "ans_ar": "مع السلامة! عد إلينا في أي وقت لديك أسئلة.",
    },
]


def find_faq_answer(text: str, language: str) -> str | None:
    """Return a pre-defined answer if the question exactly matches a FAQ pattern."""
    normalized = normalize_for_compare(text)
    # Normalize common Arabic character variants before matching
    ar_norm = normalized.translate(str.maketrans("أإآىة", "ااايه"))
    lang_key = "ar" if language == "ar" else "en"
    ans_key = "ans_ar" if language == "ar" else "ans_en"
    for entry in _FAQ:
        patterns = entry[lang_key]
        check = ar_norm if language == "ar" else normalized
        norm_patterns = (
            {normalize_for_compare(p).translate(str.maketrans("أإآىة", "ااايه")) for p in patterns}
            if language == "ar"
            else patterns
        )
        if check in norm_patterns:
            return entry[ans_key]
    return None


def localize_text(message_en: str, language: str) -> str:
    if language == "ar":
        mapping = {
            "Please enter a question before sending.": "يرجى كتابة سؤال قبل الإرسال.",
        }
        return mapping.get(message_en, message_en)
    return message_en


def fallback_message(language: str) -> str:
    return FALLBACK_MESSAGES.get(language, FALLBACK_MESSAGES["en"])


def is_fallback_answer(answer_text: str) -> bool:
    normalized = normalize_for_compare(answer_text)
    fallback_values = [normalize_for_compare(v) for v in FALLBACK_MESSAGES.values()]
    return normalized in fallback_values


def normalize_for_compare(text: str) -> str:
    # Strip leading/trailing punctuation so "Hello!" matches "hello" in FAQ/cache.
    cleaned = re.sub(r"[^\w\s\u0600-\u06FF]", " ", (text or "").strip().lower())
    return " ".join(cleaned.split())


def sanitize_history(raw_history) -> list[dict]:
    if not isinstance(raw_history, list):
        return []

    cleaned: list[dict] = []
    for item in raw_history[-6:]:
        if not isinstance(item, dict):
            continue
        role = (item.get("role") or "").strip().lower()
        content = (item.get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        cleaned.append({"role": role, "content": content[:1000]})
    return cleaned


def _parse_chunk_index(chunk_id: str) -> int | None:
    """Extract the numeric index from a chunk_id like 'docname-42'."""
    parts = (chunk_id or "").rsplit("-", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return int(parts[1])
    return None


# Cache for the chunk position lookup used by merge_adjacent_chunks.
# Rebuilt only when the chunks list content changes.
_chunk_lookup_cache: dict = {"chunks_sig": None, "lookup": {}}


def _chunks_sig(chunks: list[dict]) -> str:
    """Signature to detect when the chunks list has changed.

    Samples ~20 chunk_ids spread evenly so any addition or removal of a PDF
    (even when the total count stays the same) triggers a cache rebuild.
    """
    if not chunks:
        return "empty"
    n = len(chunks)
    step = max(1, n // 20)
    parts = [str(n)]
    for i in range(0, n, step):
        parts.append(chunks[i].get("chunk_id", ""))
    return ":".join(parts)


def _get_chunk_lookup(all_chunks: list[dict]) -> dict[tuple[str, int], int]:
    """Return (document_name, numeric_index) → position in all_chunks, cached."""
    cache = _chunk_lookup_cache
    sig = _chunks_sig(all_chunks)
    if cache["chunks_sig"] != sig:
        lookup: dict[tuple[str, int], int] = {}
        for pos, c in enumerate(all_chunks):
            idx = _parse_chunk_index(c.get("chunk_id", ""))
            if idx is not None:
                lookup[(c["document_name"], idx)] = pos
        cache["chunks_sig"] = sig
        cache["lookup"] = lookup
    return cache["lookup"]


def merge_adjacent_chunks(
    top_chunks: list[dict],
    all_chunks: list[dict],
) -> list[dict]:
    """When two retrieved chunks are neighbours, merge the gap chunk's text.

    If chunk N is in the results and chunk N+1 (or N-1) exists in the full
    corpus but is *not* already in the results, append its text to chunk N
    so the model sees the complete passage.  This prevents answers from being
    cut off at a chunk boundary.
    """
    if not top_chunks or not all_chunks:
        return top_chunks

    chunk_lookup = _get_chunk_lookup(all_chunks)

    # Track which chunk_ids are already in the result set
    result_ids = {c.get("chunk_id") for c in top_chunks}

    merged: list[dict] = []
    for chunk in top_chunks:
        idx = _parse_chunk_index(chunk.get("chunk_id", ""))
        if idx is None:
            merged.append(chunk)
            continue

        doc = chunk["document_name"]
        combined_text = chunk.get("text", "")

        # Check the next adjacent chunk
        next_key = (doc, idx + 1)
        if next_key in chunk_lookup:
            next_pos = chunk_lookup[next_key]
            next_chunk = all_chunks[next_pos]
            next_id = next_chunk.get("chunk_id", "")
            if next_id not in result_ids:
                combined_text = combined_text.rstrip() + "\n" + next_chunk.get("text", "")

        enriched = dict(chunk)
        enriched["text"] = combined_text
        merged.append(enriched)

    return merged


def _expanded_retrieval(
    question: str,
    all_chunks: list[dict],
    top_k: int,
    semantic_scores: list[float] | None = None,
) -> list[dict]:
    """Run secondary retrievals with rephrased queries to find definitional chunks.

    For short queries like 'what is FSA', TF-IDF favours chunks that repeat
    the term many times over chunks that define it.  This function creates
    alternative query phrasings and merges the results.
    """
    # Extract the core terms (strip common question words).
    q_lower = question.lower().strip()
    for prefix in ("what is ", "what are ", "define ", "explain ", "ما هو ", "ما هي ", "ما معنى "):
        if q_lower.startswith(prefix):
            q_lower = q_lower[len(prefix):]
            break

    core_term = q_lower.strip()
    if not core_term:
        return []

    alt_queries = [
        f"{core_term} definition meaning",
        f"{core_term} stands for",
        f"{core_term} policy regulation authority",
    ]

    seen_ids: set[str] = set()
    results: list[dict] = []
    for alt_q in alt_queries:
        hits = retrieve_relevant_chunks(
            alt_q, all_chunks, top_k=top_k, semantic_scores=semantic_scores,
        )
        for h in hits:
            cid = h["chunk_id"]
            if cid not in seen_ids:
                seen_ids.add(cid)
                results.append(h)

    return results


def expand_query_with_history(question: str, history: list[dict]) -> str:
    """Enrich a short / ambiguous follow-up with key terms from recent history.

    If the question already looks self-contained (long enough and has clear
    nouns/terms), return it unchanged.  Otherwise, prepend the most recent
    user question and a compact summary of the assistant answer so the
    retriever has enough signal.
    """
    words = question.split()
    # Heuristic: questions with 6+ words usually carry enough context on their own.
    if len(words) >= 6 or not history:
        return question

    # Walk history backwards to find the last user turn and the assistant reply.
    last_user_q = ""
    last_assistant_a = ""
    for entry in reversed(history):
        if entry["role"] == "assistant" and not last_assistant_a:
            # Take only the first 200 chars of the answer as keyword context.
            last_assistant_a = entry["content"][:200]
        elif entry["role"] == "user" and not last_user_q:
            last_user_q = entry["content"]
        if last_user_q and last_assistant_a:
            break

    if not last_user_q:
        return question

    # Build an expanded query: previous question + compact answer context + current question.
    parts = [last_user_q]
    if last_assistant_a:
        parts.append(last_assistant_a)
    parts.append(question)
    return " ".join(parts)


def translate_query_for_retrieval(question: str) -> str:
    """Translate an Arabic query to English for better retrieval against English docs.

    Uses the lightweight utility model for speed, and caches results so
    repeated or similar Arabic queries skip the LLM call entirely.
    Falls back to the original question on any error.
    """
    cache_key = question.strip().lower()
    if cache_key in _translate_cache:
        return _translate_cache[cache_key]

    prompt = (
        "Translate the following Arabic insurance/HR/legal question to English. "
        "Return ONLY the English translation — no explanation, no extra text.\n\n"
        f"Arabic: {question}\nEnglish:"
    )
    translated = generate_with_utility_model(prompt)
    if translated and len(translated) < 500:
        # Evict oldest entry when cache is full (FIFO).
        if len(_translate_cache) >= _TRANSLATE_CACHE_MAX:
            _translate_cache.pop(next(iter(_translate_cache)))
        _translate_cache[cache_key] = translated
        return translated
    return question


def rerank_chunks_with_llm(
    question: str,
    chunks: list[dict],
    keep: int,
) -> list[dict]:
    """Return the top *keep* chunks in relevance order.

    Chunks arrive already sorted by the combined TF-IDF + semantic score
    computed in retrieve_relevant_chunks().  This function simply slices
    to *keep* — no extra API call, no re-blending needed.
    """
    return chunks[:keep]


def _parse_int_list(text: str) -> list[int]:
    """Extract a list of integers from LLM output like '[3, 1, 7]'."""
    import re as _re
    # Find the JSON array in the response.
    match = _re.search(r"\[[\d\s,]+\]", text)
    if not match:
        return []
    try:
        result = json.loads(match.group())
        if isinstance(result, list) and all(isinstance(x, int) for x in result):
            return result
    except (json.JSONDecodeError, ValueError):
        pass
    return []


def _format_history_block(history: list[dict]) -> str:
    if not history:
        return ""
    rendered = [f"{item['role'].title()}: {item['content']}" for item in history]
    return "\n\nRecent chat history:\n" + "\n".join(rendered)


_JSON_SCHEMA_BLOCK = (
    "Output strict JSON only — no markdown, no extra text — using this schema:\n"
    "{\n"
    '  "answer": "string (thorough, complete answer — include all relevant conditions, amounts, percentages, dates, durations, and article/clause numbers exactly as stated in the context; no source citations)",\n'
    '  "confidence": "high|medium|low",\n'
    '  "follow_up_questions": ["q1", "q2", "q3"]\n'
    "}\n"
    "Rules for 'answer': be comprehensive — if the context defines multiple conditions, list ALL of them. "
    "Quote exact figures (amounts, percentages, days, months) verbatim from the documents. "
    "Do not summarise away important details.\n"
)

_FEW_SHOT_EXAMPLES = (
    "--- EXAMPLE (return bare JSON, no markdown fences) ---\n"
    "User question: ما هي مدة الإشعار لإنهاء العقد؟\n"
    "Document context: Source 1 (MERGED_PUBLIC_PDF_FILES.pdf, page 45): وفقاً للمادة 36، يجوز لأي طرف إنهاء العقد بإشعار كتابي مدته 30 يوماً.\n"
    "Response:\n"
    "{\n"
    '  "answer": "وفقاً للمادة 36، يجوز لأي من الطرفين إنهاء عقد العمل بتقديم إشعار كتابي مدته 30 يوماً للطرف الآخر. [1]",\n'
    '  "confidence": "high",\n'
    '  "follow_up_questions": ["ماذا يحدث إذا لم يتم تقديم الإشعار المطلوب؟", "هل توجد استثناءات لمتطلب الإشعار البالغ 30 يوماً؟", "هل يمكن التنازل عن فترة الإشعار باتفاق كتابي متبادل؟"]\n'
    "}\n\n"
)


def build_assistant_prompt(question: str, language: str, context_text: str, history: list[dict]) -> str:
    language_label = "Arabic" if language == "ar" else "English"
    history_block = _format_history_block(history)

    return (
        "You are Dhofar Insurance Knowledge Desk, a professional internal enterprise assistant for Dhofar Insurance Company S.A.O.G.\n"
        "Your answers must be formal, precise, and professional — suitable for an insurance company environment.\n"
        "Use ONLY the provided document context. Never invent or assume facts not present in the sources.\n"
        f"IMPORTANT: You MUST respond entirely in {language_label}. Do not mix languages.\n"
        "ACCURACY RULES — follow these strictly:\n"
        "  1. Quote exact numbers, amounts, percentages, durations, and dates directly from the context — never paraphrase them.\n"
        "  2. Mention article numbers, clause numbers, or section headings when the source explicitly references them.\n"
        "  3. If multiple conditions, exceptions, or requirements exist, list ALL of them — do not omit any.\n"
        "  4. Synthesise information from all relevant sources when the full answer spans multiple passages.\n"
        "  5. After each factual statement that comes from a specific source, add the source number in square brackets, e.g. [1] or [2]. Use the source numbers from the document context header (Source 1, Source 2, etc.).\n"
        "If the user asks about an abbreviation or acronym, infer its full name and purpose from how it is used in the context.\n"
        "If the context contains relevant information — even partial or indirect — provide it as a formal answer.\n"
        "Only return the fallback message if the context has absolutely no relevant information whatsoever.\n"
        f"English fallback: {FALLBACK_MESSAGES['en']}\n"
        f"Arabic fallback: {FALLBACK_MESSAGES['ar']}\n\n"
        + _JSON_SCHEMA_BLOCK
        + f"follow_up_questions must contain exactly 3 helpful, specific, context-aware questions written entirely in {language_label}.\n\n"
        + _FEW_SHOT_EXAMPLES
        + "--- NOW ANSWER THE FOLLOWING ---\n"
        f"User question:\n{question}\n"
        f"{history_block}\n\n"
        f"Document context:\n{context_text}"
    )


def build_assistant_prompt_retry(question: str, language: str, context_text: str, history: list[dict]) -> str:
    """Softer prompt used when the first attempt returned the fallback answer."""
    language_label = "Arabic" if language == "ar" else "English"
    history_block = _format_history_block(history)

    return (
        "You are Dhofar Insurance Knowledge Desk, a professional internal enterprise assistant for Dhofar Insurance Company S.A.O.G.\n"
        f"IMPORTANT: You MUST respond entirely in {language_label}. Do not mix languages.\n"
        "A previous attempt could not find a direct answer. Examine every source carefully this time.\n"
        "Find ANY relevant information — even indirect or partial — and present it professionally.\n"
        "Quote exact figures, amounts, percentages, durations, and article numbers directly from the context.\n"
        "Do NOT include any source citations, reference numbers, or document names in the answer text.\n"
        "If the user asks about an abbreviation or acronym, infer its meaning from how it appears in context.\n"
        "Set confidence to 'medium' or 'low' for indirect or partial matches.\n"
        "Only return the fallback if the context is completely unrelated to the question.\n\n"
        + _JSON_SCHEMA_BLOCK
        + f"follow_up_questions must contain exactly 3 questions written entirely in {language_label}.\n\n"
        + _FEW_SHOT_EXAMPLES
        + "--- NOW ANSWER THE FOLLOWING ---\n"
        f"User question:\n{question}\n"
        f"{history_block}\n\n"
        f"Document context:\n{context_text}"
    )


def parse_answer_payload(llm_text: str, language: str) -> dict:
    fallback = fallback_message(language)
    default = {
        "answer": fallback,
        "confidence": "low",
        "follow_up_questions": [],
    }

    if not llm_text:
        return default

    parsed = try_parse_json_object(llm_text)
    if not isinstance(parsed, dict):
        answer = llm_text.strip()
        return {
            "answer": answer if answer else fallback,
            "confidence": "low",
            "follow_up_questions": heuristic_followups(language),
        }

    answer = (parsed.get("answer") or "").strip() or fallback
    answer = strip_source_citations(answer)
    confidence = (parsed.get("confidence") or "low").strip().lower()
    if confidence not in {"high", "medium", "low"}:
        confidence = "low"

    follow_ups = sanitize_followups(parsed.get("follow_up_questions"), language)
    if is_fallback_answer(answer):
        follow_ups = []

    return {
        "answer": answer,
        "confidence": confidence,
        "follow_up_questions": follow_ups,
    }


def strip_source_citations(text: str) -> str:
    """Remove verbose source/document citations but KEEP [n] numeric markers.

    The LLM is now instructed to embed [1], [2], … in the answer so the
    frontend can render them as clickable links to the source PDF page.
    We only strip the long-form citation patterns that clutter the text.
    """
    # Remove patterns like (Source: ..., Page 123)
    text = re.sub(r'\(\s*Source:[^)]*\)', '', text, flags=re.IGNORECASE)
    # Remove patterns like [Source: ...]
    text = re.sub(r'\[\s*Source:[^\]]*\]', '', text, flags=re.IGNORECASE)
    # Remove patterns like (MERGED_PUBLIC_PDF_FILES.pdf, Page 123)
    text = re.sub(r'\([^)]*\.pdf[^)]*\)', '', text, flags=re.IGNORECASE)
    # Do NOT remove [n] numeric markers — those are intentional citation links.
    # Clean up leftover multiple spaces.
    text = re.sub(r'  +', ' ', text).strip()
    return text


def _sanitize_json_controls(s: str) -> str:
    """Escape raw control characters inside JSON string values.

    Gemini sometimes emits actual newline / tab chars inside JSON string values
    instead of the required \\n / \\t escape sequences, which makes json.loads
    raise InvalidControlCharacter.  This function walks the text as a simple
    state machine, escaping control chars that appear inside string literals
    while leaving structural whitespace (between keys/values) untouched.
    """
    result: list[str] = []
    in_string = False
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "\\" and in_string:
            # Consume escape sequence as-is (already valid)
            result.append(ch)
            if i + 1 < len(s):
                result.append(s[i + 1])
                i += 2
            else:
                i += 1
            continue
        if ch == '"':
            in_string = not in_string
            result.append(ch)
        elif in_string and ch in "\n\r\t\x08\x0c":
            # Escape control characters that are illegal bare inside JSON strings
            _map = {"\n": "\\n", "\r": "\\r", "\t": "\\t", "\x08": "\\b", "\x0c": "\\f"}
            result.append(_map[ch])
        elif in_string and ord(ch) < 0x20:
            result.append(f"\\u{ord(ch):04x}")
        else:
            result.append(ch)
        i += 1
    return "".join(result)


def try_parse_json_object(text: str):
    raw = (text or "").strip()

    # Strip markdown code fences: ```json ... ``` or ``` ... ```
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, flags=re.IGNORECASE)
    if fence_match:
        raw = fence_match.group(1).strip()

    # Attempt 1: direct parse (fast path for well-formed JSON)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Attempt 2: extract the outermost JSON object from any surrounding prose
    start = raw.find("{")
    end = raw.rfind("}")
    candidate = raw[start:end + 1] if (start != -1 and end != -1 and end > start) else None

    if candidate:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

        # Attempt 3: sanitize unescaped control chars in string values and retry
        try:
            return json.loads(_sanitize_json_controls(candidate))
        except json.JSONDecodeError:
            pass

    # Attempt 4: regex extraction — works even with truncated / malformed JSON.
    # Try strict match first (complete answer field with closing quote), then
    # permissive match (no closing quote, for truncated responses).
    for pattern in (
        r'"answer"\s*:\s*"((?:[^\\"]|\\.)*)"',   # complete answer field
        r'"answer"\s*:\s*"((?:[^\\"]|\\.)*)',      # truncated (no closing quote)
    ):
        answer_match = re.search(pattern, raw, re.DOTALL)
        if answer_match:
            extracted = (
                answer_match.group(1)
                .replace("\\n", "\n")
                .replace("\\t", "\t")
                .replace('\\"', '"')
                .replace("\\\\", "\\")
            )
            # Try to also extract confidence from the same raw text
            conf_match = re.search(r'"confidence"\s*:\s*"(high|medium|low)"', raw)
            confidence = conf_match.group(1) if conf_match else "low"
            return {"answer": extracted, "confidence": confidence, "follow_up_questions": []}

    return None


def sanitize_followups(raw_followups, language: str) -> list[str]:
    if not isinstance(raw_followups, list):
        return heuristic_followups(language)

    cleaned: list[str] = []
    seen = set()
    for item in raw_followups:
        text = (item or "").strip()
        if not text:
            continue
        key = normalize_for_compare(text)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
        if len(cleaned) >= 5:
            break

    if len(cleaned) < 3:
        return heuristic_followups(language)
    return cleaned


def heuristic_followups(language: str) -> list[str]:
    if language == "ar":
        return [
            "هل يمكنك توضيح المتطلبات الأساسية بشكل مختصر؟",
            "ما هي الخطوات العملية التي يجب اتباعها حسب المستندات؟",
            "هل توجد مواعيد نهائية أو شروط مهمة مرتبطة بهذا الموضوع؟",
        ]

    return [
        "Can you summarize the key requirements in bullet points?",
        "What are the practical next steps based on the documents?",
        "Are there any deadlines or critical conditions mentioned?",
    ]


def resolve_runtime_config() -> dict:
    requested_mode = os.getenv("ASSISTANT_MODE", "accurate").strip().lower()
    selected_mode = requested_mode if requested_mode in MODE_PROFILES else "balanced"
    profile = MODE_PROFILES[selected_mode]

    retrieval_top_k = read_int_env(
        "RETRIEVAL_TOP_K",
        profile["retrieval_top_k"],
        minimum=1,
        maximum=20,
    )
    gemini_temperature = read_float_env(
        "GEMINI_TEMPERATURE",
        profile["gemini_temperature"],
        minimum=0.0,
        maximum=1.0,
    )
    enable_rerank = read_bool_env("ENABLE_RERANK", profile["enable_rerank"])
    enable_retry = read_bool_env("ENABLE_RETRY", profile["enable_retry"])
    retrieval_overfetch_multiplier = read_int_env(
        "RETRIEVAL_OVERFETCH_MULTIPLIER",
        profile["retrieval_overfetch_multiplier"],
        minimum=1,
        maximum=3,
    )
    context_snippet_limit = read_int_env(
        "CONTEXT_SNIPPET_LIMIT",
        profile["context_snippet_limit"],
        minimum=200,
        maximum=1200,
    )

    return {
        "assistant_mode": selected_mode,
        "retrieval_top_k": retrieval_top_k,
        "gemini_temperature": gemini_temperature,
        "enable_rerank": enable_rerank,
        "enable_retry": enable_retry,
        "retrieval_overfetch_multiplier": retrieval_overfetch_multiplier,
        "context_snippet_limit": context_snippet_limit,
    }


def read_int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    try:
        parsed = int(raw_value)
    except ValueError:
        return default

    return max(minimum, min(maximum, parsed))


def read_float_env(name: str, default: float, minimum: float, maximum: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    try:
        parsed = float(raw_value)
    except ValueError:
        return default

    return max(minimum, min(maximum, parsed))


def read_bool_env(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def generate_with_model_fallback(prompt: str, temperature: float, _max_retries: int = 2):
    discovered_models = _get_cached_models()
    model_candidates = order_model_candidates(discovered_models)
    last_error: Exception | None = None

    for model_name in model_candidates:
        for attempt in range(_max_retries + 1):
            try:
                model = genai.GenerativeModel(model_name)
                generation_config = genai.GenerationConfig(temperature=temperature, max_output_tokens=2500)
                return model.generate_content(prompt, generation_config=generation_config)
            except Exception as exc:
                last_error = exc
                status = getattr(exc, "code", None) or getattr(exc, "status_code", None)
                is_rate_limit = status == 429 or "429" in str(exc) or "quota" in str(exc).lower()
                if is_rate_limit and attempt < _max_retries:
                    wait = 2 ** attempt  # 1s, 2s
                    log.warning("Rate-limited on %s, retry %d in %ds", model_name, attempt + 1, wait)
                    time.sleep(wait)
                    continue
                log.warning("Model %s failed (attempt %d): %s", model_name, attempt + 1, exc)
                break  # Try next model

    if last_error:
        raise last_error
    raise RuntimeError("No Gemini model candidates available.")


def discover_generate_models() -> list[str]:
    try:
        models = genai.list_models()
    except Exception:
        return []

    available: list[str] = []
    for model in models:
        methods = getattr(model, "supported_generation_methods", None) or []
        if "generateContent" in methods and getattr(model, "name", None):
            available.append(model.name)
    return available


# ── Cache for discovered models (avoids network call on every question) ──
_model_cache: dict = {"models": None, "timestamp": 0}
_MODEL_CACHE_TTL = 300  # 5 minutes


def _get_cached_models() -> list[str]:
    """Return discovered models, caching for 5 minutes."""
    now = time.time()
    if _model_cache["models"] is not None and (now - _model_cache["timestamp"]) < _MODEL_CACHE_TTL:
        return _model_cache["models"]
    models = discover_generate_models()
    _model_cache["models"] = models
    _model_cache["timestamp"] = now
    return models


def order_model_candidates(discovered_models: list[str]) -> list[str]:
    ordered: list[str] = []

    # Put preferred models first when they exist in this project.
    discovered_set = set(discovered_models)
    for preferred in PREFERRED_MODELS:
        if preferred in discovered_set and preferred not in ordered:
            ordered.append(preferred)

    # Then add any other discovered models that support generateContent.
    for name in discovered_models:
        if name not in ordered:
            ordered.append(name)

    # Final fallback list for environments where list_models is restricted.
    for fallback in PREFERRED_MODELS:
        if fallback not in ordered:
            ordered.append(fallback)

    return ordered


def generate_with_utility_model(prompt: str) -> str | None:
    """Fast LLM call for lightweight utility tasks such as translation and reranking.

    Uses faster models and fails immediately to the next model on any error —
    no rate-limit back-off retries needed for short utility prompts.
    Returns the stripped response text, or None if all candidates fail.
    """
    for model_name in _UTILITY_MODELS:
        try:
            model = genai.GenerativeModel(model_name)
            cfg = genai.GenerationConfig(temperature=0.0, max_output_tokens=300)
            resp = model.generate_content(prompt, generation_config=cfg)
            text = ((resp.text or "") if resp else "").strip()
            if text:
                return text
        except Exception as exc:
            log.debug("Utility model %s failed: %s", model_name, exc)
    return None


app = create_app()


if __name__ == "__main__":
    app.run(debug=False)