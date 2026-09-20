"""scripts/verify_and_correct.py

Autonomous verification + correction pipeline for all 580 BAC exam PDFs.

For each extracted .txt file:
1. Page-count check: PDF pages == [PAGE n] markers in .txt
2. Per-page automated quality checks:
   - Language correctness (Arabic expected → Arabic found, etc.)
   - Character count (not suspiciously short)
   - No garbled Arabic (avg token len ≤ 4 on Arabic-dominant pages → suspect)
   - No reversed text (look for reversed "بكالوريا" → "ايرولاكب")
3. Gemini verification pass: send page image + extracted text → get JSON verdict
4. Auto re-extraction for pages with issues (up to MAX_RETRIES)
5. Quality report JSON per file: data/processed/quality_reports/{subject}/{stem}_quality.json
6. Final summary: data/processed/quality_summary.json

Usage:
    python -m scripts.verify_and_correct [--subjects arabe math ...] [--workers N] [--force]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Load .env early
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
if _ENV_PATH.exists():
    for _line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingestion.ocr_clean import (
    _is_arabic_char,
    _ocr_page_gemini,
    _render_page,
    ARABIC_SUBJECTS,
    _GEMINI_MODELS,
    _get_gemini_client,
    _gemini_rate_lock,
    _GEMINI_MIN_INTERVAL,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("verify")

ALL_SUBJECTS = ["arabe", "english", "francais", "islamic", "math", "physic", "svt"]
TEXTS_DIR   = ROOT / "data" / "processed" / "texts"
REPORTS_DIR = ROOT / "data" / "processed" / "quality_reports"
MAX_RETRIES = 3
MIN_PAGE_CHARS = 30  # below this, a page is considered empty/failed

_gemini_last_call: float = 0.0

# ---------------------------------------------------------------------------
# Gemini verification prompt
# ---------------------------------------------------------------------------
_VERIFY_PROMPT = """You are a quality-control AI for Algerian Baccalaureate (BAC) exam text extraction.

Subject: {subject}
Expected language: {lang_hint}
Page {page_num} of {total_pages}

I will give you:
1. The page image
2. The extracted text (below)

Evaluate the extracted text against what you see in the image.

Respond with ONLY a JSON object — no markdown, no explanation:
{{
  "verdict": "good" | "minor_issues" | "major_issues" | "reprocess",
  "issues": ["list", "of", "issues"],
  "confidence": 0.0-1.0,
  "notes": "brief note"
}}

Verdict meanings:
- "good": text faithfully captures the page content (minor formatting differences OK)
- "minor_issues": small mistakes but content is mostly correct
- "major_issues": significant errors, missing content, or wrong language
- "reprocess": text is wrong enough that the page should be re-extracted

Extracted text:
---
{extracted_text}
---"""

_LANG_HINTS = {
    "arabe":    "Arabic (right-to-left)",
    "islamic":  "Arabic (right-to-left)",
    "svt":      "Arabic with French scientific terms",
    "physic":   "Arabic with French scientific terms and math formulas",
    "math":     "Arabic with mathematical formulas",
    "francais": "French",
    "english":  "English",
}

# ---------------------------------------------------------------------------
# Local quality checks (no API)
# ---------------------------------------------------------------------------

def _arabic_density(text: str) -> float:
    if not text.strip():
        return 0.0
    return sum(1 for c in text if _is_arabic_char(c)) / max(len(text.strip()), 1)


def _avg_arabic_token_len(text: str) -> float:
    tokens = [t for t in re.split(r"\s+", text) if any(_is_arabic_char(c) for c in t)]
    if not tokens:
        return 0.0
    return sum(len(t) for t in tokens) / len(tokens)


_REVERSED_BAKALOURIA = "ايرولاكب"  # "بكالوريا" reversed


def _has_reversed_text(text: str) -> bool:
    return _REVERSED_BAKALOURIA in text


def _local_page_check(page_text: str, subject: str) -> Dict[str, Any]:
    """Run fast local checks on a single page's text. Return issues list."""
    issues = []
    char_count = len(page_text.strip())

    if char_count < MIN_PAGE_CHARS:
        issues.append(f"very_short ({char_count} chars)")

    if subject in ARABIC_SUBJECTS:
        density = _arabic_density(page_text)
        if density < 0.10 and char_count > 50:
            issues.append(f"low_arabic_density ({density:.2f})")
        avg_tok = _avg_arabic_token_len(page_text)
        if avg_tok > 0 and avg_tok <= 3.5 and density > 0.40:
            issues.append(f"fragmented_arabic (avg_tok={avg_tok:.1f})")

    if _has_reversed_text(page_text):
        issues.append("reversed_text_detected")

    # Check for obvious garble: long runs of non-word Arabic chars
    garble_re = re.compile(r"[؀-ۿ]{1,2}(?:\s+[؀-ۿ]{1,2}){5,}")
    if garble_re.search(page_text):
        issues.append("garble_pattern_detected")

    return {
        "char_count": char_count,
        "issues": issues,
        "local_pass": len(issues) == 0,
    }


