"""Full-coverage audit: dump every remaining (not-yet-individually-verified) question
in one subject, GROUPED BY UNIT so the (long) paired solution text is shown once per
unit followed by every one of that unit's remaining questions + current stored answers.
No sampling -- every qid in the subject's remaining list is included; this is purely a
space-efficient re-layout of the same information (no content is dropped).
"""
import json, re, sys
from pathlib import Path
from collections import defaultdict
sys.path.insert(0, str(Path(__file__).parent))
from align_questions_semantic import OUT

SCRATCH = Path(r"C:\Users\samsung\AppData\Local\Temp\claude\C--Users-samsung-Desktop-bac-genius\080f53e8-a8e9-440e-a559-c5a8bdcc0ca4\scratchpad")

def one(t, n=20000):
    return re.sub(r"[ \t]+", " ", t or "").strip()[:n]

def main(subject):
    remaining = [json.loads(l) for l in open(SCRATCH / "full_audit_remaining.jsonl", encoding="utf-8") if json.loads(l)["subject"] == subject]
    qids = {r["qid"] for r in remaining}
    qs = {json.loads(l)["qid"]: json.loads(l) for l in open(OUT / f"{subject}_questions.jsonl", encoding="utf-8")}
    pairs = {json.loads(l)["exam"]["id"]: json.loads(l) for l in open(OUT / f"{subject}_pairs.jsonl", encoding="utf-8")}

    by_unit = defaultdict(list)
    for r in remaining:
        q = qs[r["qid"]]
        by_unit[q["unit_id"]].append(q)

    dump_path = SCRATCH / f"full_audit_{subject}_dump.txt"
    n_written = 0
    with open(dump_path, "w", encoding="utf-8") as f:
        for unit_id, unit_qs in by_unit.items():
            p = pairs.get(unit_id)
            f.write(f"\n{'#'*90}\nUNIT: {unit_id}\n")
            if p and p.get("solution"):
                f.write(f"=== FULL SOLUTION UNIT RAW TEXT ===\n{one(p['solution']['text'], 20000)}\n")
            else:
                f.write("=== (NO SOLUTION UNIT PAIRED) ===\n")
            for q in unit_qs:
                f.write(f"\n--- QID: {q['qid']}  CLASS: {q['match']}  LABEL: {q.get('label')} ---\n")
                f.write(f"QUESTION: {one(q['question'])}\n")
                f.write(f"STORED ANSWER: {one(q.get('answer',''), 3000)}\n")
                n_written += 1
    print(f"{subject}: {n_written} items across {len(by_unit)} units -> {dump_path}")

if __name__ == "__main__":
    main(sys.argv[1])
