"""Sanity checks on data/structured/{subject}_exercises.jsonl: exam points sum to 20,
solution exercise count == exam exercise count. usage: check_segmentation.py physic math svt"""
import json, sys
from collections import defaultdict
from pathlib import Path
OUT = Path(__file__).resolve().parent.parent / "data" / "structured"
for subj in sys.argv[1:] or ["physic", "math", "svt"]:
    by = defaultdict(list)
    for l in open(OUT/f"{subj}_exercises.jsonl", encoding="utf-8"):
        r = json.loads(l); by[(r["stem"], r["doc_type"])].append(r)
    exams = {s: l for (s, t), l in by.items() if t == "exam"}
    bad_pts = {s: [(r["exercise_label"], r["points"]) for r in l] for s, l in exams.items() if sum(r["points"] or 0 for r in l) != 20}
    mism = []
    for (s, t), l in sorted(by.items()):
        if t != "solution": continue
        n_ex = len(exams.get(s.replace("_solution", ""), []))
        if len(l) != n_ex: mism.append((s, len(l), n_ex, [r["exercise_label"] for r in l]))
    whole = [s for (s, t), l in by.items() if any(r.get("whole_document") for r in l)]
    print(f"== {subj}: exams={len(exams)} solutions={sum(1 for (s,t) in by if t=='solution')} exercises={sum(len(l) for l in by.values())}")
    print("  points!=20:", len(bad_pts)); [print("   ", s, v) for s, v in bad_pts.items()]
    print("  solution/exam count mismatch:", len(mism)); [print("   ", m) for m in mism]
    print("  whole-document solutions:", whole)
