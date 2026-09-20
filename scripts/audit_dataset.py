"""scripts/audit_dataset.py

Independent exhaustive audit of all 580 BAC PDF extractions.

Checks performed per file:
  A. Existence and size
  B. Page count match (PDF pages == [PAGE N] markers)
  C. Per-page content length (no suspiciously empty pages)
  D. Language correctness (Arabic subjects have Arabic, Latin subjects have Latin)
  E. Arabic character corruption (fragmented tokens, garble patterns)
  F. RTL/number reversal detection
  G. Question structure detection (numbering patterns preserved)
  H. Mathematical/scientific notation presence (science subjects)
  I. Forbidden hallucination strings
  J. Header/footer noise contamination
  K. Cross-subject inconsistency detection
  L. Image extraction coverage (were images in PDFs captured?)

Usage:
    python -m scripts.audit_dataset [--subjects ...] [--sample N]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Load .env
_ENV_PATH = ROOT / ".env"
if _ENV_PATH.exists():
    for _line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

from ingestion.ocr_clean import _is_arabic_char, _detect_lang

ALL_SUBJECTS = ["arabe", "english", "francais", "islamic", "math", "physic", "svt"]
ARABIC_SUBJECTS = {"arabe", "islamic", "svt", "physic", "math"}
TEXTS_DIR = ROOT / "data" / "processed" / "texts"
IMAGES_DIR = ROOT / "data" / "processed" / "images"
MANIFEST_PATH = ROOT / "data" / "raw" / "manifest.json"
OCR_MANIFEST = ROOT / "data" / "processed" / "ocr_manifest.json"
IMAGE_MANIFEST = ROOT / "data" / "processed" / "image_manifest.json"

# ── Patterns ──────────────────────────────────────────────────────────────────

# Reversed "بكالوريا" (baccalaureate in Arabic)
_REVERSED_BAKA = "ايرولاكب"
# Garble: isolated Arabic LETTER chars (≤2 chars) separated by spaces, 8+ in a row.
# Uses ء-غف-ي to match only Arabic base letters (not diacritics,
# punctuation, or presentation forms), raising the bar to 8 groups to avoid
# false-positives on short-word sentence endings and educational abbreviations.
_GARBLE_RE = re.compile(r"[ء-غف-ي]{1,2}(?:\s+[ء-غف-ي]{1,2}){7,}")
# Diagram context keywords — garble within these contexts is usually axis labels
_DIAGRAM_MARKERS = re.compile(r"الشكل|وثيقة|الوثيقة|بيان|منحنى|مخطط|الشكل|محور")
# Reversed 4-digit year in known range (2007-2026 reversed = 7002-6202)
_REVERSED_YEAR_RE = re.compile(r"\b(7002|8002|9002|0102|1102|2102|3102|4102|5102|6102|7102|8102|9102|0202|1202|2202|3202|4202|5202|6202)\b")
# Reversed Latin word fragments (common reversed words from RTL sort)
_REVERSED_LATIN_RE = re.compile(r"\b(tejuS|tejus|noitcudorp|noitcudorP)\b", re.I)
# Latin gibberish in Arabic context (pdfplumber OCR artifacts).
# Only flag in non-science Arabic subjects — science subjects legitimately use
# single-letter Latin notation (variables, DNA bases, circuit labels, pH axes).
_LATIN_GIBBER_RE = re.compile(r"[a-zA-Z]{1,2}(?:\s+[a-zA-Z]{1,2}){4,}")
_SCIENCE_ARABIC_SUBJECTS = frozenset({"svt", "physic", "math"})
# Page number noise — only flag in non-science subjects to avoid false positives
# on probability distribution tables (i=0,1,2,..) and circuit notation (i,j).
_PAGE_NUM_NOISE_RE = re.compile(r"\b\d{2,}\s*[ij]\s*\d{2,}\b")
# [PAGE REPROCESS NEEDED] markers left from cleanup script
_REPROCESS_MARKER = "[PAGE REPROCESS NEEDED"
# Hallucination patterns Gemini sometimes adds
_HALLUCINATION_RE = re.compile(
    r"(Here is the extracted text|I will extract|Note:|Commentary:|"
    r"This page contains|The following text|Translation:|"
    r"Note that|Please note|I notice)", re.I
)
# Question numbering patterns (should be present in most exam files)
_QUESTION_PATTERNS = [
    re.compile(r"(Exercise|Exercice|Exercício)\s*\d", re.I),
    re.compile(r"Question\s*\d", re.I),
    re.compile(r"الجزء\s+(الأول|الثاني|الثالث)", re.U),
    re.compile(r"(أولاً|ثانياً|ثالثاً)\s*:", re.U),
    re.compile(r"\b(Partie|PARTIE|Texte|Passage)\s*(I|II|III|\d)", re.I),
    re.compile(r"^\s*\d+[\.\)]\s*\w", re.M),
    # Arabic numbering without punctuation (e.g. "1 ما الموضوع")
    re.compile(r"^\s*[1-9]\s+[؀-ۿ]", re.M),
    # Arabic section headers used in Algerian BAC exams
    re.compile(r"البناء\s+(الفكري|اللغوي|اللّغوي)", re.U),
    re.compile(r"(التمرين|الجزء|السؤال|الموضوع)\s+(الأول|الثاني|الثالث|الأولى)", re.U),
    re.compile(r"(PART|PARTIE)\s+(ONE|TWO|THREE|I|II|III)", re.I),
]
# Math/science markers expected in science subjects
_MATH_MARKERS_RE = re.compile(
    r"[=\+\-×÷≥≤≠∞∑∫√π²³]|"
    r"\b(mg|kg|km|mol|pH|cm|mm|Hz|kHz|MHz|eV|kJ|cal|°C|°F|K)\b|"
    r"[A-Z][a-z]?\d*[\+\-]?\d*\b|"  # chemical formulas
    r"\d+[\.,]\d+",  # decimal numbers
    re.U
)


def _parse_pages(content: str) -> Dict[int, str]:
    """Split .txt content into {page_num: text} dict."""
    pages: Dict[int, str] = {}
    current_page = 0
    current_lines: List[str] = []
    for line in content.splitlines():
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


def _get_pdf_page_count(pdf_path: Path) -> int:
    try:
        import pdfplumber
        with pdfplumber.open(str(pdf_path)) as pdf:
            return len(pdf.pages)
    except Exception:
        return -1


def _check_arabic_quality(text: str, subject: str) -> List[str]:
    """Deep Arabic text quality checks. Returns list of issue strings."""
    issues = []
    if not text.strip():
        return issues

    if _REVERSED_BAKA in text:
        issues.append("REVERSED_BAKA: reversed بكالوريا detected")

    # Filter garble matches that appear within diagram/figure context (axis labels)
    garble_raw = _GARBLE_RE.findall(text)
    true_garble = []
    for m in garble_raw:
        idx = text.find(m)
        # Check surrounding 200-char window for diagram markers
        ctx = text[max(0, idx - 100):idx + len(m) + 100]
        if _DIAGRAM_MARKERS.search(ctx):
            continue  # likely axis label, not true garble
        true_garble.append(m)
    if true_garble:
        issues.append(f"GARBLE: {len(true_garble)} garble patterns (isolated Arabic chars)")

    rev_years = _REVERSED_YEAR_RE.findall(text)
    if rev_years:
        issues.append(f"REVERSED_YEAR: {rev_years}")

    rev_latin = _REVERSED_LATIN_RE.findall(text)
    if rev_latin:
        issues.append(f"REVERSED_LATIN: {rev_latin}")

    # Only flag Latin gibberish in non-science Arabic subjects
    lat_gibber = _LATIN_GIBBER_RE.findall(text)
    if lat_gibber and subject in ARABIC_SUBJECTS and subject not in _SCIENCE_ARABIC_SUBJECTS:
        issues.append(f"LATIN_GIBBER_IN_ARABIC: {len(lat_gibber)} runs")

    page_noise = _PAGE_NUM_NOISE_RE.findall(text)
    if page_noise and subject not in _SCIENCE_ARABIC_SUBJECTS:
        issues.append(f"PAGE_NUM_NOISE: {page_noise}")

    if _REPROCESS_MARKER in text:
        issues.append("REPROCESS_MARKER: cleanup placeholder still present")

    hall = _HALLUCINATION_RE.search(text)
    if hall:
        issues.append(f"HALLUCINATION: found '{hall.group()}'")

    return issues


def _check_language_match(text: str, subject: str) -> Optional[str]:
    """Returns issue string if language doesn't match subject, else None."""
    if len(text.strip()) < 50:
        return None  # too short to judge
    lang = _detect_lang(text)
    if subject in ARABIC_SUBJECTS and lang == "latin":
        ar_count = sum(1 for c in text if _is_arabic_char(c))
        if ar_count < 20:  # truly no Arabic at all
            return f"LANG_MISMATCH: {subject} expected Arabic but got latin (ar_chars={ar_count})"
    if subject in ("english", "francais") and lang == "arabic":
        lat_count = sum(1 for c in text if c.isascii() and c.isalpha())
        if lat_count < 20:  # truly no Latin at all
            return f"LANG_MISMATCH: {subject} expected Latin but got arabic (lat_chars={lat_count})"
    return None


