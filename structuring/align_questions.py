"""Stage 1c — align numbered questions with numbered answers inside each exam/solution pair.

For every pair in {subject}_pairs.jsonl, exam.items (label 1..N) are matched to solution.items by label.
Numbering may restart inside a unit (sub-parts I/II, or the answer key lumps several sections):
items are grouped into monotonic "runs" and exam run k is matched to the solution run with the best
label overlap that has not been used yet (in order).
Output: data/structured/{subject}_questions.jsonl — one record per exam question:
  {qid, subject, year, session, sujet, unit_id, unit_label, points(unit), label, question, answer|null,
   match: exact|none, solution_match(unit level)}
and alignment stats into dataset_summary.json.
usage: align_questions.py [subjects...]"""
import json, sys
from collections import Counter
from pathlib import Path
OUT = Path("C:/Users/samsung/Desktop/bac-genius/data/structured")
SUBJECTS = ["physic", "math", "svt", "arabe", "islamic", "francais", "english"]

def runs(items):
    """Split items into monotonic numbering runs: [[{label,text},...], ...]."""
    out, cur, prev = [], [], 0
    for it in items:
        n = int(it["label"])
        if n <= prev and cur: out.append(cur); cur = []
        cur.append(it); prev = n
    if cur: out.append(cur)
    return out

def align(exam_items, sol_items):
    er, sr = runs(exam_items), runs(sol_items)
    used, result = set(), []
    for run in er:
        labels = {i["label"] for i in run}
        best, best_ov = None, 0
        for j, s in enumerate(sr):
            if j in used: continue
            ov = len(labels & {i["label"] for i in s})
            if ov > best_ov: best, best_ov = j, ov
        smap = {i["label"]: i["text"] for i in sr[best]} if best is not None else {}
        if best is not None: used.add(best)
        for i in run: result.append((i, smap.get(i["label"])))
    return result

summary = json.loads((OUT/"dataset_summary.json").read_text("utf-8"))
for subj in sys.argv[1:] or SUBJECTS:
    stats = Counter(); n_units = 0
    with open(OUT/f"{subj}_questions.jsonl", "w", encoding="utf-8") as fo:
        for l in open(OUT/f"{subj}_pairs.jsonl", encoding="utf-8"):
            p = json.loads(l); e, s = p["exam"], p["solution"]
            if p.get("solution_match") == "none_expected": continue
            n_units += 1
            if not e["items"]: stats["units_without_numbered_questions"] += 1; continue
            pairs = align(e["items"], s["items"] if s else [])
            unit_label = e.get("exercise_label") or e.get("section_label")
            for it, ans in pairs:
                stats["questions"] += 1; stats["answered" if ans else "unanswered"] += 1
                fo.write(json.dumps({"qid": f"{e['id']}__q{it['label']}", "subject": subj, "year": e["year"], "session": e["session"],
                                     "sujet": e["sujet"], "unit_id": e["id"], "unit_label": unit_label, "points": e["points"],
                                     "label": it["label"], "question": it["text"], "answer": ans,
                                     "match": "exact" if ans else "none", "solution_match": p["solution_match"]}, ensure_ascii=False) + "\n")
    st = {"units": n_units, **stats, "answered_pct": round(100 * stats["answered"] / max(stats["questions"], 1), 1)}
    summary[subj]["question_alignment"] = st
    print(subj, json.dumps(st, ensure_ascii=False))
(OUT/"dataset_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), "utf-8")
