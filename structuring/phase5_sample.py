"""Phase 5: a third, larger stratified random sample (~250 items), non-overlapping with
BOTH the original 143-item audit AND the 158-item Phase 4 sample, and excluding the 55
qids just fixed by the targeted from_unit/SCORES-bracket/unresolved review (already
individually re-verified post-rerun). Proportional-with-caps per subject per match class,
covering all 7 subjects and every match class including solution_missing.
"""
import json, random, re
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent))
from align_questions_semantic import blocks_of, canonicalize, OUT

random.seed(20260925)
SUBJECTS = ["arabe", "english", "francais", "islamic", "math", "physic", "svt"]
CAP_PER_CLASS = 8
MIN_PER_SUBJECT = 25

prior1 = {json.loads(l)["question_id"] for l in open(OUT / "audit_sample_verdicts.jsonl", encoding="utf-8")}
prior2 = {json.loads(l)["question_id"] for l in open(OUT / "phase4_verdicts.jsonl", encoding="utf-8")}
ov = json.loads((OUT / "alignment_overrides.json").read_text("utf-8"))
just_fixed = {k for k, v in ov.items() if v.get("by", "").startswith("human review 2026-09-25")}
excluded = prior1 | prior2 | just_fixed
print(f"excluding {len(excluded)} previously-audited/just-fixed qids "
      f"({len(prior1)} + {len(prior2)} + {len(just_fixed)})")

def one(t, n=20000):
    return re.sub(r"[ \t]+", " ", t or "").strip()[:n]

sample_plan = []
for subj in SUBJECTS:
    qs = [json.loads(l) for l in open(OUT / f"{subj}_questions.jsonl", encoding="utf-8")]
    pairs = {p["exam"]["id"]: p for p in (json.loads(l) for l in open(OUT / f"{subj}_pairs.jsonl", encoding="utf-8"))}
    by_class = {}
    for q in qs:
        if q["match"] in ("parent_stub", "legend"):
            continue
        if q["qid"] in excluded:
            continue
        by_class.setdefault(q["match"], []).append(q)
    subj_picked = []
    for cls, items in by_class.items():
        random.shuffle(items)
        n = min(CAP_PER_CLASS, len(items))
        subj_picked.extend((subj, cls, q, pairs) for q in items[:n])
    if len(subj_picked) < MIN_PER_SUBJECT:
        leftover = []
        for cls, items in by_class.items():
            already = sum(1 for s in subj_picked if s[1] == cls)
            leftover.extend((subj, cls, q, pairs) for q in items[already:])
        random.shuffle(leftover)
        need = MIN_PER_SUBJECT - len(subj_picked)
        subj_picked.extend(leftover[:need])
    sample_plan.extend(subj_picked)

print(f"total sampled: {len(sample_plan)}")
from collections import Counter
print(Counter(s for s, c, _, _ in sample_plan))
print(Counter((s, c) for s, c, _, _ in sample_plan))

dump_path = Path(r"C:\Users\samsung\AppData\Local\Temp\claude\C--Users-samsung-Desktop-bac-genius\080f53e8-a8e9-440e-a559-c5a8bdcc0ca4\scratchpad\phase5_dump.txt")
dump_path.parent.mkdir(parents=True, exist_ok=True)
skeleton_path = OUT / "phase5_sample_qids.jsonl"

with open(dump_path, "w", encoding="utf-8") as f, open(skeleton_path, "w", encoding="utf-8") as sk:
    for subj, cls, q, pairs in sample_plan:
        unit = q["unit_id"]
        p = pairs.get(unit)
        f.write(f"\n{'='*90}\n")
        f.write(f"QID: {q['qid']}  SUBJECT: {subj}  CLASS: {cls}  LABEL: {q.get('label')}\n")
        f.write(f"--- QUESTION (raw) ---\n{one(q['question'])}\n")
        if p and p.get("solution"):
            f.write(f"--- FULL SOLUTION UNIT RAW TEXT ---\n{one(p['solution']['text'], 20000)}\n")
        else:
            f.write("--- (NO SOLUTION UNIT PAIRED) ---\n")
        f.write(f"--- CURRENT ANSWER LABEL/EXTRACT (as stored) ---\n{one(q.get('answer',''), 2500)}\n")
        sk.write(json.dumps({
            "exam_id": unit, "question_id": q["qid"], "subject": subj,
            "mapping": {"match_class": cls, "answer_label": q.get("label")},
        }, ensure_ascii=False) + "\n")

print("dump written to:", dump_path)
print("skeleton written to:", skeleton_path)