# ---------------------------------------------------------------------------
# Gemini verification
# ---------------------------------------------------------------------------

def _verify_page_gemini(
    pil_img: Any,
    page_text: str,
    subject: str,
    page_num: int,
    total_pages: int,
) -> Dict[str, Any]:
    """Send page image + extracted text to Gemini for verification.

    Returns a verdict dict.
    """
    global _gemini_last_call

    client = _get_gemini_client()
    if client is None:
        return {"verdict": "unknown", "issues": ["gemini_unavailable"], "confidence": 0.0}

    try:
        import io
        from google.genai import types as _gtypes

        buf = io.BytesIO()
        pil_img.save(buf, format="PNG")
        img_bytes = buf.getvalue()

        prompt = _VERIFY_PROMPT.format(
            subject=subject,
            lang_hint=_LANG_HINTS.get(subject, "Arabic or French"),
            page_num=page_num,
            total_pages=total_pages,
            extracted_text=page_text[:3000],  # cap to avoid token overflow
        )
        contents = [
            _gtypes.Part.from_bytes(data=img_bytes, mime_type="image/png"),
            prompt,
        ]

        for model in _GEMINI_MODELS:
            for attempt in range(3):
                with _gemini_rate_lock:
                    now = time.time()
                    wait = _GEMINI_MIN_INTERVAL - (now - _gemini_last_call)
                    if wait > 0:
                        time.sleep(wait)
                    _gemini_last_call = time.time()

                try:
                    response = client.models.generate_content(
                        model=model, contents=contents
                    )
                    raw = (response.text or "").strip()
                    # Strip markdown fences if present
                    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
                    raw = re.sub(r"\s*```$", "", raw)
                    result = json.loads(raw)
                    result.setdefault("model_used", model)
                    return result

                except json.JSONDecodeError:
                    logger.warning("Gemini verify: bad JSON from %s: %s", model, raw[:100])
                    return {"verdict": "unknown", "issues": ["bad_json_response"], "confidence": 0.0, "raw": raw[:200]}

                except Exception as exc:
                    err = str(exc)
                    if "429" in err or "RESOURCE_EXHAUSTED" in err:
                        m = re.search(r"retry[^\d]*(\d+(?:\.\d+)?)\s*s", err, re.I)
                        sleep_s = float(m.group(1)) if m else 60.0
                        time.sleep(sleep_s + 2)
                        continue
                    if "503" in err or "UNAVAILABLE" in err:
                        time.sleep(min(4.0 * (attempt + 1), 30.0))
                        continue
                    break

    except Exception as exc:
        logger.warning("Gemini verify setup error: %s", exc)

    return {"verdict": "unknown", "issues": ["gemini_call_failed"], "confidence": 0.0}


# ---------------------------------------------------------------------------
# Re-extraction
# ---------------------------------------------------------------------------

_ENHANCED_PROMPT = """You are extracting text from an Algerian Baccalaureate (BAC) exam page.

Subject: {subject}
Expected language: {lang_hint}
Page {page_num} of {total_pages}

CRITICAL INSTRUCTIONS:
- Extract ONLY horizontally-written text; COMPLETELY IGNORE any text printed sideways, rotated, or in margins
- Arabic text flows RIGHT-TO-LEFT; preserve this natural reading order for every Arabic word
- Numbers and formulas keep their exact form
- Separate sections and questions with a blank line
- Keep numbering: "أولاً:", "ثانياً:", "الجزء الأول:", "Exercice 1:", "Question 1:", etc.
- Output ONLY extracted text — no explanations, no translations, no commentary
- If the page is blank, output: [PAGE UNREADABLE]

The previous extraction attempt had quality issues. Please extract carefully and completely."""


