"""ingestion/ocr_clean.py

OCR + text-cleaning + image-extraction pipeline for bac-genius exam PDFs.

Pipeline per file
-----------------
1. pdfplumber   — RTL-aware char-level extraction for digital PDFs
2. Quality check — char count, language match, Arabic word-fragmentation detection
3. Gemini Vision — AI OCR for scanned pages and fragmented digital pages
4. PaddleOCR    — local fallback if Gemini unavailable
5. Post-process — NFKC normalisation, RTL cleanup, paragraph spacing
6. Image extract — every embedded image on every page → individual PNG files

Outputs (paths relative to project root)
-----------------------------------------
data/processed/texts/{subject}/{stem}.txt
    Full cleaned text with [PAGE n] markers.

data/processed/images/{subject}/{stem}_page{N}_img{M}.png
    Every embedded image/figure extracted individually.

data/processed/page_images/{subject}/{stem}_p{n:03d}.png
    Full-page renders for complex-layout pages (VLM queue).

data/processed/ocr_manifest.json
    Per-file summary with per-page metadata; all 7 subjects.

data/processed/image_manifest.json
    One entry per extracted image with full provenance metadata.

data/processed/vlm_ocr_queue.json
    Complex-layout pages queued for vision-model re-pass.

Rules
-----
* Never discard a page — keep empty string + failed=True on total failure.
* Resumable: skip if .txt exists and is non-empty (unless --force).
* PaddleOCR models pre-warmed in main thread before worker threads start.
* Thread-safe: one PaddleOCR instance per (thread × language) via threading.local.
* All 7 subjects processed by default.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Suppress PaddlePaddle / PaddleOCR terminal noise before any import.
os.environ.setdefault("GLOG_logtostderr", "0")
os.environ.setdefault("GLOG_v", "0")
os.environ.setdefault("GLOG_minloglevel", "3")
os.environ.setdefault("FLAGS_call_stack_level", "0")
os.environ.setdefault("TQDM_DISABLE", "1")

# Load .env from project root if present
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
if _ENV_PATH.exists():
    for _line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional heavy dependencies
# ---------------------------------------------------------------------------
try:
    import pdfplumber  # type: ignore
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False

try:
    import numpy as np  # type: ignore
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

_paddle_local = threading.local()

# ---------------------------------------------------------------------------
# Gemini Vision OCR client (lazy singleton, thread-safe)
# ---------------------------------------------------------------------------

_gemini_client: Optional[Any] = None
_gemini_lock = threading.Lock()

# Rate limiter: paid Tier 1 allows 150 RPM (Pro) / 2000 RPM (Flash)
# Use 2s interval = 30 RPM — safe headroom on paid tier
_GEMINI_MIN_INTERVAL = 2.0   # seconds between calls (30/min, paid tier)
_gemini_last_call: float = 0.0
_gemini_rate_lock = threading.Lock()


def _get_gemini_client() -> Optional[Any]:
    global _gemini_client
    if _gemini_client is not None:
        return _gemini_client
    with _gemini_lock:
        if _gemini_client is not None:
            return _gemini_client
        api_key = os.environ.get("GOOGLE_API_KEY", "") or os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            logger.warning("No GOOGLE_API_KEY set — Gemini OCR disabled")
            return None
        try:
            from google import genai  # type: ignore
            _gemini_client = genai.Client(api_key=api_key)
            logger.info("Gemini client initialised (google-genai)")
            return _gemini_client
        except Exception as exc:
            logger.warning("Gemini init failed: %s", exc)
            return None


_GEMINI_PROMPT_TEMPLATE = """You are extracting text from an Algerian Baccalaureate (BAC) exam page.

Subject: {subject}
Expected language: {lang_hint}

