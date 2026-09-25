"""Append records to the final full-coverage audit trail.
Reads a JSON list on stdin: [{"qid":..., "status": "correct"|"fixed"|"unresolved"|"still_incorrect",
"reason": "..."}, ...]  status meanings:
  correct        -- checked against the source; stored answer is the right answer, unchanged
  fixed          -- was wrong; an individually-verified override now points at the right block(s)
  unresolved     -- genuinely cannot be answered from the corpus (answer key absent/truncated at source)
  still_incorrect-- known wrong, no correct content available to point at
"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from align_questions_semantic import OUT
TRAIL = OUT / "final_audit_trail.jsonl"
recs = json.load(sys.stdin)
ok = {"correct", "fixed", "unresolved", "still_incorrect"}
with open(TRAIL, "a", encoding="utf-8") as f:
    for r in recs:
        assert r["status"] in ok, r
        assert len(r.get("reason", "")) > 20, f"{r['qid']}: needs a reason"
        f.write(json.dumps({"qid": r["qid"], "subject": r["qid"].split("_")[1],
                            "status": r["status"], "reason": r["reason"],
                            "phase": r.get("phase", "full-coverage-2026-09-25")}, ensure_ascii=False) + "\n")
n = sum(1 for _ in open(TRAIL, encoding="utf-8"))
print(f"appended {len(recs)}; trail now {n} records")
