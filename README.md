# Dhofar Insurance AI Assistant

An internal RAG (Retrieval-Augmented Generation) chatbot that answers questions from preloaded company PDF documents. Supports English and Arabic.

## Stack

- **Backend:** Python 3.10+ · Flask 3 · Google Gemini API (2.5-flash / 2.5-pro)
- **Frontend:** React 19 · Vite · TypeScript · Tailwind CSS v4 · Framer Motion
- **Retrieval:** Hybrid BM25 + semantic similarity · re-ranking · 4 094 chunks
- **PDF extraction:** `pdfplumber` with `PyPDF2` fallback

## Project Structure

```text
app.py                  Flask application (serves React build)
run.bat                 One-click launcher for end users
requirements.txt        Python dependencies
.env                    API key (not committed to source control)
.env.example            Template for .env
build_embeddings.py     Pre-compute semantic embeddings (run once)
utils/
  embedder.py           Embedding helpers
  pdf_loader.py         PDF extraction
  retriever.py          Hybrid retrieval + re-ranking
data/
  chunks.json           Pre-processed PDF chunks
  embeddings_cache.json Pre-computed embeddings
static/
  dist/                 Pre-built React frontend (served by Flask)
  dhofar-logo.png
frontend/               React source (only needed to rebuild UI)
```

---

## End-User Deployment

### Requirements
- **Python 3.10+** — download from https://www.python.org/downloads/  
  ✅ Check **"Add Python to PATH"** during installation

### What to give the user
Share the project folder as a zip, **excluding** these directories (they are recreated automatically):
```
.venv/
__pycache__/
build/
frontend/node_modules/
```
The `static/dist/` folder (pre-built React app) **must be included** — no Node.js needed on the user's machine.

### How to run
1. Unzip the folder anywhere on the machine
2. Make sure `.env` contains the Gemini API key (see `.env.example`)
3. Double-click **`run.bat`**

`run.bat` will automatically:
- Create a Python virtual environment
- Install all Python dependencies
- Launch the Flask server
- Open the browser at `http://127.0.0.1:5000`

---

## Developer Setup

### First run
```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
cp .env.example .env   # add your GEMINI_API_KEY
python app.py
```

### Rebuild the React frontend
Requires Node.js 18+.
```bash
cd frontend
npm install --legacy-peer-deps
npx vite build        # outputs to ../static/dist/
```

### Regenerate embeddings (after changing PDFs)
```bash
python build_embeddings.py
```

---

## Assistant Mode

Default mode is `accurate` — optimised for correctness over speed.

| Mode | top_k | Rerank | Temperature |
|------|-------|--------|-------------|
| accurate | 8 | ✅ | 0.15 |
| balanced | 6 | ✅ | 0.20 |
| fast | 4 | ❌ | 0.10 |

Override in `.env`:
```env
ASSISTANT_MODE=accurate
```

Optional fine-tuning overrides:
- `RETRIEVAL_TOP_K` (1–20)
- `GEMINI_TEMPERATURE` (0.0–1.0)
- `ENABLE_RERANK` (`true`/`false`)
- `CONTEXT_SNIPPET_LIMIT` (200–1200)

---

## How It Works

1. On startup, the app loads pre-processed chunks from `data/chunks.json` and embeddings from `data/embeddings_cache.json`.
2. For each question, it retrieves the most relevant chunks using a hybrid BM25 + semantic similarity search, then optionally re-ranks them.
3. The question and retrieved context are sent to the Gemini API.
4. The answer streams back token-by-token to the browser via Server-Sent Events.

If no relevant content is found, the app responds:  
`I could not find a clear answer in the uploaded documents.`

## Single EXE for End Users (No Browser, No Python Install)

This project supports a professional desktop package:

Flask backend + HTML/CSS/JS + PyWebView window + PyInstaller build = one EXE.

### Build steps (Windows)

1. Ensure `.venv` exists and dependencies are installed:

   ```powershell
   .venv\Scripts\python.exe -m pip install -r requirements.txt
   .venv\Scripts\python.exe -m pip install -r requirements-build.txt
   ```

2. Build executable:

   ```powershell
   .\build_exe.ps1
   ```

3. Output:

   - `dist\DhofarAIAssistant.exe` (single-file mode)

### End-user experience

- User double-clicks `DhofarAIAssistant.exe`
- Embedded backend starts internally
- Desktop window opens directly
- No terminal, no manual server run, no browser needed

## Important Security Note

- Never put your Gemini API key in frontend files.
- Keep `GEMINI_API_KEY` only in `.env`.
- All Gemini API calls in this project are made from Flask backend routes.
- If you ship a single EXE with `.env` bundled, the key is recoverable by advanced users; for strict security use a managed backend.