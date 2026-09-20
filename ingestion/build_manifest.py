"""ingestion/build_manifest.py

Scan data/raw/{exams,curricula,curriculum_threshold}/ and produce
data/raw/manifest.json — one JSON record per file.

Record schema
-------------
filename        : str   — bare filename
path            : str   — path relative to project root (forward slashes)
family          : A|B|C|null
                    A = individual topic exam question paper
                    B = individual topic solution / correction
                    C = combined sujet1_and_sujet2 file (duplicate=True)
                    null = non-exam file (programme / threshold)
subject         : str   — code matching config.streams.SUBJECTS_BY_CODE
year            : int|null
topic_choice    : 1|2|"both"|null
type            : exam|solution|programme|threshold
exam_regime     : early_reform|stable|covid|modern|null
censored        : bool|null
sealed          : bool|null
session         : int|null   — 1 or 2; null for non-session years
session_type    : normal|reexam|exceptional|null
duplicate       : bool  — True for family-C files (excluded from analysis)
valid_pdf       : bool|null  — magic-byte check; null for .txt files
file_size_bytes : int
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Lazy imports of sibling config modules (so this module is importable even
# when run from arbitrary cwd as long as the project root is on sys.path).
# ---------------------------------------------------------------------------
from config.streams import SUBJECTS_BY_CODE
from config.threshold_cuts import YEAR_META

# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

_PDF_MAGIC = b"%PDF"

# Arabic-Indic → ASCII digit translation table
_AR_DIGIT = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

# Typos found in source files:  raw prefix segment → canonical subject code
_PREFIX_ALIASES: Dict[str, str] = {
    "egnlish": "english",
}

# ---------------------------------------------------------------------------
# Filename regexes
# Two patterns:
#   SINGLE  — bac_{subj}_{year}_sujet{1|2}[_solution][_session{1|2}].pdf
#   COMBINED— bac_{subj}_{year}_sujet1_and_sujet2[_solution][_session{1|2}].pdf
# ---------------------------------------------------------------------------

_SINGLE_RE = re.compile(
    r"^bac_(?P<subj>[a-z]+)_(?P<year>[0-9٠-٩]{4})"
    r"_sujet(?P<n>[12])"
    r"(?:_(?P<sol>solution))?"
    r"(?:_session(?P<sess>[12]))?"
    r"\.pdf$",
    re.IGNORECASE,
)

_COMBINED_RE = re.compile(
    r"^bac_(?P<subj>[a-z]+)_(?P<year>[0-9٠-٩]{4})"
    r"_sujet1_and_sujet2"
    r"(?:_(?P<sol>solution))?"
    r"(?:_session(?P<sess>[12]))?"
    r"\.pdf$",
    re.IGNORECASE,
)

_CURRICULUM_RE = re.compile(
    r"^curriculum_(?P<subj>[a-zA-Z]+)\.(?P<ext>txt|pdf)$",
    re.IGNORECASE,
)

_THRESHOLD_RE = re.compile(
    r"^threshold_(?P<subj>[a-zA-Z]+)_(?P<year>[0-9٠-٩]{4})\.(?P<ext>txt|pdf)$",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _norm(s: str) -> str:
    """Translate Arabic-Indic digits and lower-case."""
    return s.translate(_AR_DIGIT).lower()


def _resolve_subject(raw: str) -> Optional[str]:
    code = _norm(raw)
    code = _PREFIX_ALIASES.get(code, code)
    return code if code in SUBJECTS_BY_CODE else None


def _session_type(year: int, session: Optional[int]) -> Optional[str]:
    if session is None:
        return None
    if session == 1:
        return "normal"
    # session == 2
    if year == 2016:
        return "reexam"
    if year == 2017:
        return "exceptional"
    return "normal"  # shouldn't happen but be safe


def _year_fields(year: int) -> Tuple[Optional[str], Optional[bool], Optional[bool]]:
    """Return (exam_regime, censored, sealed) from YEAR_META."""
    meta = YEAR_META.get(year)
    if meta is None:
        return None, None, None
    return meta.era, meta.censored, meta.sealed


def _check_pdf(path: Path) -> bool:
    """Return True if the file starts with the %PDF magic bytes."""
    try:
        with path.open("rb") as fh:
            return fh.read(4) == _PDF_MAGIC
    except OSError:
        return False


def _rel(path: Path, root: Path) -> str:
    """Relative path from root, always forward slashes."""
    return path.relative_to(root).as_posix()


# ---------------------------------------------------------------------------
# Per-directory scanners
# ---------------------------------------------------------------------------


def _scan_exams(exams_dir: Path, root: Path) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Scan data/raw/exams/**/*.pdf.

    Returns (records, unparsed_filenames).
    """
    records: List[Dict[str, Any]] = []
    unparsed: List[str] = []

    if not exams_dir.is_dir():
        return records, unparsed

    for pdf in sorted(exams_dir.rglob("*.pdf")):
        name = pdf.name
        size = pdf.stat().st_size
        valid = _check_pdf(pdf)

        # ── try single-topic ──────────────────────────────────────────────
        m = _SINGLE_RE.match(name)
        if m:
            subject = _resolve_subject(m.group("subj"))
            if subject is None:
                unparsed.append(str(_rel(pdf, root)))
                continue
            year = int(_norm(m.group("year")))
            topic_n = int(m.group("n"))
            is_sol = m.group("sol") is not None
            sess_raw = m.group("sess")
            session = int(sess_raw) if sess_raw else None
            regime, censored, sealed = _year_fields(year)
            records.append({
                "filename": name,
                "path": _rel(pdf, root),
                "family": "B" if is_sol else "A",
                "subject": subject,
                "year": year,
                "topic_choice": topic_n,
                "type": "solution" if is_sol else "exam",
                "exam_regime": regime,
                "censored": censored,
                "sealed": sealed,
                "session": session,
                "session_type": _session_type(year, session),
                "duplicate": False,
                "valid_pdf": valid,
                "file_size_bytes": size,
            })
            continue

        # ── try combined ──────────────────────────────────────────────────
        m = _COMBINED_RE.match(name)
        if m:
            subject = _resolve_subject(m.group("subj"))
            if subject is None:
                unparsed.append(str(_rel(pdf, root)))
                continue
            year = int(_norm(m.group("year")))
            is_sol = m.group("sol") is not None
            sess_raw = m.group("sess")
            session = int(sess_raw) if sess_raw else None
            regime, censored, sealed = _year_fields(year)
            records.append({
                "filename": name,
                "path": _rel(pdf, root),
                "family": "C",
                "subject": subject,
                "year": year,
                "topic_choice": "both",
                "type": "solution" if is_sol else "exam",
                "exam_regime": regime,
                "censored": censored,
                "sealed": sealed,
                "session": session,
                "session_type": _session_type(year, session),
                "duplicate": True,
                "valid_pdf": valid,
                "file_size_bytes": size,
            })
            continue

        # ── unrecognised ──────────────────────────────────────────────────
        unparsed.append(str(_rel(pdf, root)))

    return records, unparsed


