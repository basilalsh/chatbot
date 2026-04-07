"""PDF loading and chunking utilities.

Extraction pipeline (each stage is a fallback for the previous):
  1. PyMuPDF (fitz)  — fastest and most accurate for digital PDFs.
  2. pdfplumber      — handles some edge-cases that fitz misses.
  3. PyPDF2          — legacy fallback.
  4. OCR via pytesseract — for pages that have images but no extractable text
                          (scanned pages).  Requires Tesseract-OCR to be
                          installed as a system binary.  Install the Arabic
                          language pack (ara) for Arabic document support.

If Tesseract is not installed, scanned pages are skipped with a log warning.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path

log = logging.getLogger("charbot")

# ── Optional heavy imports ────────────────────────────────────────

try:
    import fitz  # pymupdf
    _FITZ_AVAILABLE = True
    # Silence MuPDF C-library warnings ("syntax error in content stream", etc.)
    # These are harmless for text extraction but create console noise.
    try:
        fitz.TOOLS.mupdf_display_errors(False)
    except Exception:
        pass
except ImportError:
    _FITZ_AVAILABLE = False
    log.warning("PyMuPDF (fitz) not installed – falling back to PyPDF2/pdfplumber.")

try:
    import pytesseract
    from PIL import Image as _PILImage
    # Allow run.bat (or any launcher) to point pytesseract at the installed binary.
    _tess_cmd = os.environ.get("PYTESSERACT_TESSERACT_CMD")
    if _tess_cmd:
        pytesseract.pytesseract.tesseract_cmd = _tess_cmd
    # Verify the Tesseract binary is actually available (pytesseract is only a wrapper).
    pytesseract.get_tesseract_version()
    _OCR_AVAILABLE = True
    log.info("Tesseract OCR available: %s", pytesseract.get_tesseract_version())
except Exception:
    _OCR_AVAILABLE = False

try:
    import pdfplumber as _pdfplumber
    _PDFPLUMBER_AVAILABLE = True
except ImportError:
    _PDFPLUMBER_AVAILABLE = False

try:
    from PyPDF2 import PdfReader as _PdfReader
    _PYPDF2_AVAILABLE = True
except ImportError:
    _PYPDF2_AVAILABLE = False

ALLOWED_EXTENSIONS = {"pdf"}

# Minimum letter characters for a page to be considered "has text".
# Scanned pages that PyMuPDF wraps around an image sometimes return a handful
# of artefact characters; we ignore them.
_MIN_TEXT_CHARS = 60


# ── Public API ────────────────────────────────────────────────────

def process_pdf_file(file_path: Path, document_name: str) -> list[dict]:
    """Parse a PDF into a list of chunk dicts ready for the vector store."""
    page_items = extract_pages(file_path)
    if not page_items:
        log.warning("No text extracted from '%s'.", file_path.name)
        return []

    output: list[dict] = []
    chunk_index = 0

    for page_number, page_text in page_items:
        page_chunks = split_page_into_chunks(page_text)
        for chunk_text in page_chunks:
            cleaned = normalize_chunk_text(chunk_text)
            if not cleaned:
                continue

            output.append(
                {
                    "chunk_id": f"{document_name}-{chunk_index}",
                    "document_name": document_name,
                    "text": cleaned,
                    "page_start": page_number,
                    "page_end": page_number,
                    "char_count": len(cleaned),
                }
            )
            chunk_index += 1

    log.info(
        "Extracted %d chunks from '%s' (%d pages with text).",
        len(output),
        file_path.name,
        len(page_items),
    )
    return output


# ── Extraction ────────────────────────────────────────────────────

def extract_pages(file_path: Path) -> list[tuple[int, str]]:
    """Return a sorted list of (1-based page_number, text) pairs.

    Tries extraction methods in order of quality, falling back as needed.
    Scanned pages (images with no text layer) are OCR-processed when
    Tesseract is available.
    """
    if _FITZ_AVAILABLE:
        pages = _extract_fitz(file_path)
        if pages:
            return pages

    if _PDFPLUMBER_AVAILABLE:
        pages = _extract_pdfplumber(file_path)
        if pages:
            return pages

    if _PYPDF2_AVAILABLE:
        pages = _extract_pypdf2(file_path)
        if pages:
            return pages

    return []


# ── Per-extractor implementations ────────────────────────────────

import contextlib
import tempfile

@contextlib.contextmanager
def _suppress_mupdf_stderr():
    """Redirect C-level fd 2 to /dev/null as a fallback for older PyMuPDF builds
    that don't honour fitz.TOOLS.mupdf_display_errors(False).
    """
    try:
        devnull_fd = os.open(os.devnull, os.O_WRONLY)
        saved_fd = os.dup(2)
        os.dup2(devnull_fd, 2)
        os.close(devnull_fd)
        try:
            yield
        finally:
            os.dup2(saved_fd, 2)
            os.close(saved_fd)
    except OSError:
        yield


def _extract_fitz(file_path: Path) -> list[tuple[int, str]]:
    """Primary extractor using PyMuPDF.  Handles digital text perfectly and
    can render pages to rasters for OCR on scanned content."""
    pages: list[tuple[int, str]] = []
    scanned_page_indices: list[int] = []

    try:
        with _suppress_mupdf_stderr():
            doc = fitz.open(str(file_path))  # type: ignore[union-attr]
    except Exception as exc:
        log.warning("fitz.open('%s') failed: %s", file_path.name, exc)
        return []

    try:
        with _suppress_mupdf_stderr():
            for page_idx in range(len(doc)):
                page = doc[page_idx]
                page_number = page_idx + 1

                try:
                    text = page.get_text("text").strip()
                except Exception:
                    text = ""

                if _is_meaningful(text):
                    pages.append((page_number, text))
                else:
                    try:
                        if page.get_images(full=False):
                            scanned_page_indices.append(page_idx)
                    except Exception:
                        pass

        # ── OCR pass for scanned pages ────────────────────────────
        if scanned_page_indices:
            if _OCR_AVAILABLE:
                log.info(
                    "'%s': %d page(s) appear scanned – running OCR...",
                    file_path.name,
                    len(scanned_page_indices),
                )
                ocr_success = 0
                for page_idx in scanned_page_indices:
                    page = doc[page_idx]
                    page_number = page_idx + 1
                    with _suppress_mupdf_stderr():
                        ocr_text = _ocr_fitz_page(page)
                    if _is_meaningful(ocr_text):
                        pages.append((page_number, ocr_text))
                        ocr_success += 1
                log.info(
                    "'%s': OCR recovered %d/%d scanned pages.",
                    file_path.name,
                    ocr_success,
                    len(scanned_page_indices),
                )
            else:
                log.warning(
                    "'%s': %d page(s) appear scanned but Tesseract-OCR is not "
                    "installed.  Text from those pages will be missing.  "
                    "Download and install Tesseract from "
                    "https://github.com/UB-Mannheim/tesseract/wiki "
                    "to enable OCR for scanned documents.",
                    file_path.name,
                    len(scanned_page_indices),
                )
    finally:
        doc.close()

    pages.sort(key=lambda x: x[0])
    return pages


def _extract_pdfplumber(file_path: Path) -> list[tuple[int, str]]:
    """Secondary extractor using pdfplumber."""
    pages: list[tuple[int, str]] = []
    try:
        with _pdfplumber.open(str(file_path)) as pdf:  # type: ignore[union-attr]
            for idx, page in enumerate(pdf.pages, start=1):
                try:
                    text = page.extract_text() or ""
                    if _is_meaningful(text):
                        pages.append((idx, text))
                except Exception:
                    continue
    except Exception as exc:
        log.warning("pdfplumber failed on '%s': %s", file_path.name, exc)
    return pages


def _extract_pypdf2(file_path: Path) -> list[tuple[int, str]]:
    """Tertiary extractor using PyPDF2."""
    pages: list[tuple[int, str]] = []
    try:
        reader = _PdfReader(str(file_path))  # type: ignore[union-attr]
        for idx, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text() or ""
                if _is_meaningful(text):
                    pages.append((idx, text))
            except Exception:
                continue
    except Exception as exc:
        log.warning("PyPDF2 failed on '%s': %s", file_path.name, exc)
    return pages


# ── OCR helper ────────────────────────────────────────────────────

def _ocr_fitz_page(page) -> str:
    """Render a fitz page to a high-DPI raster and run Tesseract OCR on it.

    Returns the OCR'd text, or an empty string on failure.
    Supports Arabic + English (ara+eng), with English-only fallback.
    """
    if not _OCR_AVAILABLE or not _FITZ_AVAILABLE:
        return ""
    try:
        # 300 DPI gives Tesseract enough resolution for reliable recognition.
        scale = 300 / 72
        mat = fitz.Matrix(scale, scale)  # type: ignore[union-attr]
        pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB, alpha=False)  # type: ignore[union-attr]
        img = _PILImage.frombytes("RGB", [pix.width, pix.height], pix.samples)

        # Try Arabic + English, fall back to English-only if ara pack missing.
        try:
            text = pytesseract.image_to_string(img, lang="ara+eng", config="--psm 3 --oem 3")
        except Exception:
            text = pytesseract.image_to_string(img, lang="eng", config="--psm 3 --oem 3")
        return text or ""
    except Exception:
        # Silently return empty — caller accumulates stats and logs once.
        return ""


# ── Text quality check ────────────────────────────────────────────

def _is_meaningful(text: str) -> bool:
    """Return True if the text contains enough real letters to be useful."""
    if not text:
        return False
    stripped = text.strip()
    if len(stripped) < _MIN_TEXT_CHARS:
        return False
    # At least 25 % of characters should be Unicode letters (handles Arabic too).
    letter_count = sum(1 for c in stripped if c.isalpha())
    return (letter_count / len(stripped)) >= 0.25



def split_page_into_chunks(text: str, chunk_size: int = 1200, overlap_sentences: int = 2) -> list[str]:
    normalized = re.sub(r"\r\n?", "\n", text)
    normalized = re.sub(r"[ \t]+", " ", normalized)

    paragraphs = [p.strip() for p in normalized.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [line.strip() for line in normalized.split("\n") if line.strip()]

    sentences: list[str] = []
    for paragraph in paragraphs:
        parts = sentence_split(paragraph)
        if parts:
            sentences.extend(parts)

    if not sentences:
        return []

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        if len(sentence) > chunk_size:
            for piece in split_long_sentence(sentence, chunk_size):
                if current:
                    chunks.append(" ".join(current).strip())
                    current = []
                    current_len = 0
                chunks.append(piece)
            continue

        projected = current_len + len(sentence) + (1 if current else 0)
        if projected <= chunk_size:
            current.append(sentence)
            current_len = projected
            continue

        if current:
            chunks.append(" ".join(current).strip())

        if overlap_sentences > 0 and current:
            overlap = current[-overlap_sentences:]
            current = overlap + [sentence]
            current_len = len(" ".join(current))
        else:
            current = [sentence]
            current_len = len(sentence)

    if current:
        chunks.append(" ".join(current).strip())

    return chunks


def sentence_split(text: str) -> list[str]:
    raw_parts = re.split(r"(?<=[.!?؟:؛])\s+", text)
    parts = [p.strip() for p in raw_parts if p.strip()]
    if parts:
        return parts

    # Fallback split for badly formatted OCR text.
    tokens = [t for t in text.split(" ") if t]
    if not tokens:
        return []

    window = 20
    out: list[str] = []
    for i in range(0, len(tokens), window):
        out.append(" ".join(tokens[i:i + window]))
    return out


def split_long_sentence(sentence: str, chunk_size: int) -> list[str]:
    tokens = sentence.split()
    if not tokens:
        return []

    pieces: list[str] = []
    current: list[str] = []
    length = 0

    for token in tokens:
        projected = length + len(token) + (1 if current else 0)
        if projected <= chunk_size:
            current.append(token)
            length = projected
            continue

        if current:
            pieces.append(" ".join(current))
        current = [token]
        length = len(token)

    if current:
        pieces.append(" ".join(current))

    return pieces


def normalize_chunk_text(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "")).strip()
    return cleaned
