"""
scripts/audit_digit_runs.py

Audit extracted texts for _DIGIT_RUN reversal artifacts affecting non-year numbers.

The bug: _extract_page_text_rtl in ocr_clean.py reverses all digit runs when
sorting RTL Arabic lines. For Type-A PDFs (digits stored RTL in PDF stream),
this double-reversal corrupts correctly-ordered digits. fix_reversed_years.py
only repairs 4-digit years (2008–2026). Other multi-digit numbers may still be
reversed: section numbers, scores, physical constants, measurement values, etc.

Strategy:
1. Scan all physic/svt/math txt files for 2-8 digit number runs NOT in [2008-2026]
2. Flag numbers that look suspicious: appear in contexts where a student expects
   a specific value but the number seems inverted (e.g. 05 → 50, 001 → 100)
3. Output a report with candidate reversals and their context for manual review

This script reports ONLY — does not auto-fix, because we cannot reliably determine
if a number is reversed without comparing to original PDF.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from collections import defaultdict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEXTS_DIR    = PROJECT_ROOT / "data" / "processed" / "texts"
SCIENCE_SUBS = {"physic", "svt", "math"}

VALID_YEARS = set(range(2008, 2027))

# Patterns that suggest a reversed digit run
# A reversed 2-digit number: leading zero that would make no sense,
# or number that looks like it was originally written in RTL order
SUSPICIOUS_PATTERNS = [
    # Numbers with leading zero that aren't decimals (.05) or fractions
    (r"(?<![.,/])\b0\d+\b(?![.,])", "leading_zero_suspicious"),
    # 2-digit numbers in Arabic physics context that might be section numbers
    # (hard to detect without context — just collect all non-year 2+ digit numbers)
]

# Context words that suggest this is a section/question number (high suspicion)
SECTION_CONTEXT_RE = re.compile(
    r"(تمرين|جزء|السؤال|سؤال|الجزء|القسم|الفقرة|النقطة|نقطة|علامة)",
    re.UNICODE,
)

# Physical value context (lower suspicion — these are usually correct)
PHYS_CONTEXT_RE = re.compile(
    r"(كيلو|ميلي|نانو|ميكرو|هرتز|نيوتن|جول|واط|فولت|أمبير|أوم|كولوم|فاراد)",
    re.UNICODE,
)

NON_YEAR_DIGITS_RE = re.compile(r"\b\d{2,8}\b")


def is_suspicious_reversal(num: str, context: str) -> tuple[bool, str]:
    """
    Heuristic: is this multi-digit number potentially reversed?
    Returns (is_suspicious, reason).
    """
    n = int(num)

    # Skip years
    if n in VALID_YEARS:
        return False, ""

    # Skip numbers that look like they could be measurement values (hard to judge)
    # Focus on numbers that look like they might be reversed section/question numbers

    # Reversed two-digit: "50" appears where "05" would be strange,
    # OR "01" appears where "10" is expected
    if len(num) == 2:
        # Leading-zero two-digit numbers in non-decimal context are suspicious
        if num.startswith("0"):
            return True, f"2-digit leading-zero: '{num}' → reversed would be '{num[::-1]}'"
        # Two-digit numbers near section context words
        if SECTION_CONTEXT_RE.search(context):
            return True, f"2-digit '{num}' near section context"

    if len(num) == 3:
        if num.startswith("0"):
            return True, f"3-digit leading-zero: '{num}' → reversed would be '{num[::-1]}'"

    return False, ""


def scan_file(txt_path: Path, subject: str) -> list[dict]:
    text = txt_path.read_text("utf-8")
    findings = []

    for m in NON_YEAR_DIGITS_RE.finditer(text):
        num = m.group()
        start = max(0, m.start() - 80)
        end   = min(len(text), m.end() + 80)
        context = text[start:end]

        suspicious, reason = is_suspicious_reversal(num, context)
        if suspicious:
            findings.append({
                "file": txt_path.name,
                "subject": subject,
                "number": num,
                "reversed_would_be": num[::-1],
                "reason": reason,
                "context": context.replace("\n", " ").strip(),
                "offset": m.start(),
            })

    return findings


def main():
    all_findings = []
    stats = defaultdict(int)

    for subj in SCIENCE_SUBS:
        subj_dir = TEXTS_DIR / subj
        if not subj_dir.exists():
            continue
        txt_files = sorted(subj_dir.glob("*.txt"))
        print(f"{subj}: scanning {len(txt_files)} files...")
        for txt_path in txt_files:
            findings = scan_file(txt_path, subj)
            all_findings.extend(findings)
            stats[subj] += len(findings)

    print(f"\n=== _DIGIT_RUN Audit Results ===")
    print(f"Total suspicious patterns: {len(all_findings)}")
    for subj, cnt in sorted(stats.items()):
        print(f"  {subj}: {cnt}")

    # Group by file
    by_file = defaultdict(list)
    for f in all_findings:
        by_file[f["file"]].append(f)

    if all_findings:
        print(f"\nFiles with suspicious digit runs: {len(by_file)}")
        print("\nTop 20 most suspicious (leading-zero numbers):")
        leading_zero = [f for f in all_findings if f["reason"].startswith("leading")]
        for f in sorted(leading_zero, key=lambda x: x["file"])[:20]:
            print(f"  {f['file']} offset={f['offset']}: '{f['number']}' → would be '{f['reversed_would_be']}'")
            print(f"    context: ...{f['context'][:100]}...")

        print(f"\nTotal leading-zero suspicious: {len(leading_zero)}")
        print(f"Total section-context suspicious: {len(all_findings) - len(leading_zero)}")
    else:
        print("\nNo suspicious digit runs found — _DIGIT_RUN appears safe for non-year numbers.")

    # Save full report
    report_path = PROJECT_ROOT / "data" / "processed" / "digit_run_audit.json"
    report_path.write_text(
        json.dumps({
            "total_suspicious": len(all_findings),
            "by_subject": dict(stats),
            "leading_zero_count": len([f for f in all_findings if "leading_zero" in f["reason"]]),
            "findings": all_findings[:500],  # cap output
        }, ensure_ascii=False, indent=2),
        "utf-8",
    )
    print(f"\nFull report: {report_path}")


if __name__ == "__main__":
    main()
