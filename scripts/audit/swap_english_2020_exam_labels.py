"""Swap the mislabeled English 2020 EXAM stems (verified visually 2026-09-20):
  bac_english_2020_sujet1(.pdf) held الموضوع الثاني (Money Laundering, pages 3-4) -> becomes bac_english_2020_sujet2
  bac_english_2020_sujet2(.pdf) held الموضوع الأول (Malnutrition, pages 1-2)      -> becomes bac_english_2020_sujet1
The *_solution and *_and_sujet2* stems are correct and left untouched. usage: swap_english_2020_exam_labels.py [--dry]
"""
import json, re, sys, datetime
from pathlib import Path
P = Path("C:/Users/samsung/Desktop/bac-genius"); DRY = "--dry" in sys.argv
S = "bac_english_2020_sujet"
RX = re.compile(r"bac_english_2020_sujet([12])(?!_and)(?!_solution)(?![A-Za-z0-9])")
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
            r["relabel_note"] = "2026-09-20: file renamed; original upload had sujet1/sujet2 exam labels swapped (verified visually)"
    mp.write_text(json.dumps(m, indent=1, ensure_ascii=False), "utf-8")
    log = P/"data/raw/RELABEL_LOG.md"
    log.write_text(log.read_text("utf-8") +
        f"\n## {datetime.date.today()} English 2020 (exams only)\nbac_english_2020_sujet1.pdf held الموضوع الثاني (Money Laundering) and "
        "bac_english_2020_sujet2.pdf held الموضوع الأول (Malnutrition). The two exam stems and every reference under data/ were swapped by "
        "scripts/audit/swap_english_2020_exam_labels.py. Solutions and the _and_sujet2 duplicates were already correct and untouched.\n", "utf-8")
print("done (dry)" if DRY else "done")