def _scan_curricula(curricula_dir: Path, root: Path) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Scan data/raw/curricula/ — .txt and .pdf files."""
    records: List[Dict[str, Any]] = []
    unparsed: List[str] = []

    if not curricula_dir.is_dir():
        return records, unparsed

    for f in sorted(curricula_dir.iterdir()):
        if f.name.startswith("."):
            continue
        m = _CURRICULUM_RE.match(f.name)
        if not m:
            unparsed.append(str(_rel(f, root)))
            continue
        subject = _resolve_subject(m.group("subj"))
        if subject is None:
            unparsed.append(str(_rel(f, root)))
            continue
        is_pdf = m.group("ext").lower() == "pdf"
        records.append({
            "filename": f.name,
            "path": _rel(f, root),
            "family": None,
            "subject": subject,
            "year": None,
            "topic_choice": None,
            "type": "programme",
            "exam_regime": None,
            "censored": None,
            "sealed": None,
            "session": None,
            "session_type": None,
            "duplicate": False,
            "valid_pdf": _check_pdf(f) if is_pdf else None,
            "file_size_bytes": f.stat().st_size,
        })

    return records, unparsed


def _scan_thresholds(threshold_dir: Path, root: Path) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Scan data/raw/curriculum_threshold/ — optional directory."""
    records: List[Dict[str, Any]] = []
    unparsed: List[str] = []

    if not threshold_dir.is_dir():
        return records, unparsed

    for f in sorted(threshold_dir.iterdir()):
        if f.name.startswith("."):
            continue
        m = _THRESHOLD_RE.match(f.name)
        if not m:
            unparsed.append(str(_rel(f, root)))
            continue
        subject = _resolve_subject(m.group("subj"))
        if subject is None:
            unparsed.append(str(_rel(f, root)))
            continue
        year = int(_norm(m.group("year")))
        is_pdf = m.group("ext").lower() == "pdf"
        regime, censored, sealed = _year_fields(year)
        records.append({
            "filename": f.name,
            "path": _rel(f, root),
            "family": None,
            "subject": subject,
            "year": year,
            "topic_choice": None,
            "type": "threshold",
            "exam_regime": regime,
            "censored": censored,
            "sealed": sealed,
            "session": None,
            "session_type": None,
            "duplicate": False,
            "valid_pdf": _check_pdf(f) if is_pdf else None,
            "file_size_bytes": f.stat().st_size,
        })

    return records, unparsed


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------


