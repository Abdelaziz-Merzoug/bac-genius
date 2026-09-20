"""Fix reversed year digits in extracted text files.

For PDFs where digits are stored in RTL order, the _DIGIT_RUN reversal in
_extract_page_text_rtl causes years like "2018" to appear as "8102".
This script detects and corrects these in the extracted .txt files.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEXTS_DIR = PROJECT_ROOT / "data" / "processed" / "texts"
AUDIT_REPORT = PROJECT_ROOT / "data" / "processed" / "audit_report.json"

# Years in the BAC dataset
_VALID_YEARS = set(range(2008, 2027))


def _reverse_year(year: int) -> str:
    return str(year)[::-1]


def fix_file_all_years(txt_path: Path, dry_run: bool = False) -> dict:
    """Fix all reversed years (2008-2026) in a text file, regardless of the file's own year."""
    text = txt_path.read_text(encoding="utf-8")
    total_fixes = 0
    fixes = []

    for year in sorted(_VALID_YEARS, reverse=True):  # longest/most specific first
        rev = _reverse_year(year)
        correct = str(year)
        count = text.count(rev)
        if count > 0:
            text = text.replace(rev, correct)
            total_fixes += count
            fixes.append(f"{rev}→{correct}({count})")

    if total_fixes > 0 and not dry_run:
        txt_path.write_text(text, encoding="utf-8")

    return {
        "stem": txt_path.stem,
        "occurrences": total_fixes,
        "fixed": total_fixes > 0 and not dry_run,
        "detail": ", ".join(fixes),
    }


def fix_file(txt_path: Path, year: int, dry_run: bool = False) -> dict:
    rev = _reverse_year(year)
    correct = str(year)

    text = txt_path.read_text(encoding="utf-8")
    count = text.count(rev)
    if count == 0:
        return {"stem": txt_path.stem, "year": year, "reversed": rev, "occurrences": 0, "fixed": False}

    new_text = text.replace(rev, correct)
    if not dry_run:
        txt_path.write_text(new_text, encoding="utf-8")

    return {
        "stem": txt_path.stem,
        "year": year,
        "reversed": rev,
        "occurrences": count,
        "fixed": not dry_run,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Fix reversed year digits in extracted texts")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be fixed without writing")
    parser.add_argument("--all", action="store_true", help="Scan all txt files, not just REVERSED_YEAR from audit")
    args = parser.parse_args()

    # Load audit report to find REVERSED_YEAR files
    report = json.loads(AUDIT_REPORT.read_text("utf-8"))
    per_file = report["per_file_results"]

    targets: list[tuple[str, int]] = []

    if args.all:
        # Scan all txt files for any reversed year
        for entry in per_file:
            year = entry.get("year")
            if year and year in _VALID_YEARS:
                targets.append((entry["stem"], year))
    else:
        # Only files flagged with REVERSED_YEAR
        for entry in per_file:
            issues = entry.get("issues", [])
            if any("REVERSED_YEAR" in i for i in issues):
                year = entry.get("year")
                if year and year in _VALID_YEARS:
                    targets.append((entry["stem"], year))

    print(f"Targets: {len(targets)} files")

    results = []
    fixed_count = 0
    for stem, year in targets:
        # Find txt file
        subject = stem.split("_")[1]
        txt_path = TEXTS_DIR / subject / f"{stem}.txt"
        if not txt_path.exists():
            print(f"  MISSING: {txt_path}")
            continue

        result = fix_file(txt_path, year, dry_run=args.dry_run)
        results.append(result)

        if result["occurrences"] > 0:
            action = "WOULD FIX" if args.dry_run else "FIXED"
            print(f"  {action}: {stem} — '{result['reversed']}' → '{year}' ({result['occurrences']} occurrence(s))")
            fixed_count += 1

    print(f"\nSummary: {fixed_count}/{len(targets)} files had reversed years")
    if args.dry_run:
        print("Dry run — no files written.")

    # Also run on all files to catch any missed cases
    if not args.all:
        print("\nAlso scanning all files for any reversed year not caught by audit...")
        extra = 0
        for entry in per_file:
            stem = entry["stem"]
            year = entry.get("year")
            if not year or year not in _VALID_YEARS:
                continue
            subject = stem.split("_")[1]
            txt_path = TEXTS_DIR / subject / f"{stem}.txt"
            if not txt_path.exists():
                continue
            # Skip files already processed
            if any(r["stem"] == stem for r in results):
                continue
            rev = _reverse_year(year)
            text = txt_path.read_text(encoding="utf-8")
            if rev in text:
                result = fix_file(txt_path, year, dry_run=args.dry_run)
                action = "WOULD FIX" if args.dry_run else "FIXED"
                print(f"  {action} (extra): {stem} — '{rev}' → '{year}' ({result['occurrences']} occurrence(s))")
                extra += 1
        print(f"Extra fixes: {extra}")


if __name__ == "__main__":
    main()
