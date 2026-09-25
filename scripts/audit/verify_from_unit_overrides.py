"""Exhaustive manual-verification dump for every francais from_unit override.
For each override, prints: the question, the label it needs, the block(s) the
override currently points to, the block(s) whose OWN label matches the needed
label (candidate correct answer), and the full from_unit block list once per
unique from_unit so a human can judge multi-block glued cases directly.
"""
import json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "structuring"))
from align_questions_semantic import blocks_of, canonicalize, OUT

ov = json.loads((OUT / "alignment_overrides.json").read_text("utf-8"))
targets = {k: v for k, v in ov.items() if v.get("from_unit") and k.split("_")[1] == "francais"}

qs = {}
for l in open(OUT / "francais_questions.jsonl", encoding="utf-8"):
    q = json.loads(l)
    qs[q["qid"]] = q
pairs = {p["exam"]["id"]: p for p in (json.loads(l) for l in open(OUT / "francais_pairs.jsonl", encoding="utf-8"))}

def one(t, n=100000):
    return re.sub(r"\*\*|<[^>]+>", "", t or "").strip()[:n]

out_path = Path(r"C:\Users\samsung\AppData\Local\Temp\claude\C--Users-samsung-Desktop-bac-genius\080f53e8-a8e9-440e-a559-c5a8bdcc0ca4\scratchpad\verify_francais_dump.txt")
out_path.parent.mkdir(parents=True, exist_ok=True)

unit_blocks_cache = {}
with open(out_path, "w", encoding="utf-8") as f:
    for unit in sorted({v["from_unit"] for v in targets.values()}):
        p = pairs.get(unit)
        bl = canonicalize(blocks_of(p["solution"])) if p and p["solution"] else []
        unit_blocks_cache[unit] = bl
        f.write(f"\n{'#'*100}\nFROM_UNIT: {unit}  ({len(bl)} blocks)\n{'#'*100}\n")
        for i, b in enumerate(bl):
            f.write(f"[{i}] label={b.get('label')!r}  {one(b['text'], 300)}\n")

    for qid, o in sorted(targets.items()):
        q = qs[qid]
        unit = o["from_unit"]
        bl = unit_blocks_cache[unit]
        qlabel = qid.split("__q")[1].split("#")[0]
        idxs = o["block"] if isinstance(o["block"], list) else [o["block"]]
        f.write(f"\n{'='*100}\nQID: {qid}  needs label={qlabel!r}  from_unit={unit}  current_block(s)={idxs}\n")
        f.write(f"--- QUESTION ---\n{one(q['question'])}\n")
        f.write(f"--- CURRENT MAPPED BLOCK(S) TEXT ---\n")
        for k in idxs:
            if k < len(bl):
                f.write(f"[block {k}, label={bl[k].get('label')!r}]\n{one(bl[k]['text'])}\n")
            else:
                f.write(f"[block {k}] OUT OF RANGE (only {len(bl)} blocks)\n")
        f.write(f"--- STORED ANSWER (as currently persisted) ---\n{one(q['answer'], 3000)}\n")
        cand = [i for i, b in enumerate(bl) if b.get("label") == qlabel]
        f.write(f"--- CANDIDATE BLOCK(S) WHOSE OWN LABEL == {qlabel!r}: {cand} ---\n")

print("wrote", out_path)
