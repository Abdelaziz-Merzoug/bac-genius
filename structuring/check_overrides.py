"""Sanity check of alignment_overrides.json after any re-segmentation: an override stores block INDICES, so if
the answer key's block list changed, the index may now point to another block. Prints every override whose
target block label differs from the question label (expected for glued/multi-block/grid answers — check the note)
and every override whose index is out of range.  usage: check_overrides.py [subject]"""
import json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from align_questions_semantic import blocks_of, canonicalize, OUT
ov = json.loads((OUT/"alignment_overrides.json").read_text("utf-8"))
pairs = {}
for subj in {k.split("_")[1] for k in ov}:
    for l in open(OUT/f"{subj}_pairs.jsonl", encoding="utf-8"):
        p = json.loads(l); pairs[p["exam"]["id"]] = p
def one(t, n=90): return re.sub(r"\s+", " ", re.sub(r"\*\*|<[^>]+>", "", t or "")).strip()[:n]
n_ok = n_warn = 0
for qid, o in ov.items():
    if len(sys.argv) > 1 and qid.split("_")[1] != sys.argv[1]: continue
    if o["block"] is None: continue
    unit = o.get("from_unit") or qid.split("__q")[0]
    qlabel = qid.split("__q")[1].split("#")[0]
    p = pairs.get(unit)
    if not p or not p["solution"]: print("MISSING UNIT/KEY", qid, unit); n_warn += 1; continue
    bl = canonicalize(blocks_of(p["solution"]))
    idxs = o["block"] if isinstance(o["block"], list) else [o["block"]]
    for k in idxs:
        if k >= len(bl): print("OUT OF RANGE", qid, k, "of", len(bl)); n_warn += 1; continue
        lab = bl[k]["label"]
        if lab == qlabel or (lab and qlabel.startswith(lab + ".")) or (lab and lab.startswith(qlabel + ".")): n_ok += 1
        else:
            n_warn += 1
            print(f"CHECK {qid} -> [{k}] a{lab}: {one(bl[k]['text'])}   | note: {o['note'][:60]}")
print(f"label-consistent: {n_ok}, to check: {n_warn}")