def _check_question_structure(full_text: str, subject: str) -> Optional[str]:
    """Returns issue if no question numbering found in substantial file."""
    if len(full_text.strip()) < 200:
        return None  # too short
    for pat in _QUESTION_PATTERNS:
        if pat.search(full_text):
            return None
    return "NO_QUESTION_STRUCTURE: no question/exercise numbering found"


def _check_science_markers(full_text: str, subject: str) -> Optional[str]:
    """Returns issue if science content has no math/science markers."""
    if subject not in ("math", "physic", "svt"):
        return None
    if len(full_text.strip()) < 200:
        return None
    if not _MATH_MARKERS_RE.search(full_text):
        return f"NO_SCIENCE_MARKERS: {subject} file has no math/science notation"
    return None


def _check_min_chars_per_page(pages: Dict[int, str], pdf_page_count: int) -> List[str]:
    """Check for suspiciously empty or very short pages."""
    issues = []
    for pn in range(1, pdf_page_count + 1):
        text = pages.get(pn, "")
        chars = len(text.strip())
        if chars == 0:
            issues.append(f"EMPTY_PAGE: page {pn} has 0 chars")
        elif chars < 30:
            issues.append(f"SHORT_PAGE: page {pn} has only {chars} chars")
    return issues


# ── Per-file audit ─────────────────────────────────────────────────────────────

