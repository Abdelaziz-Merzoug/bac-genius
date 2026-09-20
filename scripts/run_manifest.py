"""Entry point: build the raw-data manifest.

Usage (from project root):
    python -m scripts.run_manifest
    python scripts/run_manifest.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure project root is on sys.path so config/ingestion packages resolve.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ingestion.build_manifest import (
    build_manifest,
    print_coverage_table,
    print_pdf_validation_report,
)

MANIFEST_PATH = ROOT / "data" / "raw" / "manifest.json"


def main() -> None:
    print("═" * 60)
    print("  bac-genius — manifest builder")
    print("═" * 60)
    print(f"  Project root : {ROOT}")
    print(f"  Output       : {MANIFEST_PATH}")
    print()

    records = build_manifest(ROOT)

    # ── Write manifest ─────────────────────────────────────────────────────
    MANIFEST_PATH.write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"✅  Wrote {len(records)} records → {MANIFEST_PATH.relative_to(ROOT)}")

    # ── Summary counts ─────────────────────────────────────────────────────
    exams     = sum(1 for r in records if r["type"] == "exam"      and not r["duplicate"])
    solutions = sum(1 for r in records if r["type"] == "solution"  and not r["duplicate"])
    combined  = sum(1 for r in records if r["duplicate"])
    progs     = sum(1 for r in records if r["type"] == "programme")
    thresholds= sum(1 for r in records if r["type"] == "threshold")

    print()
    print("  Record breakdown:")
    print(f"    Exam papers (individual)  : {exams}")
    print(f"    Solutions   (individual)  : {solutions}")
    print(f"    Combined duplicates       : {combined}  (family C — excluded from analysis)")
    print(f"    Programme / curriculum    : {progs}")
    print(f"    Threshold documents       : {thresholds}")
    print(f"    TOTAL                     : {len(records)}")

    # ── Coverage table ─────────────────────────────────────────────────────
    print("\n" + "═" * 60)
    print("  COVERAGE TABLE")
    print("═" * 60)
    print_coverage_table(records)

    # ── PDF validation ─────────────────────────────────────────────────────
    print("═" * 60)
    print("  PDF VALIDATION")
    print("═" * 60)
    print_pdf_validation_report(records)


if __name__ == "__main__":
    main()
