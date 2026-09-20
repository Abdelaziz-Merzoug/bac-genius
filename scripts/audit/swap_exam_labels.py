"""Swap mislabeled sujet1 <-> sujet2 EXAM stems for one subject/year (the *_solution and
*_and_sujet2* stems are left untouched). Generalises swap_english_2020_exam_labels.py.
Renames every file whose name starts with the two stems and rewrites every reference under data/.
usage: swap_exam_labels.py <subject> <year> "<reason>" [--dry]
"""
import json, re, sys, datetime
from pathlib import Path
P = Path("C:/Users/samsung/Desktop/bac-genius"); DRY = "--dry" in sys.argv
subject, year, reason = sys.argv[1], sys.argv[2], sys.argv[3]
S = f"bac_{subject}_{year}_sujet"
RX = re.compile(re.escape(S) + r"([12])(?!_and)(?!_solution)(?![A-Za-z0-9])")
def swap_str(s): return RX.sub(lambda m: f"{S}{'2' if m.group(1) == '1' else '1'}", s)

files = [p for p in P.rglob(f"{S}*") if p.is_file() and "_and_" not in p.name and "_solution" not in p.name]
plan = [(p, p.with_name(swap_str(p.name))) for p in files]
plan = [(a, b) for a, b in plan if a != b]
print("files to rename:", len(plan))
for a, b in plan: print("  ", a.relative_to(P), "->", b.name)
if not DRY:
    tmp = [(a, a.with_name(a.name + ".__swap__")) for a, _ in plan]
    for a, t in tmp: a.rename(t)
    for (a, b), (_, t) in zip(plan, tmp): t.rename(b)

touched = []
for f in P.joinpath("data").rglob("*"):
    if not f.is_file() or f.suffix.lower() not in (".json", ".txt", ".md", ".jsonl", ".csv"): continue
    if f.name == "manifest.json" and f.parent.name == "raw": continue
    try: s = f.read_text("utf-8")
    except UnicodeDecodeError: continue
    if S not in s: continue
    s2 = swap_str(s)
    if s2 != s:
        touched.append(f.relative_to(P))
        if not DRY: f.write_text(s2, "utf-8")
print("files rewritten:", len(touched))
for t in touched: print("  ", t)

if not DRY:
    mp = P/"data/raw/manifest.json"; m = json.loads(mp.read_text("utf-8"))
    for r in m:
        if S in r["path"] and "_and_" not in r["path"] and "_solution" not in r["path"]:
            r["file_size_bytes"] = (P/r["path"]).stat().st_size
            r["relabel_note"] = f"{datetime.date.today()}: file renamed; original upload had sujet1/sujet2 exam labels swapped (verified visually)"
    mp.write_text(json.dumps(m, indent=1, ensure_ascii=False), "utf-8")
    log = P/"data/raw/RELABEL_LOG.md"
    log.write_text(log.read_text("utf-8") +
        f"\n## {datetime.date.today()} {subject} {year} (exams only)\n{reason} The two exam stems and every reference under data/ "
        "were swapped by scripts/audit/swap_exam_labels.py. Solutions and the _and_sujet2 duplicates were already correct and untouched.\n", "utf-8")
print("done (dry)" if DRY else "done")