def build_manifest(project_root: Path) -> List[Dict[str, Any]]:
    """Scan all raw-data directories and return the manifest record list.

    Does NOT write the file — the caller handles I/O so this stays testable.
    """
    raw = project_root / "data" / "raw"

    exam_records, exam_unparsed = _scan_exams(raw / "exams", project_root)
    curr_records, curr_unparsed = _scan_curricula(raw / "curricula", project_root)
    thr_records, thr_unparsed = _scan_thresholds(raw / "curriculum_threshold", project_root)

    all_records = exam_records + curr_records + thr_records
    all_unparsed = exam_unparsed + curr_unparsed + thr_unparsed

    if all_unparsed:
        print(f"\n⚠  {len(all_unparsed)} file(s) could not be parsed — check naming:")
        for p in all_unparsed:
            print(f"   {p}")

    return all_records


# ---------------------------------------------------------------------------
# Coverage table
# ---------------------------------------------------------------------------

# Column keys for a complete individual-file set (family A + B per topic)
_COLS = [
    ("topic1_exam",     1, "exam"),
    ("topic1_solution", 1, "solution"),
    ("topic2_exam",     2, "exam"),
    ("topic2_solution", 2, "solution"),
]


def print_coverage_table(records: List[Dict[str, Any]]) -> None:
    """Print per-subject coverage: which year/session slots are complete."""
    try:
        from rich.console import Console
        from rich.table import Table
        from rich import box
        console = Console()
        _rich_coverage(records, console)
    except ImportError:
        _plain_coverage(records)


def _coverage_index(records: List[Dict[str, Any]]) -> Dict:
    """Build index[(subject, year, session)] → set of (topic_choice, type)."""
    idx: Dict[Tuple, set] = {}
    for r in records:
        if r["duplicate"] or r["family"] not in ("A", "B"):
            continue
        key = (r["subject"], r["year"], r["session"])
        idx.setdefault(key, set()).add((r["topic_choice"], r["type"]))
    return idx


