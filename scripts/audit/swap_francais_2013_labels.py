"""Swap the mislabeled French 2013 stems (verified visually 2026-09-19):
  bac_francais_2013_sujet1(.pdf)          held the ANSWER KEY p1  -> becomes bac_francais_2013_sujet1_solution
  bac_francais_2013_sujet2(.pdf)          held the ANSWER KEY p2  -> becomes bac_francais_2013_sujet2_solution
  bac_francais_2013_sujet1_solution(.pdf) held the EXAM p1-2      -> becomes bac_francais_2013_sujet1
  bac_francais_2013_sujet2_solution(.pdf) held the EXAM p3-4      -> becomes bac_francais_2013_sujet2
Renames every file on disk whose name starts with one of the 4 stems and rewrites every JSON/TXT under data/
that mentions them (the *_and_sujet2* duplicate stems are left untouched). usage: swap_francais_2013_labels.py [--dry]
"""
import json, re, sys, datetime
from pathlib import Path
P = Path("C:/Users/samsung/Desktop/bac-genius"); DRY = "--dry" in sys.argv
S = "bac_francais_2013_sujet"
# token regex: stem followed by something that is NOT another stem char ("_and", "_solution" handled explicitly)
RX = re.compile(r"bac_francais_2013_sujet([12])(_solution)?(?!_and)(?![A-Za-z0-9])")
def swap_token(m):
    n, sol = m.group(1), m.group(2)
    return f"{S}{n}" if sol else f"{S}{n}_solution"
def swap_str(s): return RX.sub(swap_token, s)

# 1. rename files on disk (two-phase via temp names to avoid collisions)
files = [p for p in P.rglob(f"{S}*") if p.is_file() and "_and_" not in p.name]
plan = [(p, p.with_name(swap_str(p.name))) for p in files]
plan = [(a, b) for a, b in plan if a != b]
print("files to rename:", len(plan))
for a, b in plan: print("  ", a.relative_to(P), "->", b.name)
if not DRY:
    tmp = [(a, a.with_name(a.name + ".__swap__")) for a, _ in plan]
    for a, t in tmp: a.rename(t)
    for (a, b), (_, t) in zip(plan, tmp): t.rename(b)

# 2. rewrite references in json/txt/md files under data/
touched = []
for f in P.joinpath("data").rglob("*"):
    if not f.is_file() or f.suffix.lower() not in (".json", ".txt", ".md", ".jsonl", ".csv"): continue
    if f.name == "manifest.json" and f.parent.name == "raw": continue  # records keep name+type; file content now matches
    try: s = f.read_text("utf-8")
    except UnicodeDecodeError: continue
    if S not in s: continue
    s2 = swap_str(s)
    if s2 != s:
        touched.append(f.relative_to(P))
        if not DRY: f.write_text(s2, "utf-8")
print("files rewritten:", len(touched))
for t in touched: print("  ", t)

# 3. refresh file sizes in raw manifest (content moved under the names)
if not DRY:
    mp = P/"data/raw/manifest.json"; m = json.loads(mp.read_text("utf-8"))
    for r in m:
        if S in r["path"] and "_and_" not in r["path"]:
            r["file_size_bytes"] = (P/r["path"]).stat().st_size
            r["relabel_note"] = "2026-09-20: file renamed; original upload had exam/solution labels swapped (verified visually)"
    mp.write_text(json.dumps(m, indent=1, ensure_ascii=False), "utf-8")
    log = P/"data/raw/RELABEL_LOG.md"
    log.write_text((log.read_text("utf-8") if log.exists() else "# Relabel log\n") +
        f"\n## {datetime.date.today()} French 2013\nThe four single-subject 2013 French PDFs were uploaded with exam/solution labels swapped "
        "(sujetN.pdf held the answer key, sujetN_solution.pdf held the exam). Files and every reference under data/ were renamed by "
        "scripts/audit/swap_francais_2013_labels.py so that sujetN = exam and sujetN_solution = answer key. The _and_sujet2 duplicates were untouched.\n", "utf-8")
print("done (dry)" if DRY else "done")