Instructions:
- Extract only HORIZONTALLY-written text; IGNORE any text printed sideways or rotated (exam forms often have a vertical sidebar on the margin — skip it entirely)
- For Arabic text: each word is written right-to-left; preserve this RTL reading order
- Keep all numbers, mathematical/chemical formulas, and special characters exactly as written
- Separate questions and sections with blank lines
- Preserve numbering: "أولاً:", "ثانياً:", "الجزء الأول:", "Exercice 1:", "Question 1:", etc.
- Output ONLY the extracted text — no commentary, no translations, no added headings
- If the page is blank or truly unreadable, output only: [PAGE UNREADABLE]"""

_LANG_HINTS = {
    "arabe":    "Arabic (right-to-left)",
    "islamic":  "Arabic (right-to-left)",
    "svt":      "Arabic with French scientific terms",
    "physic":   "Arabic with French scientific terms and math formulas",
    "math":     "Arabic with mathematical formulas",
    "francais": "French",
    "english":  "English",
}


_GEMINI_MODELS = [
    "gemini-3.8-flash",   # best available: fast (4s), accurate, paid tier
    "gemini-3.7-flash",   # fallback: also fast (4.6s)
    "gemini-3.5-flash",   # verified working fallback
]


def _ocr_page_gemini(pil_img: Any, subject: str) -> Tuple[str, float]:
    """Use Gemini Vision to OCR a page image. Returns (text, confidence)."""
    import io as _io
    import time as _time
    import re as _re
    global _gemini_last_call

    client = _get_gemini_client()
    if client is None:
        return "", 0.0
    try:
        buf = _io.BytesIO()
        pil_img.save(buf, format="PNG")
        img_bytes = buf.getvalue()

        from google.genai import types as _gtypes  # type: ignore
        prompt = _GEMINI_PROMPT_TEMPLATE.format(
            subject=subject,
            lang_hint=_LANG_HINTS.get(subject, "Arabic or French"),
        )
        contents = [
            _gtypes.Part.from_bytes(data=img_bytes, mime_type="image/png"),
            prompt,
        ]

        last_exc: Optional[Exception] = None
        for model in _GEMINI_MODELS:
            for attempt in range(4):
                # Global rate limiting: enforce minimum interval between calls
                with _gemini_rate_lock:
                    now = _time.time()
                    wait = _GEMINI_MIN_INTERVAL - (now - _gemini_last_call)
                    if wait > 0:
                        _time.sleep(wait)
                    _gemini_last_call = _time.time()

                try:
                    response = client.models.generate_content(
                        model=model, contents=contents
                    )
                    text = (response.text or "").strip()
                    if text and text != "[PAGE UNREADABLE]":
                        return text, 0.92
                    return "", 0.0

                except Exception as exc:
                    last_exc = exc
                    err = str(exc)

                    if "429" in err or "RESOURCE_EXHAUSTED" in err:
                        # Parse "retry in Xs" from error message
                        m = _re.search(r"retry[^\d]*(\d+(?:\.\d+)?)\s*s", err, _re.I)
                        sleep_s = float(m.group(1)) if m else 60.0
                        logger.info("Gemini 429 (%s) — sleeping %.0fs", model, sleep_s)
                        _time.sleep(sleep_s + 2)
                        continue  # retry same model after waiting

                    if "503" in err or "UNAVAILABLE" in err:
                        _time.sleep(min(4.0 * (attempt + 1), 30.0))
                        continue

                    break  # non-retriable — try next model

        logger.warning("Gemini OCR failed (all models): %s", last_exc)
        return "", 0.0
    except Exception as exc:
        logger.warning("Gemini OCR setup failed: %s", exc)
        return "", 0.0

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PADDLE_LANG: Dict[str, str] = {
    "svt":      "arabic",
    "physic":   "arabic",
    "math":     "arabic",
    "arabe":    "arabic",
    "islamic":  "arabic",
    "francais": "fr",
    "english":  "en",
}

ARABIC_SUBJECTS = frozenset({"svt", "physic", "math", "arabe", "islamic"})
SCIENCE_SUBJECTS = frozenset({"svt", "physic", "math"})

MIN_CHARS_GOOD = 50
RENDER_DPI = 200

# If an extracted image covers > this fraction of the page area it is a
# full-page scan, not a figure — we save it but flag it differently.
PAGE_SCAN_AREA_RATIO = 0.80

# ---------------------------------------------------------------------------
# Arabic / text normalisation
# ---------------------------------------------------------------------------

_ZW_RE = re.compile(r"[​-‏‪- ⁠-⁤﻿]")
_TATWEEL = "ـ"
_MULTI_NL = re.compile(r"\n{3,}")
_MULTI_SP = re.compile(r"[ \t]{2,}")
_DIGIT_RUN = re.compile(r"\d+")  # digit runs reversed by RTL sort — restore


def _is_arabic_char(c: str) -> bool:
    """True for any character in an Arabic Unicode block."""
    cp = ord(c)
    return (0x0600 <= cp <= 0x06FF or   # Arabic
            0x0750 <= cp <= 0x077F or   # Arabic Supplement
            0x08A0 <= cp <= 0x08FF or   # Arabic Extended-A
            0xFB50 <= cp <= 0xFDFF or   # Arabic Presentation Forms-A
            0xFE70 <= cp <= 0xFEFF)     # Arabic Presentation Forms-B


def _extract_page_text_rtl(page: Any) -> str:
    """RTL-aware text extraction from a pdfplumber page.

    Re-sorts characters right-to-left within Arabic-dominant lines so that
    words appear in correct logical reading order.  Digit runs reversed by the
    RTL sort are restored to LTR order afterwards.
    """
    try:
        chars = page.chars
    except Exception:
        chars = []

    if not chars:
        return page.extract_text() or ""

    from collections import defaultdict as _dd
    lines: Dict[int, List[Any]] = _dd(list)
    for c in chars:
        bucket = round(float(c["top"]) / 3) * 3
        lines[bucket].append(c)

    result_lines: List[str] = []
    for y in sorted(lines):
        lc = lines[y]
        raw = "".join(c["text"] for c in lc)
        ar_ratio = sum(1 for ch in raw if _is_arabic_char(ch)) / max(len(raw.strip()), 1)
        if ar_ratio > 0.30:
            sorted_chars = sorted(lc, key=lambda c: float(c["x0"]), reverse=True)
            line = unicodedata.normalize("NFKC", "".join(c["text"] for c in sorted_chars)).strip()
            line = _DIGIT_RUN.sub(lambda m: m.group()[::-1], line)
        else:
            sorted_chars = sorted(lc, key=lambda c: float(c["x0"]))
            line = "".join(c["text"] for c in sorted_chars).strip()
        if line:
            result_lines.append(line)

    return "\n".join(result_lines)


def _normalize_text(text: str) -> str:
    if not text:
        return ""
    text = _ZW_RE.sub("", text)
    text = text.replace(_TATWEEL, "")
    # NFKC converts Arabic Presentation Forms (U+FE70–FEFF) to standard Unicode
    text = unicodedata.normalize("NFKC", text)
    text = _MULTI_SP.sub(" ", text)
    text = _MULTI_NL.sub("\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

def _detect_lang(text: str) -> str:
    if not text.strip():
        return "unknown"
    ar  = sum(1 for c in text if _is_arabic_char(c))
    lat = sum(1 for c in text if c.isascii() and c.isalpha())
    total = ar + lat
    if total == 0:
        return "unknown"
    ratio = ar / total
    if ratio > 0.60:
        return "arabic"
    if ratio < 0.20:
        return "latin"
    return "mixed"


# ---------------------------------------------------------------------------
# Page quality assessment
# ---------------------------------------------------------------------------

_AR_WORD_RE = re.compile(r"\S+")


def _avg_arabic_word_len(text: str) -> float:
    """Average length of Arabic-dominant tokens; 0 if none found."""
    words = [
        w for w in _AR_WORD_RE.findall(text)
        if sum(_is_arabic_char(c) for c in w) / max(len(w), 1) > 0.5
    ]
    if not words:
        return 0.0
    return sum(len(w) for w in words) / len(words)


def _assess_page(text: str, page_images: List[Any], subject: str) -> Dict[str, Any]:
    char_count = len(text.strip())
    has_images = len(page_images) > 0
    lang = _detect_lang(text)

    # Complex layout: any subject with embedded images worth preserving.
    complex_layout = has_images

    low_quality = char_count < MIN_CHARS_GOOD
    if not low_quality and char_count > 100:
        expects_arabic = subject in ARABIC_SUBJECTS
        if expects_arabic and lang == "latin":
            low_quality = True
        if not expects_arabic and lang == "arabic":
            low_quality = True
        # Fragmentation check: pdfplumber extracted chars individually (avg word < 3 chars)
        if not low_quality and lang in ("arabic", "mixed") and expects_arabic:
            if _avg_arabic_word_len(text) < 3.0:
                low_quality = True

    return {
        "char_count": char_count,
        "has_images": has_images,
        "image_count": len(page_images),
        "complex_layout": complex_layout,
        "language_guess": lang,
        "low_quality": low_quality,
    }


# ---------------------------------------------------------------------------
# Page rendering (for OCR fallback and VLM queue)
# ---------------------------------------------------------------------------

def _render_page(page: Any) -> Optional[Any]:
    """Render page to PIL Image; None if unavailable."""
    try:
        return page.to_image(resolution=RENDER_DPI).original
    except Exception as exc:
        logger.debug("Page render failed: %s", exc)
        return None


def _save_png(pil_img: Any, out_path: Path) -> bool:
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        pil_img.save(str(out_path), format="PNG", optimize=False)
        return True
    except Exception as exc:
        logger.warning("PNG save failed %s: %s", out_path, exc)
        return False


# ---------------------------------------------------------------------------
# Embedded image extraction
# ---------------------------------------------------------------------------

def _extract_page_images(
    page: Any,
    pil_page: Optional[Any],
    page_num: int,
    stem: str,
    imgs_out_dir: Path,
    root: Path,
    record: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Extract every embedded image on *page* as a separate PNG.

    Returns a list of image metadata dicts (one per extracted image).
    Skips images that cannot be cropped; never raises.
    """
    page_imgs = page.images or []
    if not page_imgs:
        return []

    # We need the rendered page to crop from.
    if pil_page is None:
        pil_page = _render_page(page)
    if pil_page is None:
        return []

    page_w_pt = float(page.width)
    page_h_pt = float(page.height)
    page_area_pt = page_w_pt * page_h_pt

    scale_x = pil_page.width  / page_w_pt
    scale_y = pil_page.height / page_h_pt

    results: List[Dict[str, Any]] = []
    for img_idx, img_obj in enumerate(page_imgs, start=1):
        try:
            # pdfplumber coords: bottom-left origin
            x0 = float(img_obj.get("x0", 0))
            y0 = float(img_obj.get("y0", 0))
            x1 = float(img_obj.get("x1", page_w_pt))
            y1 = float(img_obj.get("y1", page_h_pt))

            if x1 <= x0 or y1 <= y0:
                continue

            img_area = (x1 - x0) * (y1 - y0)
            is_page_scan = (img_area / page_area_pt) >= PAGE_SCAN_AREA_RATIO

            # Convert to PIL pixels (top-left origin)
            left   = max(0, int(x0 * scale_x))
            top    = max(0, int((page_h_pt - y1) * scale_y))
            right  = min(pil_page.width,  int(x1 * scale_x))
            bottom = min(pil_page.height, int((page_h_pt - y0) * scale_y))

            if right <= left or bottom <= top:
                continue

            cropped = pil_page.crop((left, top, right, bottom))

            img_out_dir = imgs_out_dir / record.get("subject", "unknown")
            fname = f"{stem}_page{page_num}_img{img_idx}.png"
            img_path = img_out_dir / fname

            saved = _save_png(cropped, img_path)
            results.append({
                "source_pdf":   record["path"],
                "page_num":     page_num,
                "img_index":    img_idx,
                "image_path":   img_path.relative_to(root).as_posix() if saved else None,
                "subject":      record.get("subject"),
                "year":         record.get("year"),
                "topic_choice": record.get("topic_choice"),
                "type":         record.get("type"),
                "exam_regime":  record.get("exam_regime"),
                "session_type": record.get("session_type"),
                "width":        cropped.width,
                "height":       cropped.height,
                "is_page_scan": is_page_scan,
            })
        except Exception as exc:
            logger.warning("Image extract failed (page %d img %d %s): %s",
                           page_num, img_idx, stem, exc)

    return results


