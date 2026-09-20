"""Pair every exam exercise with its answer-key exercise (same stem family, part, exercise_index).
Input : data/structured/{subject}_exercises.jsonl
Output: data/structured/{subject}_pairs.jsonl  — {pair_id, subject, year, session, sujet, exercise_index,
        exercise_label, points, exam: {...record}, solution: {...record}|null}
        data/structured/dataset_summary.json
usage: pair_exam_solution.py [physic math svt]"""
import json, sys
from collections import Counter
from pathlib import Path
OUT = Path("C:/Users/samsung/Desktop/bac-genius/data/structured")
summary = {}
for subj in sys.argv[1:] or ["physic", "math", "svt"]:
    recs = [json.loads(l) for l in open(OUT/f"{subj}_exercises.jsonl", encoding="utf-8")]
    sols = {}
    for r in recs:
        if r["doc_type"] == "solution":
            sols[(r["stem"].replace("_solution", ""), r["part"], r["exercise_index"])] = r
    pairs, unpaired = [], []
    for r in recs:
        if r["doc_type"] != "exam": continue
        key = (r["stem"], r["part"], r["exercise_index"])
        s = sols.pop(key, None) or sols.pop((r["stem"], None, r["exercise_index"]), None) \
            or next((sols.pop(k) for k in list(sols) if k[0] == r["stem"] and k[2] == r["exercise_index"]), None)
        if s is None: unpaired.append(r["id"])
        pairs.append({"pair_id": r["id"], "subject": subj, "year": r["year"], "session": r["session"], "sujet": r["sujet"],
                      "part": r["part"], "exercise_index": r["exercise_index"], "exercise_label": r["exercise_label"],
                      "points": r["points"], "exam": r, "solution": s})
    with open(OUT/f"{subj}_pairs.jsonl", "w", encoding="utf-8") as fo:
        for p in pairs: fo.write(json.dumps(p, ensure_ascii=False) + "\n")
    ex = [p["exam"] for p in pairs]
    summary[subj] = {
        "exam_files": len({p["exam"]["stem"] for p in pairs}), "exam_exercises": len(pairs),
        "paired_with_solution": sum(1 for p in pairs if p["solution"]), "unpaired": unpaired,
        "leftover_solution_exercises": [v["id"] for v in sols.values()],
        "years": sorted({p["year"] for p in pairs}),
        "exercises_with_items": sum(1 for r in ex if r["items"]), "avg_items": round(sum(len(r["items"]) for r in ex) / len(ex), 2),
        "exercises_with_figure_blocks": sum(1 for r in ex if r["figures"]), "figure_blocks": sum(len(r["figures"]) for r in ex),
        "exercises_with_captions": sum(1 for r in ex if r["captions"]),
        "avg_exam_chars": round(sum(len(r["text"]) for r in ex) / len(ex)),
        "points_distribution": dict(sorted(Counter(r["points"] for r in ex).items())),
    }
    print(subj, json.dumps(summary[subj], ensure_ascii=False))
(OUT/"dataset_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), "utf-8")