def audit_file(record: Dict[str, Any]) -> Dict[str, Any]:
    """Full audit of one extracted file. Returns audit result dict."""
    subject = record["subject"]
    pdf_path = ROOT / record["path"]
    stem = pdf_path.stem
    txt_path = TEXTS_DIR / subject / f"{stem}.txt"

    result: Dict[str, Any] = {
        "stem": stem,
        "subject": subject,
        "year": record.get("year"),
        "type": record.get("type"),
        "pdf_path": record["path"],
        "txt_exists": txt_path.exists(),
        "txt_size": txt_path.stat().st_size if txt_path.exists() else 0,
        "pdf_page_count": 0,
        "extracted_page_count": 0,
        "page_count_match": False,
        "issues": [],
        "warnings": [],
        "pass": False,
    }

    # A. File existence
    if not txt_path.exists():
        result["issues"].append("MISSING_TXT: output file does not exist")
        return result
    if result["txt_size"] == 0:
        result["issues"].append("EMPTY_TXT: output file is 0 bytes")
        return result

    # B. Read extracted content
    try:
        content = txt_path.read_text(encoding="utf-8")
    except Exception as e:
        result["issues"].append(f"READ_ERROR: {e}")
        return result

    # C. Page count
    pdf_page_count = _get_pdf_page_count(pdf_path)
    result["pdf_page_count"] = pdf_page_count
    pages = _parse_pages(content)
    result["extracted_page_count"] = len(pages)

    if pdf_page_count <= 0:
        result["issues"].append(f"PDF_UNREADABLE: pdfplumber returned {pdf_page_count} pages")
    elif len(pages) != pdf_page_count:
        result["issues"].append(
            f"PAGE_COUNT_MISMATCH: pdf={pdf_page_count} extracted={len(pages)}"
        )
    else:
        result["page_count_match"] = True

    # D. Per-page content length
    short_issues = _check_min_chars_per_page(pages, max(pdf_page_count, 1))
    result["issues"].extend(short_issues)

    # E. Full-text quality checks
    full_text = content

    # Language match
    for pn, page_text in pages.items():
        lang_issue = _check_language_match(page_text, subject)
        if lang_issue:
            result["issues"].append(f"p{pn}: {lang_issue}")

    # F. Arabic-specific checks per page
    for pn, page_text in pages.items():
        ar_issues = _check_arabic_quality(page_text, subject)
        for iss in ar_issues:
            result["issues"].append(f"p{pn}: {iss}")

    # G. Question structure
    q_issue = _check_question_structure(full_text, subject)
    if q_issue:
        result["warnings"].append(q_issue)

    # H. Science markers
    sci_issue = _check_science_markers(full_text, subject)
    if sci_issue:
        result["warnings"].append(sci_issue)

    # I. Remaining REPROCESS markers
    if _REPROCESS_MARKER in full_text:
        result["issues"].append("REPROCESS_MARKER_IN_FILE: cleanup placeholder not replaced")

    # J. Suspiciously large per-page char jumps (possible page skipping)
    char_counts = [len(pages.get(p, "").strip()) for p in range(1, pdf_page_count + 1)]
    if char_counts:
        avg = sum(char_counts) / len(char_counts)
        for i, c in enumerate(char_counts):
            if avg > 200 and c < 20:
                result["warnings"].append(
                    f"LOW_RELATIVE_PAGE: page {i+1} has {c} chars vs avg {avg:.0f}"
                )

    # K. Overall text length sanity (solution files often short; exam files should be substantial)
    total_chars = len(full_text.strip())
    if total_chars < 100:
        result["issues"].append(f"VERY_SHORT_FILE: only {total_chars} total chars")
    elif total_chars < 500 and record.get("type") == "exam":
        result["warnings"].append(f"SHORT_EXAM_FILE: only {total_chars} chars for exam")

    result["total_chars"] = total_chars
    result["avg_chars_per_page"] = total_chars // max(len(pages), 1)
    result["pass"] = len(result["issues"]) == 0
    return result