# ---------------------------------------------------------------------------
# PaddleOCR — thread-local lazy initialisation
# ---------------------------------------------------------------------------

def _get_paddle(lang: str) -> Optional[Any]:
    attr = f"ocr_{lang}"
    if not hasattr(_paddle_local, attr):
        try:
            from paddleocr import PaddleOCR  # type: ignore
            setattr(_paddle_local, attr,
                    PaddleOCR(lang=lang, use_angle_cls=True,
                              show_log=False, use_gpu=False))
        except Exception as exc:
            logger.warning("PaddleOCR init failed (lang=%s): %s", lang, exc)
            setattr(_paddle_local, attr, None)
    return getattr(_paddle_local, attr)


def _ocr_page_paddle(pil_img: Any, lang: str) -> Tuple[str, float]:
    ocr = _get_paddle(lang)
    if ocr is None or not HAS_NUMPY:
        return "", 0.0
    try:
        img_arr = np.array(pil_img)
        result  = ocr.ocr(img_arr, cls=True)
        lines   = result[0] if result and result[0] else []
        if not lines:
            return "", 0.0
        texts = [ln[1][0] for ln in lines]
        confs = [float(ln[1][1]) for ln in lines]
        return "\n".join(texts), sum(confs) / len(confs)
    except Exception as exc:
        logger.warning("PaddleOCR inference failed: %s", exc)
        return "", 0.0