def _reextract_page(
    pdf_path: Path,
    page_num: int,
    subject: str,
    total_pages: int,
) -> str:
    """Re-extract a single page using Gemini with the enhanced prompt."""
    try:
        import pdfplumber

        with pdfplumber.open(str(pdf_path)) as pdf:
            if page_num > len(pdf.pages):
                return ""
            page = pdf.pages[page_num - 1]
            pil = _render_page(page)
            if pil is None:
                return ""

        global _gemini_last_call
        client = _get_gemini_client()
        if client is None:
            return ""

        import io
        from google.genai import types as _gtypes

        buf = io.BytesIO()
        pil.save(buf, format="PNG")
        img_bytes = buf.getvalue()

        prompt = _ENHANCED_PROMPT.format(
            subject=subject,
            lang_hint=_LANG_HINTS.get(subject, "Arabic or French"),
            page_num=page_num,
            total_pages=total_pages,
        )
        contents = [
            _gtypes.Part.from_bytes(data=img_bytes, mime_type="image/png"),
            prompt,
        ]

        for model in _GEMINI_MODELS:
            for attempt in range(3):
                with _gemini_rate_lock:
                    now = time.time()
                    wait = _GEMINI_MIN_INTERVAL - (now - _gemini_last_call)
                    if wait > 0:
                        time.sleep(wait)
                    _gemini_last_call = time.time()

                try:
                    response = client.models.generate_content(
                        model=model, contents=contents
                    )
                    text = (response.text or "").strip()
                    if text and text != "[PAGE UNREADABLE]":
                        return text
                    return ""

                except Exception as exc:
                    err = str(exc)
                    if "429" in err or "RESOURCE_EXHAUSTED" in err:
                        m = re.search(r"retry[^\d]*(\d+(?:\.\d+)?)\s*s", err, re.I)
                        sleep_s = float(m.group(1)) if m else 60.0
                        time.sleep(sleep_s + 2)
                        continue
                    if "503" in err or "UNAVAILABLE" in err:
                        time.sleep(min(4.0 * (attempt + 1), 30.0))
                        continue
                    break

    except Exception as exc:
        logger.warning("Re-extract page %d failed: %s", page_num, exc)

    return ""


# ---------------------------------------------------------------------------
# Parse extracted txt file
# ---------------------------------------------------------------------------

def _parse_pages(txt_content: str) -> Dict[int, str]:
    """Split extracted text into page-indexed dict: {page_num: text}."""
    pages: Dict[int, str] = {}
    current_page = 0
    current_lines: List[str] = []

    for line in txt_content.splitlines():
        m = re.match(r"^\[PAGE\s+(\d+)\]", line.strip())
        if m:
            if current_page > 0:
                pages[current_page] = "\n".join(current_lines).strip()
            current_page = int(m.group(1))
            current_lines = []
        else:
            if current_page > 0:
                current_lines.append(line)

    if current_page > 0:
        pages[current_page] = "\n".join(current_lines).strip()

    return pages


# ---------------------------------------------------------------------------
# Main per-file verification
# ---------------------------------------------------------------------------