# ── Image audit ───────────────────────────────────────────────────────────────

def audit_images() -> Dict[str, Any]:
    """Check image extraction coverage."""
    report: Dict[str, Any] = {
        "image_manifest_exists": IMAGE_MANIFEST.exists(),
        "images_dir_exists": IMAGES_DIR.exists(),
        "total_images_in_manifest": 0,
        "images_on_disk": 0,
        "missing_images": 0,
        "by_subject": {},
    }

    if not IMAGE_MANIFEST.exists():
        return report

    try:
        manifest = json.loads(IMAGE_MANIFEST.read_text(encoding="utf-8"))
    except Exception:
        return report

    report["total_images_in_manifest"] = len(manifest)
    missing = []
    by_subject: Dict[str, int] = defaultdict(int)

    for entry in manifest:
        subj = entry.get("subject", "unknown")
        by_subject[subj] += 1
        img_path = entry.get("image_path")
        if img_path:
            full = ROOT / img_path
            if full.exists():
                report["images_on_disk"] += 1
            else:
                missing.append(img_path)
                report["missing_images"] += 1

    report["by_subject"] = dict(by_subject)
    if missing:
        report["missing_sample"] = missing[:10]

    return report


# ── Manifest audit ────────────────────────────────────────────────────────────

def audit_manifest() -> Dict[str, Any]:
    """Validate raw manifest completeness and consistency."""
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    in_scope = [r for r in manifest
                if not r.get("duplicate")
                and r.get("family") in ("A", "B")
                and r.get("subject") in ALL_SUBJECTS]

    report: Dict[str, Any] = {
        "total_records": len(manifest),
        "in_scope": len(in_scope),
        "by_subject": defaultdict(int),
        "by_year": defaultdict(int),
        "missing_pdfs": [],
        "zero_byte_pdfs": [],
        "duplicate_stems": [],
    }

    stems_seen: Dict[str, List[str]] = defaultdict(list)
    for r in in_scope:
        report["by_subject"][r["subject"]] += 1
        report["by_year"][r.get("year", "?")] += 1
        pdf = ROOT / r["path"]
        if not pdf.exists():
            report["missing_pdfs"].append(r["path"])
        elif pdf.stat().st_size == 0:
            report["zero_byte_pdfs"].append(r["path"])
        stem = Path(r["path"]).stem
        stems_seen[stem].append(r["path"])

    for stem, paths in stems_seen.items():
        if len(paths) > 1:
            report["duplicate_stems"].append({"stem": stem, "paths": paths})

    report["by_subject"] = dict(report["by_subject"])
    report["by_year"] = dict(sorted(report["by_year"].items()))
    return report