def _ocr_page(pil_img: Any, lang: str, subject: str = "") -> Tuple[str, float]:
    """OCR a page image: Gemini Vision first, PaddleOCR as fallback."""
    # Primary: Gemini Vision (accurate, handles Arabic/French/English natively)
    text, conf = _ocr_page_gemini(pil_img, subject or lang)
    if text.strip():
        return text, conf
    # Fallback: PaddleOCR (may be unavailable on some platforms)
    return _ocr_page_paddle(pil_img, lang)


# ---------------------------------------------------------------------------
# Single-file processing
# ---------------------------------------------------------------------------

def process_file(
    record: Dict[str, Any],
    root: Path,
    texts_dir: Path,
    imgs_dir: Path,
    page_imgs_dir: Path,
    force: bool = False,
) -> Dict[str, Any]:
    """Process one manifest record: OCR + image extraction.

    Returns a result dict for ocr_manifest.json.  Never raises.
    """
    subject: str = record["subject"]
    rel_pdf: str = record["path"]
    pdf_path = root / rel_pdf
    stem     = pdf_path.stem

    txt_dir  = texts_dir / subject
    txt_dir.mkdir(parents=True, exist_ok=True)
    txt_path = txt_dir / f"{stem}.txt"

    # ── Resumable ────────────────────────────────────────────────────────
    if txt_path.exists() and txt_path.stat().st_size > 0 and not force:
        return _skipped_result(record, root, txt_path)

    if not HAS_PDFPLUMBER:
        return _failed_result(record, root, txt_path, "pdfplumber not installed")

    paddle_lang  = PADDLE_LANG.get(subject, "arabic")
    page_results: List[Dict[str, Any]] = []
    vlm_pages:   List[Dict[str, Any]] = []
    image_metas: List[Dict[str, Any]] = []
    page_texts:  List[str] = []

    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):

                # 1. Text extraction
                try:
                    raw_text:   str       = _extract_page_text_rtl(page)
                    page_imgs:  List[Any] = page.images or []
                except Exception as exc:
                    logger.warning("%s p%d extract error: %s", stem, page_num, exc)
                    raw_text  = ""
                    page_imgs = []

                # 2. Quality check
                assessment = _assess_page(raw_text, page_imgs, subject)

                method     = "pdfplumber"
                text       = raw_text
                confidence = 1.0
                failed     = False
                pil_page: Optional[Any] = None   # lazy: render at most once per page

                # 3. Complex-layout: render full page for VLM queue
                if assessment["complex_layout"]:
                    pil_page = _render_page(page)
                    if pil_page is not None:
                        pi_path = (page_imgs_dir / subject
                                   / f"{stem}_p{page_num:03d}.png")
                        saved = _save_png(pil_page, pi_path)
                        vlm_pages.append({
                            "source_pdf": rel_pdf,
                            "page_num":   page_num,
                            "image_path": pi_path.relative_to(root).as_posix() if saved else None,
                            "subject":    subject,
                            "year":       record.get("year"),
                            "reason":     "complex_layout",
                        })
                    else:
                        vlm_pages.append({
                            "source_pdf": rel_pdf,
                            "page_num":   page_num,
                            "image_path": None,
                            "subject":    subject,
                            "year":       record.get("year"),
                            "reason":     "complex_layout_no_render",
                        })

                # 4. AI+OCR fallback for low-quality pages (Gemini Vision → PaddleOCR)
                if assessment["low_quality"]:
                    if pil_page is None:
                        pil_page = _render_page(page)
                    if pil_page is not None:
                        ocr_text, ocr_conf = _ocr_page(pil_page, paddle_lang, subject)
                        if ocr_text.strip():
                            text       = ocr_text
                            confidence = ocr_conf
                            method     = "gemini" if ocr_conf >= 0.90 else "paddleocr"
                            assessment["char_count"]    = len(text.strip())
                            assessment["language_guess"] = _detect_lang(text)
                        else:
                            failed     = True
                            method     = "failed"
                            confidence = 0.0
                    else:
                        if not text.strip():
                            failed     = True
                            method     = "failed"
                            confidence = 0.0

                # 5. Extract embedded images (all subjects, every page with images)
                if page_imgs:
                    metas = _extract_page_images(
                        page, pil_page, page_num, stem,
                        imgs_dir, root, record,
                    )
                    image_metas.extend(metas)

                # 6. Normalise text
                text = _normalize_text(text)

                page_results.append({
                    "page_num":      page_num,
                    "method":        method,
                    "char_count":    len(text),
                    "confidence":    round(confidence, 4),
                    "complex_layout": assessment["complex_layout"],
                    "image_count":   assessment["image_count"],
                    "language_guess": assessment["language_guess"],
                    "failed":        failed,
                })
                page_texts.append(f"[PAGE {page_num}]\n{text}")

    except Exception as exc:
        logger.error("Fatal error processing %s: %s", pdf_path, exc)
        return _failed_result(record, root, txt_path, str(exc))

    # ── Write text output ────────────────────────────────────────────────
    try:
        txt_path.write_text("\n\n".join(page_texts), encoding="utf-8")
    except OSError as exc:
        logger.error("Cannot write %s: %s", txt_path, exc)

    # ── Quality score ────────────────────────────────────────────────────
    good = [p for p in page_results if not p["failed"]]
    if good:
        avg_conf   = sum(p["confidence"] for p in good) / len(good)
        char_score = min(1.0, sum(p["char_count"] for p in good) / (len(good) * 500))
        quality_score = round(0.6 * avg_conf + 0.4 * char_score, 4)
    else:
        quality_score = 0.0

    breakdown: Dict[str, int] = {}
    for p in page_results:
        breakdown[p["method"]] = breakdown.get(p["method"], 0) + 1

    return {
        # ── file-level provenance ─────────────────────────────────────
        "source_pdf":    rel_pdf,
        "txt_path":      txt_path.relative_to(root).as_posix(),
        "subject":       subject,
        "year":          record.get("year"),
        "topic_choice":  record.get("topic_choice"),
        "type":          record.get("type"),
        "exam_regime":   record.get("exam_regime"),
        "censored":      record.get("censored"),
        "sealed":        record.get("sealed"),
        "session":       record.get("session"),
        "session_type":  record.get("session_type"),
        # ── processing results ────────────────────────────────────────
        "skipped":          False,
        "quality_score":    quality_score,
        "method_breakdown": breakdown,
        "pages":            page_results,
        # ── image extraction summary ──────────────────────────────────
        "extracted_images": len(image_metas),
        # internal — stripped before writing ocr_manifest
        "_vlm_pages":    vlm_pages,
        "_image_metas":  image_metas,
    }


