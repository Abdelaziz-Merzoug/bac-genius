"""Print the full text of given answer blocks of a unit: show_block.py <unit_id> <k> [k ...]"""
import sys, json, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from align_questions_semantic import blocks_of, canonicalize, OUT
uid = sys.argv[1]; subj = uid.split("_")[1]
p = next(json.loads(l) for l in open(OUT/f"{subj}_pairs.jsonl", encoding="utf-8") if json.loads(l)["exam"]["id"] == uid)
b = canonicalize(blocks_of(p["solution"]))
for k in map(int, sys.argv[2:]):
    print(f"[{k}] a{b[k]['label']}:", re.sub(r"\s+", " ", b[k]["text"])[:1500]); print()
