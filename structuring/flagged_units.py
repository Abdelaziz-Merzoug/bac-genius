"""Print, for every unit of a subject that has at least one flagged pair (none / contra / label_supported /
shared block), the questions (with their exact qid tags and current answer block index) and all answer blocks,
so a human can decide each pair and record it with override_alignment.py set.
usage: flagged_units.py <subject> [start] [count]"""
import json, re, sys
from collections import defaultdict, Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from align_questions_semantic import blocks_of, canonicalize, OUT
subj = sys.argv[1]; start = int(sys.argv[2]) if len(sys.argv) > 2 else 0; count = int(sys.argv[3]) if len(sys.argv) > 3 else 15
qs = defaultdict(list)
for l in open(OUT/f"{subj}_questions.jsonl", encoding="utf-8"):
    q = json.loads(l); qs[q["unit_id"]].append(q)
pairs = {p["exam"]["id"]: p for p in (json.loads(l) for l in open(OUT/f"{subj}_pairs.jsonl", encoding="utf-8"))}
def one(t, n=100): return re.sub(r"\s+", " ", re.sub(r"\*\*|<[^>]+>", "", t or "")).strip()[:n]
flagged = []
for uid, ql in qs.items():
    seen = Counter(q["answer"][:60] for q in ql if q["answer"])
    if any(q["match"] in ("none", "label_supported") or (q["evidence"] and q["evidence"].get("label_agree") == 0)
           or (q["answer"] and seen[q["answer"][:60]] > 1) for q in ql):
        flagged.append(uid)
print(f"flagged units: {len(flagged)} (showing {start}..{start+count})")
for uid in flagged[start:start + count]:
    p = pairs[uid]; blocks = canonicalize(blocks_of(p["solution"])) if p["solution"] else []
    btext = {b["text"]: k for k, b in enumerate(blocks)}
    print(f"\n##### {uid}")
    for q in qs[uid]:
        tag = q["qid"].split("__")[-1]
        cur = "-" if not q["answer"] else str(btext.get(q["answer"], "?"))
        print(f"  {tag} [{q['match']}] -> blk {cur} | {one(q['question'])}")
    for k, b in enumerate(blocks): print(f"    [{k}] a{b['label']}: {one(b['text'])}")