def _skipped_result(record: Dict[str, Any], root: Path, txt_path: Path) -> Dict[str, Any]:
    return {
        "source_pdf":    record["path"],
        "txt_path":      txt_path.relative_to(root).as_posix(),
        "subject":       record.get("subject"),
        "year":          record.get("year"),
        "topic_choice":  record.get("topic_choice"),
        "type":          record.get("type"),
        "exam_regime":   record.get("exam_regime"),
        "censored":      record.get("censored"),
        "sealed":        record.get("sealed"),
        "session":       record.get("session"),
        "session_type":  record.get("session_type"),
        "skipped":          True,
        "quality_score":    None,
        "method_breakdown": {},
        "pages":            [],
        "extracted_images": None,
        "_vlm_pages":    [],
        "_image_metas":  [],
    }


def _failed_result(
    record: Dict[str, Any],
    root: Path,
    txt_path: Path,
    reason: str,
) -> Dict[str, Any]:
    try:
        txt_path.parent.mkdir(parents=True, exist_ok=True)
        txt_path.write_text("", encoding="utf-8")
    except OSError:
        pass
    return {
        "source_pdf":    record.get("path", ""),
        "txt_path":      txt_path.relative_to(root).as_posix(),
        "subject":       record.get("subject"),
        "year":          record.get("year"),
        "topic_choice":  record.get("topic_choice"),
        "type":          record.get("type"),
        "exam_regime":   record.get("exam_regime"),
        "censored":      record.get("censored"),
        "sealed":        record.get("sealed"),
        "session":       record.get("session"),
        "session_type":  record.get("session_type"),
        "skipped":          False,
        "quality_score":    0.0,
        "method_breakdown": {"failed": 1},
        "pages": [{
            "page_num": 1, "method": "failed", "char_count": 0,
            "confidence": 0.0, "complex_layout": False, "image_count": 0,
            "language_guess": "unknown", "failed": True, "reason": reason,
        }],
        "extracted_images": 0,
        "_vlm_pages":    [],
        "_image_metas":  [],
    }


