"""Apply individually-verified alignment fixes. Reads a JSON list on stdin:
  [{"qid": "...", "block": 3 | [3,4,5] | null, "from_unit": "..."|null, "reason": "..."}, ...]
Each entry must carry its own reason written from reading that one question against that
one unit's actual answer blocks. Same semantics as override_alignment.py "set" (overrides
file + one audit-log entry per fix), but batched so a long review can be recorded in order.
"""
import json, sys, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from align_questions_semantic import blocks_of, canonicalize, OUT

OV = OUT / "alignment_overrides.json"
BY = sys.argv[1] if len(sys.argv) > 1 else "human review 2026-09-25 (full-coverage audit)"

def one(t, n=160): return re.sub(r"\s+", " ", re.sub(r"\*\*|<[^>]+>", "", t or "")).strip()[:n]

_p = {}
def unit(uid):
    subj = uid.split("_")[1]
    if subj not in _p:
        _p[subj] = {json.loads(l)["exam"]["id"]: json.loads(l) for l in open(OUT / f"{subj}_pairs.jsonl", encoding="utf-8")}
    if uid not in _p[subj]: raise SystemExit(f"unit not found: {uid}")
    return _p[subj][uid]

_q = {}
def question(qid):
    subj = qid.split("_")[1]
    if subj not in _q:
        _q[subj] = {json.loads(l)["qid"]: json.loads(l) for l in open(OUT / f"{subj}_questions.jsonl", encoding="utf-8")}
    return _q[subj].get(qid)

fixes = json.load(sys.stdin)
d = json.loads(OV.read_text("utf-8")) if OV.exists() else {}
log = []
for fx in fixes:
    qid, block, reason = fx["qid"], fx.get("block"), fx["reason"]
    assert question(qid), f"unknown qid {qid}"
    assert reason and len(reason) > 25, f"fix for {qid} needs its own substantive reason"
    old = d.get(qid)
    d[qid] = {"block": block, "note": reason, "by": BY}
    if fx.get("from_unit"): d[qid]["from_unit"] = fx["from_unit"]
    if fx.get("lines"): d[qid]["lines"] = fx["lines"]
    if fx.get("text"):  d[qid]["text"] = fx["text"]
    cur = question(qid)
    src_unit = fx.get("from_unit") or qid.split("__q")[0]
    nb = [] if block is None else (block if isinstance(block, list) else [block])
    if fx.get("text"):
        log.append({"exam_id": qid.split("__q")[0], "question_id": qid, "question": one(cur["question"], 200),
                    "old_mapping": {"match": cur["match"], "answer_label": cur["answer_label"], "answer": one(cur["answer"], 200)},
                    "previous_override": old,
                    "new_mapping": {"match": "human", "blocks": nb, "from_unit": fx.get("from_unit"), "literal": True},
                    "evidence": [one(fx["text"], 300)], "reason": reason, "by": BY})
        continue
    try:
        bl = canonicalize(blocks_of(unit(src_unit)["solution"]))
        joined = "\n".join(bl[i]["text"] for i in nb)
        if fx.get("lines"):
            L = fx["lines"]; rows = joined.split("\n")
            rngs = L if isinstance(L[0], list) else [L]
            joined = "\n".join("\n".join(rows[a:b]) for a, b in rngs)
        evidence = [one(joined, 300)]
    except Exception as e:
        evidence = [f"<could not render: {e}>"]
    log.append({"exam_id": qid.split("__q")[0], "question_id": qid,
                "question": one(cur["question"], 200),
                "old_mapping": {"match": cur["match"], "answer_label": cur["answer_label"], "answer": one(cur["answer"], 200)},
                "previous_override": old,
                "new_mapping": {"match": "solution_missing" if block is None else "human", "blocks": nb, "from_unit": fx.get("from_unit")},
                "evidence": evidence, "reason": reason, "by": BY})

OV.write_text(json.dumps(d, ensure_ascii=False, indent=1), "utf-8")
with open(OUT / "alignment_audit_log.jsonl", "a", encoding="utf-8") as fo:
    for e in log: fo.write(json.dumps(e, ensure_ascii=False) + "\n")
print(f"applied {len(fixes)} fixes; overrides now {len(d)}")
for e in log: print("  ", e["question_id"], "->", e["new_mapping"]["blocks"], "|", e["evidence"][0][:90] if e["evidence"] else "")