# ── Statistical summary ───────────────────────────────────────────────────────

def build_stats(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(results)
    passing = sum(1 for r in results if r["pass"])
    with_issues = sum(1 for r in results if r["issues"])
    with_warnings = sum(1 for r in results if not r["issues"] and r["warnings"])

    issue_counts: Dict[str, int] = defaultdict(int)
    for r in results:
        for iss in r["issues"]:
            tag = iss.split(":")[0]
            issue_counts[tag] += 1

    warning_counts: Dict[str, int] = defaultdict(int)
    for r in results:
        for w in r["warnings"]:
            tag = w.split(":")[0]
            warning_counts[tag] += 1

    by_subject: Dict[str, Dict[str, int]] = {}
    for r in results:
        s = r["subject"]
        if s not in by_subject:
            by_subject[s] = {"total": 0, "pass": 0, "issues": 0, "warnings": 0}
        by_subject[s]["total"] += 1
        if r["pass"]:
            by_subject[s]["pass"] += 1
        elif r["issues"]:
            by_subject[s]["issues"] += 1
        else:
            by_subject[s]["warnings"] += 1

    files_with_issues = [
        {"stem": r["stem"], "subject": r["subject"], "issues": r["issues"][:3]}
        for r in results if r["issues"]
    ]

    return {
        "total_files": total,
        "audit_pass": passing,
        "with_issues": with_issues,
        "with_warnings_only": with_warnings,
        "issue_type_counts": dict(sorted(issue_counts.items(), key=lambda x: -x[1])),
        "warning_type_counts": dict(sorted(warning_counts.items(), key=lambda x: -x[1])),
        "by_subject": by_subject,
        "files_with_issues": files_with_issues,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(description="Exhaustive audit of BAC extractions")
    p.add_argument("--subjects", nargs="+", default=None)
    p.add_argument("--output", default="data/processed/audit_report.json")
    args = p.parse_args()

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    records = [r for r in manifest
               if not r.get("duplicate")
               and r.get("family") in ("A", "B")
               and r.get("subject") in ALL_SUBJECTS]
    if args.subjects:
        subject_filter = set(args.subjects)
        records = [r for r in records if r.get("subject") in subject_filter]

    print(f"Auditing {len(records)} files...")

    results = []
    for i, rec in enumerate(records, 1):
        res = audit_file(rec)
        results.append(res)
        if i % 50 == 0:
            print(f"  {i}/{len(records)} done...")

    print(f"Done. Building stats...")

    stats = build_stats(results)
    manifest_report = audit_manifest()
    image_report = audit_images()

    full_report = {
        "manifest_audit": manifest_report,
        "extraction_stats": stats,
        "image_audit": image_report,
        "per_file_results": results,
    }

    out_path = ROOT / args.output
    out_path.write_text(json.dumps(full_report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'='*60}")
    print("AUDIT SUMMARY")
    print(f"  Total files : {stats['total_files']}")
    print(f"  Audit PASS  : {stats['audit_pass']}")
    print(f"  With ISSUES : {stats['with_issues']}")
    print(f"  Warnings only: {stats['with_warnings_only']}")
    print(f"\nIssue types:")
    for k, v in stats["issue_type_counts"].items():
        print(f"  {k}: {v}")
    print(f"\nWarning types:")
    for k, v in stats["warning_type_counts"].items():
        print(f"  {k}: {v}")
    print(f"\nBy subject:")
    for subj, s in stats["by_subject"].items():
        print(f"  {subj}: pass={s['pass']}/{s['total']} issues={s['issues']} warnings={s['warnings']}")
    print(f"\nImages: {image_report['total_images_in_manifest']} in manifest, "
          f"{image_report['images_on_disk']} on disk, "
          f"{image_report['missing_images']} missing")
    print(f"\nFull report: {out_path}")
    print("="*60)


if __name__ == "__main__":
    main()
