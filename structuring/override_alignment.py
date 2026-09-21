"""Manual, per-question corrections of the question<->answer alignment (applied on top of the automatic
alignment by align_questions_semantic.py). Stored in data/structured/alignment_overrides.json:
  { "<qid>": {"block": <index into blocks_of(solution)> | null, "note": "...", "by": "human review 2026-09-21"} }
usage:
  override_alignment.py show <unit_id>            # list the answer blocks (with index) and the questions of a unit
  override_alignment.py set <qid> <block|none> "<note>"
  override_alignment.py list
"""
import json, sys, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from align_questions_semantic import blocks_of, canonicalize, OUT
OV = OUT/"alignment_overrides.json"

def load(): return json.loads(OV.read_text("utf-8")) if OV.exists() else {}
def save(d): OV.write_text(json.dumps(d, ensure_ascii=False, indent=1), "utf-8")

def unit(unit_id):
    subj = unit_id.split("_")[1]
    for l in open(OUT/f"{subj}_pairs.jsonl", encoding="utf-8"):
        p = json.loads(l)
        if p["exam"]["id"] == unit_id: return p
    raise SystemExit("unit not found")

def one(t, n=110): return re.sub(r"\s+", " ", re.sub(r"\*\*|<[^>]+>", "", t or "")).strip()[:n]

cmd = sys.argv[1]
if cmd == "show":
    p = unit(sys.argv[2]); s = p["solution"]
    print("QUESTIONS:")
    from collections import Counter
    seen = Counter()
    for it in canonicalize(p["exam"]["items"]):
        seen[it["label"]] += 1; tag = f"q{it['label']}" + (f"#{seen[it['label']]}" if seen[it["label"]] > 1 else "")
        print(f"  {tag}: {one(it['text'])}")
    print("BLOCKS:")
    for k, b in enumerate(canonicalize(blocks_of(s)) if s else []): print(f"  [{k}] a{b['label']}: {one(b['text'])}")
elif cmd == "set":
    qid, blk, note = sys.argv[2], sys.argv[3], sys.argv[4]
    block = None if blk == "none" else ([int(x) for x in blk.split(",")] if "," in blk else int(blk))
    d = load(); d[qid] = {"block": block, "note": note, "by": "human review 2026-09-21"}; save(d)
    print("saved", qid, d[qid])
elif cmd == "list":
    for k, v in load().items(): print(k, v)