def verify_file(
    record: Dict[str, Any],
    force_report: bool = False,
    use_gemini_verify: bool = True,
) -> Dict[str, Any]:
    """Verify and if needed correct one file. Return quality report dict."""
    subject = record["subject"]
    pdf_path = ROOT / record["path"]
    stem = pdf_path.stem
    txt_path = TEXTS_DIR / subject / f"{stem}.txt"
    report_path = REPORTS_DIR / subject / f"{stem}_quality.json"

    report_path.parent.mkdir(parents=True, exist_ok=True)

    # Skip if report already exists and not forced
    if report_path.exists() and not force_report:
        try:
            return json.loads(report_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    report: Dict[str, Any] = {
        "stem": stem,
        "subject": subject,
        "pdf_path": record["path"],
        "year": record.get("year"),
        "verified_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "pdf_page_count": 0,
        "extracted_page_count": 0,
        "page_count_match": False,
        "pages": {},
        "overall_verdict": "unknown",
        "issues_found": [],
        "corrections_made": 0,
        "retry_count": 0,
        "final_status": "pending",
    }

    # ── Check txt exists ─────────────────────────────────────────────────
    if not txt_path.exists() or txt_path.stat().st_size == 0:
        report["overall_verdict"] = "missing"
        report["final_status"] = "failed_missing_txt"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report

    if not pdf_path.exists():
        report["overall_verdict"] = "error"
        report["final_status"] = "failed_missing_pdf"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report

    # ── Count PDF pages ──────────────────────────────────────────────────
    try:
        import pdfplumber
        with pdfplumber.open(str(pdf_path)) as pdf:
            pdf_page_count = len(pdf.pages)
    except Exception as exc:
        report["overall_verdict"] = "error"
        report["final_status"] = f"failed_pdf_open: {exc}"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report

    report["pdf_page_count"] = pdf_page_count

    # ── Parse extracted text ─────────────────────────────────────────────
    txt_content = txt_path.read_text(encoding="utf-8")
    extracted_pages = _parse_pages(txt_content)
    report["extracted_page_count"] = len(extracted_pages)
    report["page_count_match"] = (len(extracted_pages) == pdf_page_count)

    all_issues: List[str] = []
    pages_needing_reprocess: List[int] = []
    page_reports: Dict[str, Any] = {}

    # ── Per-page checks ──────────────────────────────────────────────────
    if not report["page_count_match"]:
        all_issues.append(
            f"page_count_mismatch: pdf={pdf_page_count} extracted={len(extracted_pages)}"
        )

    for page_num in range(1, pdf_page_count + 1):
        page_text = extracted_pages.get(page_num, "")
        local = _local_page_check(page_text, subject)
        page_report = {
            "page_num": page_num,
            "char_count": local["char_count"],
            "local_issues": local["issues"],
            "local_pass": local["local_pass"],
            "gemini_verdict": None,
            "gemini_issues": [],
            "reprocessed": False,
            "retry_count": 0,
            "final_status": "pending",
        }

        needs_reprocess = not local["local_pass"]

        # Gemini verify for pages with local issues OR pages selected for spot-check
        if use_gemini_verify and (not local["local_pass"] or page_num == 1):
            try:
                import pdfplumber
                with pdfplumber.open(str(pdf_path)) as pdf:
                    if page_num <= len(pdf.pages):
                        page_obj = pdf.pages[page_num - 1]
                        pil = _render_page(page_obj)
                        if pil is not None:
                            verdict_data = _verify_page_gemini(
                                pil, page_text, subject, page_num, pdf_page_count
                            )
                            page_report["gemini_verdict"] = verdict_data.get("verdict")
                            page_report["gemini_issues"] = verdict_data.get("issues", [])
                            page_report["gemini_confidence"] = verdict_data.get("confidence", 0.0)

                            g_verdict = verdict_data.get("verdict", "unknown")
                            if g_verdict in ("minor_issues", "major_issues", "reprocess"):
                                needs_reprocess = True
            except Exception as exc:
                logger.warning("Gemini verify error for %s p%d: %s", stem, page_num, exc)

        if needs_reprocess:
            pages_needing_reprocess.append(page_num)

        page_reports[str(page_num)] = page_report

    report["pages"] = page_reports

    # ── Re-extraction loop ───────────────────────────────────────────────
    corrected_pages: Dict[int, str] = {}
    total_corrections = 0

    for page_num in pages_needing_reprocess:
        page_report = page_reports[str(page_num)]
        page_text = extracted_pages.get(page_num, "")

        for attempt in range(MAX_RETRIES):
            page_report["retry_count"] = attempt + 1
            new_text = _reextract_page(pdf_path, page_num, subject, pdf_page_count)

            if new_text:
                local_check = _local_page_check(new_text, subject)
                if local_check["local_pass"] or attempt == MAX_RETRIES - 1:
                    corrected_pages[page_num] = new_text
                    page_report["reprocessed"] = True
                    page_report["final_status"] = "corrected"
                    total_corrections += 1
                    break
            else:
                if attempt == MAX_RETRIES - 1:
                    page_report["final_status"] = "reprocess_failed"
        else:
            page_report.setdefault("final_status", "reprocess_failed")

    # ── Write corrected file if any pages were fixed ─────────────────────
    if corrected_pages:
        new_pages = dict(extracted_pages)
        new_pages.update(corrected_pages)

        lines: List[str] = []
        for pn in range(1, pdf_page_count + 1):
            lines.append(f"[PAGE {pn}]")
            lines.append(new_pages.get(pn, ""))
            lines.append("")

        txt_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("Corrected %d pages in %s", len(corrected_pages), stem)

    # ── Finalize report ──────────────────────────────────────────────────
    report["corrections_made"] = total_corrections
    report["retry_count"] = sum(
        p.get("retry_count", 0) for p in page_reports.values()
    )
    report["issues_found"] = all_issues

    # Overall verdict
    failed_pages = [
        p for p in page_reports.values()
        if p.get("final_status") == "reprocess_failed"
    ]
    problem_pages = [
        p for p in page_reports.values()
        if p.get("local_issues")
        or p.get("gemini_verdict") in ("minor_issues", "major_issues", "reprocess")
    ]

    if failed_pages:
        report["overall_verdict"] = "partial_failure"
        report["final_status"] = "verified_with_failures"
    elif problem_pages and not corrected_pages:
        report["overall_verdict"] = "issues_found"
        report["final_status"] = "verified_issues_uncorrected"
    elif total_corrections > 0:
        report["overall_verdict"] = "corrected"
        report["final_status"] = "verified_corrected"
    else:
        report["overall_verdict"] = "good"
        report["final_status"] = "verified_pass"

    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


# ---------------------------------------------------------------------------
# Summary report
# ---------------------------------------------------------------------------

def write_summary(all_reports: List[Dict[str, Any]]) -> None:
    summary: Dict[str, Any] = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "total_files": len(all_reports),
        "verified_pass": 0,
        "verified_corrected": 0,
        "verified_best_effort": 0,
        "verified_issues_uncorrected": 0,
        "verified_with_failures": 0,
        "missing_txt": 0,
        "error": 0,
        "by_subject": {},
        "files_needing_attention": [],
    }

    for r in all_reports:
        status = r.get("final_status", "unknown")
        if status == "verified_pass":
            summary["verified_pass"] += 1
        elif status == "verified_corrected":
            summary["verified_corrected"] += 1
        elif status == "verified_best_effort":
            summary["verified_best_effort"] += 1
        elif status == "verified_issues_uncorrected":
            summary["verified_issues_uncorrected"] += 1
        elif status == "verified_with_failures":
            summary["verified_with_failures"] += 1
        elif "missing" in status:
            summary["missing_txt"] += 1
        else:
            summary["error"] += 1

        subj = r.get("subject", "unknown")
        s = summary["by_subject"].setdefault(subj, {
            "total": 0, "pass": 0, "corrected": 0, "issues": 0, "failed": 0
        })
        s["total"] += 1
        if "pass" in status:
            s["pass"] += 1
        elif "corrected" in status:
            s["corrected"] += 1
        elif "issue" in status or "failure" in status:
            s["issues"] += 1
        else:
            s["failed"] += 1

        if status not in ("verified_pass", "verified_corrected", "verified_best_effort"):
            summary["files_needing_attention"].append({
                "stem": r.get("stem"),
                "subject": subj,
                "status": status,
                "issues": r.get("issues_found", []),
            })

    out = ROOT / "data" / "processed" / "quality_summary.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Summary written to %s", out)
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_records(subjects: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    manifest_path = ROOT / "data" / "raw" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    subject_filter = set(subjects) if subjects else None
    records = []
    for r in manifest:
        if r.get("duplicate"):
            continue
        if r.get("family") not in ("A", "B"):
            continue
        if r.get("subject") not in ALL_SUBJECTS:
            continue
        if subject_filter and r.get("subject") not in subject_filter:
            continue
        records.append(r)
    return records


def main() -> None:
    p = argparse.ArgumentParser(description="Verify and correct BAC exam extractions")
    p.add_argument("--subjects", nargs="+", metavar="SUBJECT", default=None,
                   help="Subjects to verify (default: all 7)")
    p.add_argument("--workers", type=int, default=2,
                   help="Parallel workers (default: 2; Gemini calls are rate-limited)")
    p.add_argument("--force", action="store_true",
                   help="Re-verify even if report already exists")
    p.add_argument("--no-gemini-verify", action="store_true",
                   help="Skip Gemini verification pass (local checks only)")
    p.add_argument("--summary-only", action="store_true",
                   help="Only regenerate summary from existing reports")
    p.add_argument("--fix-issues", action="store_true",
                   help="Only re-process files with verified_issues_uncorrected status")
    args = p.parse_args()

    if args.summary_only:
        # Collect existing reports and regenerate summary
        all_reports = []
        for subject in ALL_SUBJECTS:
            rdir = REPORTS_DIR / subject
            if rdir.exists():
                for f in rdir.glob("*_quality.json"):
                    try:
                        all_reports.append(json.loads(f.read_text(encoding="utf-8")))
                    except Exception:
                        pass
        summary = write_summary(all_reports)
        print(f"\nSummary regenerated: {len(all_reports)} reports")
        print(json.dumps({k: v for k, v in summary.items() if k != "files_needing_attention"}, indent=2))
        return

    records = _build_records(args.subjects)

    # --fix-issues: only reprocess files with uncorrected issues
    if args.fix_issues:
        issue_stems = set()
        for f in REPORTS_DIR.rglob("*_quality.json"):
            try:
                r = json.loads(f.read_text(encoding="utf-8"))
                if r.get("final_status") in ("verified_issues_uncorrected", "verified_with_failures"):
                    verdicts = [p.get("gemini_verdict") for p in r.get("pages", {}).values()]
                    local_issues = [p.get("local_issues") for p in r.get("pages", {}).values()]
                    failed_p = [p for p in r.get("pages", {}).values() if p.get("final_status") == "reprocess_failed"]
                    is_real = (
                        any(v in ("minor_issues", "major_issues", "reprocess") for v in verdicts)
                        or any(x for x in local_issues)
                        or bool(failed_p)
                    )
                    if is_real:
                        issue_stems.add(r["stem"])
            except Exception:
                pass
        records = [r for r in records if Path(r["path"]).stem in issue_stems]
        logger.info("--fix-issues: %d files with real uncorrected issues", len(records))
        args.force = True  # always force re-verify for fix-issues mode

    total = len(records)
    use_gemini = not args.no_gemini_verify

    logger.info(
        "Verifying %d files | subjects=%s | workers=%d | gemini_verify=%s | force=%s",
        total,
        args.subjects or "all",
        args.workers,
        use_gemini,
        args.force,
    )

    all_reports: List[Dict[str, Any]] = []
    lock = threading.Lock()
    done = [0]

    def process(record: Dict[str, Any]) -> Dict[str, Any]:
        try:
            report = verify_file(record, force_report=args.force, use_gemini_verify=use_gemini)
        except Exception as exc:
            logger.error("Unhandled error for %s: %s", record.get("path"), exc)
            report = {
                "stem": Path(record.get("path", "")).stem,
                "subject": record.get("subject", ""),
                "final_status": f"unhandled_error: {exc}",
                "overall_verdict": "error",
            }

        with lock:
            done[0] += 1
            all_reports.append(report)
            status = report.get("final_status", "?")
            stem = report.get("stem", "?")
            corrections = report.get("corrections_made", 0)
            logger.info(
                "[%d/%d] %s → %s%s",
                done[0], total, stem, status,
                f" ({corrections} pages corrected)" if corrections else "",
            )

        return report

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(process, r): r for r in records}
        for f in as_completed(futures):
            try:
                f.result()
            except Exception as exc:
                logger.error("Future error: %s", exc)

    # Write summary
    summary = write_summary(all_reports)

    # Final stats
    print("\n" + "=" * 60)
    print("VERIFICATION COMPLETE")
    print(f"  Total files : {total}")
    print(f"  Pass        : {summary['verified_pass']}")
    print(f"  Corrected   : {summary['verified_corrected']}")
    print(f"  Issues      : {summary['verified_issues_uncorrected']}")
    print(f"  Failures    : {summary['verified_with_failures']}")
    print(f"  Missing txt : {summary['missing_txt']}")
    if summary["files_needing_attention"]:
        print(f"\n  Files needing attention: {len(summary['files_needing_attention'])}")
        for f in summary["files_needing_attention"][:10]:
            print(f"    {f['subject']}/{f['stem']}: {f['status']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
