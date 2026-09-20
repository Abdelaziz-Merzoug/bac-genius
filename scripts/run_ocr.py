"""Entry point: OCR + image-extraction pipeline (P3) — all 7 subjects.

Usage (from project root)
--------------------------
    python -m scripts.run_ocr                          # all 7 subjects (default)
    python -m scripts.run_ocr --force                  # re-process everything
    python -m scripts.run_ocr --retry-failed           # re-process only q=0 files
    python -m scripts.run_ocr --subjects arabe math    # specific subjects only
    python -m scripts.run_ocr --workers 8              # override thread count (default: 4)
    python -m scripts.run_ocr --scope                  # print file scope then exit
    python scripts/run_ocr.py --help
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="OCR + image-extraction pipeline for all bac-genius PDFs.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--workers",
        type=int,
        default=4,
        metavar="N",
        help="Number of parallel worker threads.",
    )
    p.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Re-process files even if their .txt output already exists.",
    )
    p.add_argument(
        "--retry-failed",
        action="store_true",
        default=False,
        help="Re-process only files with quality_score=0 in ocr_manifest.json.",
    )
    p.add_argument(
        "--scope",
        action="store_true",
        default=False,
        help="Print the file scope (counts per subject) then exit without running.",
    )
    p.add_argument(
        "--subjects",
        nargs="+",
        metavar="SUBJECT",
        default=None,
        help="Limit processing to these subjects (e.g. --subjects arabe math). "
             "Choices: arabe english francais islamic math physic svt.",
    )
    return p.parse_args()


def _print_scope(subjects: list | None = None) -> None:
    """Show how many files will be processed per subject."""
    manifest_path = ROOT / "data" / "raw" / "manifest.json"
    if not manifest_path.exists():
        print("ERROR: data/raw/manifest.json not found — run scripts/run_manifest.py first.")
        sys.exit(1)

    sys.path.insert(0, str(ROOT))
    from config.streams import SUBJECTS_BY_CODE

    records = json.loads(manifest_path.read_text(encoding="utf-8"))
    subject_filter = set(subjects) if subjects else None

    def _in_scope(r: dict) -> bool:
        if r.get("duplicate"):
            return False
        if r.get("family") not in ("A", "B"):
            return False
        if SUBJECTS_BY_CODE.get(r.get("subject", "")) is None:
            return False
        if subject_filter and r.get("subject") not in subject_filter:
            return False
        return True

    in_scope = [r for r in records if _in_scope(r)]
    by_subj  = Counter(r["subject"] for r in in_scope)
    by_type  = Counter(r["type"]    for r in in_scope)

    subj_label = ", ".join(sorted(subject_filter)) if subject_filter else "all 7"
    parts = "  +  ".join(f"{s}({n})" for s, n in sorted(by_subj.items()))
    print(f"\nWill process {len(in_scope)} files ({subj_label} subjects):")
    print(f"  {parts}")
    print(f"\n  Exams:     {by_type.get('exam', 0)}")
    print(f"  Solutions: {by_type.get('solution', 0)}\n")


def main() -> None:
    args = _parse_args()

    if args.scope:
        _print_scope(subjects=args.subjects)
        return

    from ingestion.ocr_clean import run_ocr
    run_ocr(
        project_root=ROOT,
        workers=args.workers,
        force=args.force,
        retry_failed=args.retry_failed,
        subjects=args.subjects,
    )


if __name__ == "__main__":
    main()