# ---------------------------------------------------------------------------
# Manifest writers
# ---------------------------------------------------------------------------

def _write_manifests(
    processed_dir: Path,
    all_results: List[Dict[str, Any]],
    vlm_queue: List[Dict[str, Any]],
    image_queue: List[Dict[str, Any]],
) -> None:
    """Write / merge all four output manifests. Best-effort — never raises."""

    # ── ocr_manifest.json ────────────────────────────────────────────────
    try:
        strip_keys = {"_vlm_pages", "_image_metas"}
        new_entries = [{k: v for k, v in r.items() if k not in strip_keys}
                       for r in all_results]
        ocr_path = processed_dir / "ocr_manifest.json"
        if ocr_path.exists():
            try:
                prior      = json.loads(ocr_path.read_text(encoding="utf-8"))
                # Skipped files: keep the prior manifest entry unchanged (preserves quality_score).
                # Only update entries for files that were actually processed this run.
                processed_entries = [e for e in new_entries if not e.get("skipped")]
                new_pdfs          = {e["source_pdf"] for e in processed_entries}
                merged            = [e for e in prior if e["source_pdf"] not in new_pdfs] + processed_entries
            except Exception:
                merged = new_entries
        else:
            merged = new_entries
        ocr_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.error("Failed writing ocr_manifest.json: %s", exc)

    # ── image_manifest.json ──────────────────────────────────────────────
    try:
        img_path = processed_dir / "image_manifest.json"
        if img_path.exists() and image_queue:
            try:
                prior_imgs = json.loads(img_path.read_text(encoding="utf-8"))
                new_keys   = {(e["source_pdf"], e["page_num"], e["img_index"])
                              for e in image_queue}
                kept_imgs  = [e for e in prior_imgs
                              if (e["source_pdf"], e["page_num"], e["img_index"]) not in new_keys]
                image_queue = kept_imgs + image_queue
            except Exception:
                pass
        img_path.write_text(json.dumps(image_queue, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.error("Failed writing image_manifest.json: %s", exc)

    # ── vlm_ocr_queue.json ───────────────────────────────────────────────
    try:
        vlm_path = processed_dir / "vlm_ocr_queue.json"
        if vlm_path.exists() and vlm_queue:
            try:
                prior_vlm = json.loads(vlm_path.read_text(encoding="utf-8"))
                new_keys  = {(e["source_pdf"], e["page_num"]) for e in vlm_queue}
                kept_vlm  = [e for e in prior_vlm
                             if (e["source_pdf"], e["page_num"]) not in new_keys]
                vlm_queue = kept_vlm + vlm_queue
            except Exception:
                pass
        vlm_path.write_text(json.dumps(vlm_queue, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.error("Failed writing vlm_ocr_queue.json: %s", exc)


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run_ocr(
    project_root: Path,
    workers: int = 4,
    force: bool = False,
    retry_failed: bool = False,
    subjects: Optional[List[str]] = None,
) -> None:
    """Run the full OCR + image-extraction pipeline across all 7 subjects.

    Parameters
    ----------
    project_root : Path
        Absolute path to the bac-genius project root.
    workers : int
        ThreadPoolExecutor max_workers.
    force : bool
        Re-process even if .txt output already exists.
    retry_failed : bool
        Re-process only files marked quality_score=0 in ocr_manifest.json.
    subjects : list of str, optional
        Limit processing to these subject codes (e.g. ["arabe", "math"]).
        If None, all 7 subjects are processed.
    """
    try:
        from rich.console import Console
        from rich.progress import (
            Progress, SpinnerColumn, TextColumn,
            BarColumn, MofNCompleteColumn, TimeElapsedColumn,
        )
        console  = Console()
        USE_RICH = True
    except ImportError:
        USE_RICH = False
        console  = None  # type: ignore

    # ── Load raw manifest ─────────────────────────────────────────────────
    manifest_path = project_root / "data" / "raw" / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"Manifest not found: {manifest_path}\n"
            "Run  python -m scripts.run_manifest  first."
        )
    all_records: List[Dict[str, Any]] = json.loads(
        manifest_path.read_text(encoding="utf-8")
    )

    # ── Filter: all 7 subjects, family A + B, skip duplicates ────────────
    from config.streams import SUBJECTS_BY_CODE

    subject_filter = set(subjects) if subjects else None

    def _in_scope(r: Dict[str, Any]) -> bool:
        if r.get("duplicate"):
            return False
        if r.get("family") not in ("A", "B"):
            return False
        if SUBJECTS_BY_CODE.get(r.get("subject", "")) is None:
            return False
        if subject_filter and r.get("subject") not in subject_filter:
            return False
        return True

    records = [r for r in all_records if _in_scope(r)]

    # ── Retry-failed filter ───────────────────────────────────────────────
    effective_force = force or retry_failed
    if retry_failed and not force:
        ocr_mf = project_root / "data" / "processed" / "ocr_manifest.json"
        if ocr_mf.exists():
            prior = json.loads(ocr_mf.read_text(encoding="utf-8"))
            failed_paths = {
                r["source_pdf"]
                for r in prior
                if (r.get("quality_score") or 0) == 0 and not r.get("skipped")
            }
            records = [r for r in records if r["path"] in failed_paths]

    # ── Output directories ────────────────────────────────────────────────
    processed     = project_root / "data" / "processed"
    texts_dir     = processed / "texts"
    imgs_dir      = processed / "images"
    page_imgs_dir = processed / "page_images"
    for d in (texts_dir, imgs_dir, page_imgs_dir):
        d.mkdir(parents=True, exist_ok=True)

    # ── Scope summary ─────────────────────────────────────────────────────
    from collections import Counter
    by_subj = Counter(r["subject"] for r in records)
    scope_line = "  +  ".join(f"{s}({n})" for s, n in sorted(by_subj.items()))
    header = (
        f"\nOCR pipeline — {len(records)} files across 7 subjects:\n"
        f"  {scope_line}\n"
        f"Workers: {workers}  |  Force: {force}  |  RetryFailed: {retry_failed}\n"
    )
    if USE_RICH and console:
        console.print(header)
    else:
        print(header)

    # ── Initialise Gemini OCR client ──────────────────────────────────────
    gemini_ok = _get_gemini_client() is not None
    msg = "Gemini Vision OCR ready" if gemini_ok else "Gemini unavailable (no GOOGLE_API_KEY) — PaddleOCR fallback only"
    if USE_RICH and console:
        colour = "green" if gemini_ok else "yellow"
        console.print(f"  [{colour}]{msg}[/{colour}]")
    else:
        print(f"  {msg}")

    # ── Parallel processing ───────────────────────────────────────────────
    all_results:  List[Dict[str, Any]] = []
    vlm_queue:    List[Dict[str, Any]] = []
    image_queue:  List[Dict[str, Any]] = []
    _lock = threading.Lock()

    def _task(rec: Dict[str, Any]) -> Dict[str, Any]:
        result = process_file(
            rec, project_root, texts_dir, imgs_dir, page_imgs_dir,
            force=effective_force,
        )
        with _lock:
            vlm_queue.extend(result.get("_vlm_pages", []))
            image_queue.extend(result.get("_image_metas", []))
        return result

    def _collect(future: Any, rec: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return future.result()
        except Exception as exc:
            logger.error("Unhandled exception for %s: %s", rec.get("path"), exc)
            txt_dir  = texts_dir / rec.get("subject", "unknown")
            txt_dir.mkdir(parents=True, exist_ok=True)
            txt_path = txt_dir / f"{Path(rec.get('path', 'unknown')).stem}.txt"
            return _failed_result(rec, project_root, txt_path, f"unhandled: {exc}")

    try:
        if USE_RICH and console:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                TimeElapsedColumn(),
                console=console,
            ) as progress:
                task_id = progress.add_task("Processing PDFs…", total=len(records))
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = {pool.submit(_task, rec): rec for rec in records}
                    for future in as_completed(futures):
                        rec    = futures[future]
                        result = _collect(future, rec)
                        all_results.append(result)
                        label  = (
                            "[dim]skip[/dim]" if result.get("skipped")
                            else f"[green]ok[/green] q={result.get('quality_score') or 0:.2f}"
                        )
                        progress.update(
                            task_id, advance=1,
                            description=(
                                f"{rec['subject']} {rec.get('year','')} "
                                f"{rec.get('type','')[:3]} {label}"
                            ),
                        )
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(_task, rec): rec for rec in records}
                done = 0
                for future in as_completed(futures):
                    rec    = futures[future]
                    result = _collect(future, rec)
                    all_results.append(result)
                    done  += 1
                    print(f"  [{done}/{len(records)}] {result['source_pdf']}  "
                          f"q={result.get('quality_score') or 0:.2f}")
    finally:
        _write_manifests(processed, all_results, vlm_queue, image_queue)

    # ── Summary ───────────────────────────────────────────────────────────
    skipped_n  = sum(1 for r in all_results if r.get("skipped"))
    failed_n   = sum(1 for r in all_results
                     if not r.get("skipped") and (r.get("quality_score") or 0) == 0)
    paddle_n   = sum(r.get("method_breakdown", {}).get("paddleocr", 0) for r in all_results)
    images_n   = sum(r.get("extracted_images") or 0 for r in all_results)
    vlm_n      = len(vlm_queue)

    summary = (
        f"\n=== OCR + Image Extraction Summary ===\n"
        f"  Files processed : {len(all_results) - skipped_n}\n"
        f"  Files skipped   : {skipped_n}  (already done)\n"
        f"  Failed (q=0)    : {failed_n}\n"
        f"  PaddleOCR pages : {paddle_n}  (fallback)\n"
        f"  Images extracted: {images_n}\n"
        f"  VLM queue       : {vlm_n}  (complex pages)\n"
        f"\n  → ocr_manifest.json\n"
        f"  → image_manifest.json  ({len(image_queue)} entries)\n"
        f"  → vlm_ocr_queue.json   ({vlm_n} entries)\n"
    )
    if USE_RICH and console:
        console.print(summary)
    else:
        print(summary)