def _rich_coverage(records: List[Dict[str, Any]], console: Any) -> None:
    from rich.table import Table
    from rich import box

    idx = _coverage_index(records)
    subjects = sorted({r["subject"] for r in records if r["year"] is not None})

    for subj in subjects:
        table = Table(
            title=f"Coverage — {subj}",
            box=box.SIMPLE_HEAD,
            show_lines=False,
        )
        table.add_column("Year", style="bold")
        table.add_column("Sess")
        table.add_column("T1 Exam",     justify="center")
        table.add_column("T1 Solution", justify="center")
        table.add_column("T2 Exam",     justify="center")
        table.add_column("T2 Solution", justify="center")
        table.add_column("Notes",       style="dim")

        keys = sorted(
            {k for k in idx if k[0] == subj},
            key=lambda k: (k[1] or 0, k[2] or 0),
        )
        missing_rows: List[str] = []

        for key in keys:
            _, year, session = key
            present = idx[key]
            cells = []
            missing = []
            for col_label, tc, tp in _COLS:
                has = (tc, tp) in present
                cells.append("✅" if has else "❌")
                if not has:
                    missing.append(col_label)

            note = ""
            if missing:
                note = "MISSING: " + ", ".join(missing)
                missing_rows.append(f"  {year} sess={session}: {note}")

            sess_str = str(session) if session else "—"
            yr_str = str(year) if year else "?"
            table.add_row(yr_str, sess_str, *cells, note)

        console.print(table)
        if missing_rows:
            console.print(f"[red]  → Re-download needed for {subj}:[/red]")
            for m in missing_rows:
                console.print(f"[red]{m}[/red]")
        else:
            console.print(f"[green]  ✓ {subj}: all slots complete[/green]")
        console.print()


def _plain_coverage(records: List[Dict[str, Any]]) -> None:
    idx = _coverage_index(records)
    subjects = sorted({r["subject"] for r in records if r["year"] is not None})
    SEP = "-" * 72

    for subj in subjects:
        print(f"\n{SEP}")
        print(f"  {subj.upper()}")
        print(f"  {'Year':<6} {'Sess':<5} {'T1-E':<5} {'T1-S':<5} {'T2-E':<5} {'T2-S':<5}  Notes")
        print(SEP)

        keys = sorted(
            {k for k in idx if k[0] == subj},
            key=lambda k: (k[1] or 0, k[2] or 0),
        )
        missing_list: List[str] = []

        for key in keys:
            _, year, session = key
            present = idx[key]
            flags = []
            missing = []
            for col_label, tc, tp in _COLS:
                has = (tc, tp) in present
                flags.append("  ok" if has else " !!!")
                if not has:
                    missing.append(col_label)
            note = "MISSING: " + ", ".join(missing) if missing else ""
            sess_str = str(session) if session else "-"
            print(f"  {year:<6} {sess_str:<5} {''.join(flags[0]):<5} {''.join(flags[1]):<5} {''.join(flags[2]):<5} {''.join(flags[3]):<5}  {note}")
            if missing:
                missing_list.append(f"  {year} sess={session}: {note}")

        if missing_list:
            print(f"\n  !! RE-DOWNLOAD NEEDED for {subj}:")
            for m in missing_list:
                print(m)
        else:
            print(f"\n  OK — {subj}: all slots complete")


# ---------------------------------------------------------------------------
# PDF validation report
# ---------------------------------------------------------------------------


def print_pdf_validation_report(records: List[Dict[str, Any]]) -> None:
    """Report 0-byte files and files failing the %PDF magic-byte check."""
    bad: List[Dict[str, Any]] = []
    for r in records:
        if r["valid_pdf"] is None:
            continue  # .txt or unvalidated
        size = r["file_size_bytes"]
        valid = r["valid_pdf"]
        if size == 0 or not valid:
            bad.append(r)

    try:
        from rich.console import Console
        from rich.table import Table
        from rich import box
        console = Console()
        if not bad:
            console.print("[green]✅  PDF validation: all files pass %PDF magic-byte check[/green]\n")
            return
        table = Table(title="⚠  Invalid / corrupt PDFs", box=box.SIMPLE_HEAD)
        table.add_column("File")
        table.add_column("Size (B)", justify="right")
        table.add_column("Valid PDF", justify="center")
        table.add_column("Reason")
        for r in bad:
            reason = "0-byte file" if r["file_size_bytes"] == 0 else "not a PDF (magic bytes mismatch)"
            table.add_row(r["path"], str(r["file_size_bytes"]), "❌", reason)
        console.print(table)
    except ImportError:
        if not bad:
            print("\nPDF validation: all files pass.")
            return
        print(f"\n{'!'*60}")
        print(f"  INVALID / CORRUPT PDFs ({len(bad)} files):")
        for r in bad:
            reason = "0-byte" if r["file_size_bytes"] == 0 else "bad magic bytes"
            print(f"  [{reason}]  {r['path']}")
        print("!"*60)
