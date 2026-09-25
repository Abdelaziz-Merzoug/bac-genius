"""Per-item inspection for the full-coverage audit: for each qid print the FULL question
text, the current stored answer, the current override (if any), and every answer block of
the relevant solution unit with its index -- so the correct block can be chosen by reading
the actual content rather than by label arithmetic.
usage: inspect_item.py <qid> [<qid> ...]            # blocks shown once per unit
       inspect_item.py --unit <unit_id>             # all questions + all blocks of a unit
       inspect_item.py --blocks <unit_id> [maxlen]  # just the blocks
"""
import json, sys, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from align_questions_semantic import blocks_of, canonicalize, OUT

OVF = OUT / "alignment_overrides.json"
OV = json.loads(OVF.read_text("utf-8")) if OVF.exists() else {}
_qcache, _pcache = {}, {}

def qs(subj):
    if subj not in _qcache:
        _qcache[subj] = {json.loads(l)["qid"]: json.loads(l) for l in open(OUT / f"{subj}_questions.jsonl", encoding="utf-8")}
    return _qcache[subj]

def pairs(subj):
    if subj not in _pcache:
        _pcache[subj] = {json.loads(l)["exam"]["id"]: json.loads(l) for l in open(OUT / f"{subj}_pairs.jsonl", encoding="utf-8")}
    return _pcache[subj]

def flat(t, n=600):
    return re.sub(r"[ \t]+", " ", re.sub(r"\n+", " ⏎ ", (t or "").strip()))[:n]

def show_blocks(unit_id, maxlen=340):
    subj = unit_id.split("_")[1]
    p = pairs(subj).get(unit_id)
    if not p:
        print(f"  !! unit not found: {unit_id}"); return
    if not p.get("solution"):
        print("  !! NO SOLUTION PAIRED FOR THIS UNIT"); return
    bl = canonicalize(blocks_of(p["solution"]))
    print(f"  BLOCKS OF {unit_id}  (n={len(bl)})")
    for k, b in enumerate(bl):
        print(f"   [{k:>3}] label={b['label']!r:>8} :: {flat(b['text'], maxlen)}")

def show_q(qid, with_blocks=True, seen=None):
    subj = qid.split("_")[1]
    q = qs(subj).get(qid)
    if not q:
        print(f"!! qid not found: {qid}"); return
    unit = q["unit_id"]
    print("=" * 100)
    print(f"QID {qid}   match={q['match']}  label={q.get('label')}  answer_label={q.get('answer_label')}")
    print(f"UNIT {unit}   unit_label={q.get('unit_label')!r}")
    print(f"QUESTION: {flat(q['question'], 2000)}")
    print(f"STORED ANSWER ({len(q.get('answer') or '')} chars): {flat(q.get('answer'), 6000)}")
    o = OV.get(qid)
    if o: print(f"CURRENT OVERRIDE: block={o.get('block')} from_unit={o.get('from_unit')} note={o.get('note','')[:200]}")
    if with_blocks and seen is not None:
        src = (o or {}).get("from_unit") or unit
        if src not in seen:
            seen.add(src); show_blocks(src)

if __name__ == "__main__":
    a = sys.argv[1:]
    if a[0] == "--blocks":
        show_blocks(a[1], int(a[2]) if len(a) > 2 else 340)
    elif a[0] == "--unit":
        unit_id = a[1]; subj = unit_id.split("_")[1]
        for qid, q in qs(subj).items():
            if q["unit_id"] == unit_id: show_q(qid, with_blocks=False)
        show_blocks(unit_id, int(a[2]) if len(a) > 2 else 340)
    else:
        seen = set()
        for qid in a: show_q(qid, seen=seen)
