"""
scripts/rebuild_ocr_manifest.py

Rebuilds data/processed/ocr_manifest.json from quality reports and extracted text stats.
The existing manifest is stale: 487/580 files show {failed:1} or empty method_breakdown.

Method inference strategy (per file):
  - scanned_era: year <= 2014 → Gemini processed full pages
  - digital_era: year >= 2015 → pdfplumber primary; Gemini for low-quality/complex pages
  - reprocessed pages in quality report → Gemini was invoked on those pages
  - char_count == 0 on pages → Gemini fallback occurred
"""
from __future__ import annotations

import json
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).resolve().parent.parent
QUALITY_DIR  = PROJECT_ROOT / "data" / "processed" / "quality_reports"
TEXTS_DIR    = PROJECT_ROOT / "data" / "processed" / "texts"
MANIFEST_OUT = PROJECT_ROOT / "data" / "processed" / "ocr_manifest.json"

SUBJECTS = ["arabe", "english", "francais", "islamic", "math", "physic", "svt"]
SCANNED_ERA_MAX_YEAR = 2014


def get_char_counts(stem: str, subject: str) -> dict[int, int]:
    """Read the .txt file and count chars per page."""
    import re
    txt_path = TEXTS_DIR / subject / f"{stem}.txt"
    if not txt_path.exists():
        return {}
    text = txt_path.read_text("utf-8")
    parts = re.split(r"\[PAGE \d+\]", text)
    result = {}
    for i, part in enumerate(parts[1:], start=1):  # skip pre-marker content
        result[i] = len(part.strip())
    return result


def load_quality_report(stem: str, subject: str) -> dict | None:
    qpath = QUALITY_DIR / subject / f"{stem}_quality.json"
    if not qpath.exists():
        return None
    try:
        return json.loads(qpath.read_text("utf-8"))
    except Exception:
        return None


def infer_method_breakdown(
    stem: str,
    subject: str,
    year: int | None,
    quality: dict | None,
    char_counts: dict[int, int],
) -> dict:
    """Infer per-method page counts from available data."""
    is_scanned = year is not None and year <= SCANNED_ERA_MAX_YEAR

    if quality is None:
        # No quality report — use era heuristic only
        total = sum(char_counts.values())
        if is_scanned or total == 0:
            return {"gemini": len(char_counts)}
        return {"pdfplumber": len(char_counts)}

    pages = quality.get("pages", {})
    pdfplumber_pages = 0
    gemini_pages = 0

    for page_key, page_data in pages.items():
        reprocessed = page_data.get("reprocessed", False)
        char_count  = char_counts.get(int(page_key), page_data.get("char_count", 0))

        if is_scanned:
            # Scanned era: Gemini processed all pages as images
            gemini_pages += 1
        elif reprocessed:
            gemini_pages += 1
        elif char_count > 50:
            pdfplumber_pages += 1
        else:
            # Very low char count despite digital era → likely Gemini fallback
            gemini_pages += 1

    result = {}
    if pdfplumber_pages:
        result["pdfplumber"] = pdfplumber_pages
    if gemini_pages:
        result["gemini"] = gemini_pages
    return result or {"pdfplumber": len(pages) or len(char_counts)}


def build_entry(stem: str, subject: str) -> dict | None:
    quality = load_quality_report(stem, subject)
    char_counts = get_char_counts(stem, subject)

    if quality is None and not char_counts:
        return None  # No data at all

    year = None
    if quality:
        year = quality.get("year")
    if year is None:
        # Parse from stem: bac_{subj}_{year}_...
        parts = stem.split("_")
        for part in parts:
            if part.isdigit() and 2008 <= int(part) <= 2030:
                year = int(part)
                break

    method_breakdown = infer_method_breakdown(stem, subject, year, quality, char_counts)

    total_chars = sum(char_counts.values())
    page_count = len(char_counts)
    corrections = quality.get("corrections_made", 0) if quality else 0
    overall_verdict = quality.get("overall_verdict", "unknown") if quality else "unknown"
    final_status = quality.get("final_status", "unknown") if quality else "unknown"

    return {
        "stem": stem,
        "subject": subject,
        "year": year,
        "overall_verdict": overall_verdict,
        "final_status": final_status,
        "page_count": page_count,
        "total_chars": total_chars,
        "corrections_made": corrections,
        "method_breakdown": method_breakdown,
        "rebuilt_at": datetime.now(timezone.utc).isoformat(),
        "rebuild_note": "rebuilt from quality_reports + text stats (original manifest was stale)",
    }


def main():
    manifest = {}
    stats = defaultdict(int)
    method_totals = defaultdict(int)

    for subject in SUBJECTS:
        subj_dir = TEXTS_DIR / subject
        if not subj_dir.exists():
            print(f"  {subject}: texts dir missing")
            continue

        txt_files = sorted(subj_dir.glob("*.txt"))
        print(f"{subject}: {len(txt_files)} files")

        for txt_path in txt_files:
            stem = txt_path.stem
            entry = build_entry(stem, subject)
            if entry is None:
                stats["no_data"] += 1
                continue

            manifest[stem] = entry
            stats["built"] += 1
            for method, count in entry["method_breakdown"].items():
                method_totals[method] += count

    print(f"\nManifest rebuilt: {stats['built']} entries, {stats['no_data']} with no data")
    print(f"Method totals: {dict(method_totals)}")

    # Preserve any existing entries not in our rebuilt set as a backup
    old_manifest = {}
    if MANIFEST_OUT.exists():
        try:
            old_manifest = json.loads(MANIFEST_OUT.read_text("utf-8"))
        except Exception:
            pass

    # Write backup of old manifest
    backup = MANIFEST_OUT.with_suffix(".json.bak_stale")
    if not backup.exists() and old_manifest:
        backup.write_text(json.dumps(old_manifest, ensure_ascii=False, indent=2), "utf-8")
        print(f"Old manifest backed up: {backup}")

    MANIFEST_OUT.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), "utf-8")
    print(f"Manifest written: {MANIFEST_OUT}")
    print(f"  Total entries: {len(manifest)}")


if __name__ == "__main__":
    main()
