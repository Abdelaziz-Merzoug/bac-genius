"""Re-audit of every override recorded as solution_missing (block=null): print the question and any answer block
(of the paired key, or of any other key unit of the same document) whose text carries this question's marker
(block_mentions) — a hint that the answer exists and the override is wrong.  usage: check_missing.py [subject]"""
import json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from align_questions_semantic import blocks_of, canonicalize, block_mentions, OUT
ov = json.loads((OUT/"alignment_overrides.json").read_text("utf-8"))
def one(t, n=110): return re.sub(r"\s+", " ", re.sub(r"\*\*|<[^>]+>", "", t or "")).strip()[:n]
pairs, qtext = {}, {}
for subj in {k.split("_")[1] for k in ov}:
    for l in open(OUT/f"{subj}_pairs.jsonl", encoding="utf-8"):
        p = json.loads(l); pairs[p["exam"]["id"]] = p
    for l in open(OUT/f"{subj}_questions.jsonl", encoding="utf-8"):
        q = json.loads(l); qtext[q["qid"]] = q["question"]
n = hits = 0
for qid, o in ov.items():
    if o["block"] is not None: continue
    if len(sys.argv) > 1 and sys.argv[1] != "--doc" and qid.split("_")[1] != sys.argv[1]: continue
    n += 1
    unit = qid.split("__q")[0]; label = qid.split("__q")[1].split("#")[0]; doc = unit.split("__")[0]
    found = []
    same_only = "--doc" not in sys.argv      # default: only the key paired with this very unit
    for uid, p in pairs.items():
        if not p["solution"] or (uid != unit if same_only else not uid.startswith(doc + "__")): continue
        for k, b in enumerate(canonicalize(blocks_of(p["solution"]))):
            if b["label"] == label or block_mentions(label, b["text"]): found.append((uid, k, b["label"], one(b["text"])))
    if found:
        hits += 1
        print(f"\n{qid}  Q: {one(qtext.get(qid, ''))}\n   note: {o['note'][:80]}")
        for uid, k, lab, t in found[:6]: print(f"   ? {uid.split('__')[-1]} [{k}] a{lab}: {t}")
print(f"\nsolution_missing overrides checked: {n}, with a candidate block carrying the marker: {hits}")
