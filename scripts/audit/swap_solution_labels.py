"""Swap mislabeled sujet1 <-> sujet2 SOLUTION stems for one subject/year(+session) (the exam stems are
left untouched). Mirrors swap_exam_labels.py but for the opposite case: the exam files are correctly
labeled but the solution PDFs were swapped at the source.
usage: swap_solution_labels.py <subject> <year> <session_suffix|""> "<reason>" [--dry]
  session_suffix example: "_session2" (leave "" for years without a session suffix)
"""
import json, re, sys, datetime
from pathlib import Path
P = Path("C:/Users/samsung/Desktop/bac-genius"); DRY = "--dry" in sys.argv
subject, year, session, reason = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
# matches "bac_english_2017_sujet1_solution_session2" style stems (digit BEFORE "_solution")
RX = re.compile(rf"bac_{re.escape(subject)}_{re.escape(year)}_sujet([12])_solution{re.escape(session)}(?![A-Za-z0-9])")
def swap_str(s): return RX.sub(lambda m: f"bac_{subject}_{year}_sujet{'2' if m.group(1) == '1' else '1'}_solution{session}", s)

files = [p for p in P.rglob(f"bac_{subject}_{year}_sujet*_solution{session}*") if p.is_file()]
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
    if not RX.search(s): continue
    s2 = swap_str(s)
    if s2 != s:
        touched.append(f.relative_to(P))
        if not DRY: f.write_text(s2, "utf-8")
print("files rewritten:", len(touched))
for t in touched: print("  ", t)

if not DRY:
    mp = P/"data/raw/manifest.json"; m = json.loads(mp.read_text("utf-8"))
    for r in m:
        if RX.search(r["path"]):
            r["file_size_bytes"] = (P/r["path"]).stat().st_size
            r["relabel_note"] = f"{datetime.date.today()}: file renamed; original upload had sujet1/sujet2 SOLUTION labels swapped (verified by content: topic mismatch with own exam, matches other sujet's exam topic)"
    mp.write_text(json.dumps(m, indent=1, ensure_ascii=False), "utf-8")
    log = P/"data/raw/RELABEL_LOG.md"
    log.write_text(log.read_text("utf-8") +
        f"\n## {datetime.date.today()} {subject} {year}{session} (solutions only)\n{reason} The two solution stems and every reference under data/ "
        "were swapped by scripts/audit/swap_solution_labels.py. Exams were already correctly labeled and untouched.\n", "utf-8")
print("done (dry)" if DRY else "done")
