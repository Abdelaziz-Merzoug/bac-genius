"""Phase 4: draw a NEW stratified random sample of automatically-matched Q->A pairs,
non-overlapping with the qids already verified in audit_sample_verdicts.jsonl, for a
fresh measured post-fix accuracy check. Proportional-with-caps per subject per match
class, English included. Writes a full-text dump (question + complete raw answer block)
for manual verification, plus a skeleton verdicts jsonl to fill in.
"""
import json, random, re
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent))
from align_questions_semantic import blocks_of, canonicalize, OUT

random.seed(4242)
SUBJECTS = ["arabe", "english", "francais", "islamic", "math", "physic", "svt"]
CAP_PER_CLASS = 5  # max samples per (subject, match-class) cell
MIN_PER_SUBJECT = 15

prior = {json.loads(l)["question_id"] for l in open(OUT / "audit_sample_verdicts.jsonl", encoding="utf-8")}
print(f"excluding {len(prior)} previously-audited qids")

def one(t, n=4000):
    return re.sub(r"[ \t]+", " ", t or "").strip()[:n]

sample_plan = []
for subj in SUBJECTS:
    qs = [json.loads(l) for l in open(OUT / f"{subj}_questions.jsonl", encoding="utf-8")]
    pairs = {p["exam"]["id"]: p for p in (json.loads(l) for l in open(OUT / f"{subj}_pairs.jsonl", encoding="utf-8"))}
    by_class = {}
    for q in qs:
        if q["match"] in ("parent_stub", "legend"):
            continue
        if q["qid"] in prior:
            continue
        by_class.setdefault(q["match"], []).append(q)
    subj_picked = []
    for cls, items in by_class.items():
        random.shuffle(items)
        n = min(CAP_PER_CLASS, len(items))
        subj_picked.extend((subj, cls, q, pairs) for q in items[:n])
    if len(subj_picked) < MIN_PER_SUBJECT:
        # top up from largest remaining class pools
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
print(Counter((s, c) for s, c, _, _ in sample_plan))
print(Counter(s for s, c, _, _ in sample_plan))

dump_path = Path(r"C:\Users\samsung\AppData\Local\Temp\claude\C--Users-samsung-Desktop-bac-genius\080f53e8-a8e9-440e-a559-c5a8bdcc0ca4\scratchpad\phase4_dump.txt")
dump_path.parent.mkdir(parents=True, exist_ok=True)
skeleton_path = OUT / "phase4_sample_qids.jsonl"

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
        f.write(f"--- CURRENT ANSWER LABEL/EXTRACT (as stored) ---\n{one(q.get('answer',''), 2000)}\n")
        sk.write(json.dumps({
            "exam_id": unit, "question_id": q["qid"], "subject": subj,
            "mapping": {"match_class": cls, "answer_label": q.get("label")},
        }, ensure_ascii=False) + "\n")

print("dump written to:", dump_path)
print("skeleton written to:", skeleton_path)
