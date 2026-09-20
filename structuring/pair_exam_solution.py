"""Pair every exam unit with its answer-key unit.
  science  (physic/math/svt): unit = exercise, key = (stem, part, exercise_index)   <- {subject}_exercises.jsonl
  language (arabe/islamic/francais/english): unit = section, key = (stem, section_key) <- {subject}_sections.jsonl
     a "whole"-document answer key is attached to every section of its exam.
Output: data/structured/{subject}_pairs.jsonl — {pair_id, subject, year, session, sujet, unit fields, points,
        exam: {...record}, solution: {...record}|null}; data/structured/dataset_summary.json
usage: pair_exam_solution.py [subjects...]"""
import json, sys
from collections import Counter
from pathlib import Path
OUT = Path("C:/Users/samsung/Desktop/bac-genius/data/structured")
SCIENCE = ("physic", "math", "svt"); LANGUAGE = ("arabe", "islamic", "francais", "english")
summary = json.loads((OUT/"dataset_summary.json").read_text("utf-8")) if (OUT/"dataset_summary.json").exists() else {}
for subj in sys.argv[1:] or SCIENCE + LANGUAGE:
    sci = subj in SCIENCE
    recs = [json.loads(l) for l in open(OUT/f"{subj}_{'exercises' if sci else 'sections'}.jsonl", encoding="utf-8")]
    sols, by_doc = {}, {}
    for r in recs:
        if r["doc_type"] != "solution": continue
        base = r["stem"].replace("_solution", "")
        by_doc.setdefault(base, []).append(r)
        if sci: sols[(base, r["part"], r["exercise_index"])] = r
        elif not r.get("whole_document"): sols[(base, r["section_key"])] = r
    pairs, unpaired = [], []
    for r in recs:
        if r["doc_type"] != "exam": continue
        match = "unit"
        if sci:
            s = sols.pop((r["stem"], r["part"], r["exercise_index"]), None) or sols.pop((r["stem"], None, r["exercise_index"]), None) \
                or next((sols.pop(k) for k in list(sols) if k[0] == r["stem"] and k[2] == r["exercise_index"]), None)
            unit = {"part": r["part"], "exercise_index": r["exercise_index"], "exercise_label": r["exercise_label"]}
        else:
            unit = {"section_key": r["section_key"], "section_label": r["section_label"]}
            s = sols.pop((r["stem"], r["section_key"]), None)
            if s is None and r["section_key"] == "text":
                s, match = None, "none_expected"       # a reading passage has no answer
            elif s is None and by_doc.get(r["stem"]):
                # answer keys often fold the writing/production grid into the previous section, or are one block
                s, match = by_doc[r["stem"]][0], "document_fallback"
        if s is None and match != "none_expected": unpaired.append(r["id"])
        pairs.append({"pair_id": r["id"], "subject": subj, "year": r["year"], "session": r["session"], "sujet": r["sujet"],
                      **unit, "points": r["points"], "solution_match": match if s or match == "none_expected" else "none",
                      "exam": r, "solution": s})
    with open(OUT/f"{subj}_pairs.jsonl", "w", encoding="utf-8") as fo:
        for p in pairs: fo.write(json.dumps(p, ensure_ascii=False) + "\n")
    ex = [p["exam"] for p in pairs]
    summary[subj] = {
        "unit": "exercise" if sci else "section",
        "exam_files": len({p["exam"]["stem"] for p in pairs}), "exam_units": len(pairs),
        "paired_with_solution": sum(1 for p in pairs if p["solution"]), "unpaired": unpaired,
        "solution_match": dict(Counter(p["solution_match"] for p in pairs)),
        "leftover_solution_units": [v["id"] for v in sols.values()],
        "years": sorted({p["year"] for p in pairs}),
        "exercises_with_items": sum(1 for r in ex if r["items"]), "avg_items": round(sum(len(r["items"]) for r in ex) / len(ex), 2),
        "exercises_with_figure_blocks": sum(1 for r in ex if r["figures"]), "figure_blocks": sum(len(r["figures"]) for r in ex),
        "exercises_with_captions": sum(1 for r in ex if r["captions"]),
        "avg_exam_chars": round(sum(len(r["text"]) for r in ex) / len(ex)),
        "points_distribution": dict(sorted(Counter(r["points"] for r in ex).items(), key=lambda kv: (kv[0] is None, kv[0] or 0))),
    }
    print(subj, json.dumps(summary[subj], ensure_ascii=False))
(OUT/"dataset_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), "utf-8")
