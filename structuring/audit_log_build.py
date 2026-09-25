"""Rebuild data/structured/alignment_audit_log.jsonl from scratch:
  one entry per human override = automatic mapping ({subj}_questions_auto.jsonl, produced with NO_OVERRIDES=1)
  -> human mapping ({subj}_questions.jsonl), with evidence (answer text) and the reviewer's reason.
Also reports regressions: questions whose automatic mapping changed since the previous run
(compares {subj}_questions_auto.jsonl with {subj}_questions_auto.prev.jsonl when present).
usage: audit_log_build.py [subjects...]"""
import json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from align_questions_semantic import OUT, SUBJECTS
def one(t, n=160): return re.sub(r"\s+", " ", re.sub(r"\*\*|<[^>]+>", "", t or "")).strip()[:n]
def load(p): return {q["qid"]: q for q in (json.loads(l) for l in open(p, encoding="utf-8"))} if p.exists() else {}
ov = json.loads((OUT/"alignment_overrides.json").read_text("utf-8"))
entries, regressions = [], []
for subj in (sys.argv[1:] or SUBJECTS):
    auto, final = load(OUT/f"{subj}_questions_auto.jsonl"), load(OUT/f"{subj}_questions.jsonl")
    prev = load(OUT/f"{subj}_questions_auto.prev.jsonl")
    for qid, q in final.items():
        if qid not in ov: continue
        a = auto.get(qid); o = ov[qid]
        blocks = o["block"] if isinstance(o["block"], list) else ([] if o["block"] is None else [o["block"]])
        entries.append({"exam_id": q["unit_id"], "question_id": qid, "subject": subj, "question": one(q["question"]),
                        "old_mapping": {"match": a["match"], "answer_label": a["answer_label"], "answer": one(a["answer"])} if a else None,
                        "new_mapping": {"match": q["match"], "blocks": blocks, "from_unit": o.get("from_unit")},
                        "changed": (a["answer"] != q["answer"]) if a else None,
                        "evidence": one(q["answer"], 300), "reason": o["note"], "by": o["by"]})
    for qid, a in auto.items():
        p = prev.get(qid)
        if p and (p["answer"] != a["answer"] or p["match"] != a["match"]):
            regressions.append({"subject": subj, "qid": qid, "prev": (p["match"], p["answer_label"]), "now": (a["match"], a["answer_label"]),
                                "overridden": qid in ov})
with open(OUT/"alignment_audit_log.jsonl", "w", encoding="utf-8") as fo:
    for e in entries: fo.write(json.dumps(e, ensure_ascii=False) + "\n")
print(f"audit log: {len(entries)} human decisions; changed vs automatic: {sum(1 for e in entries if e['changed'])}; "
      f"confirmations of automatic mapping: {sum(1 for e in entries if e['changed'] is False)}")
print(f"automatic-mapping regressions vs previous run: {len(regressions)} (of which covered by override: {sum(r['overridden'] for r in regressions)})")
for r in regressions:
    if not r["overridden"]: print("  ", r)
