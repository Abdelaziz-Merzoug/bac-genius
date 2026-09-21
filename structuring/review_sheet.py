"""Compact per-file review sheet for the final human check of segmentation + alignment.
usage: review_sheet.py <subject> [start_index] [count] [full|compact]
Flags: CONTRA (matched against numbering), LBL (label_supported), SHARED (block reused), NONE, STUB.
compact mode: flagged pairs shown in full; clean pairs as one short line (q label -> a label, 45 chars each)."""
import json, re, sys
from collections import defaultdict
from pathlib import Path
OUT = Path("C:/Users/samsung/Desktop/bac-genius/data/structured")
subj = sys.argv[1]; start = int(sys.argv[2]) if len(sys.argv) > 2 else 0; count = int(sys.argv[3]) if len(sys.argv) > 3 else 10
mode = sys.argv[4] if len(sys.argv) > 4 else "full"
pairs = [json.loads(l) for l in open(OUT/f"{subj}_pairs.jsonl", encoding="utf-8")]
qs = defaultdict(list)
for l in open(OUT/f"{subj}_questions.jsonl", encoding="utf-8"):
    q = json.loads(l); qs[q["unit_id"]].append(q)
def one(t, n=78):
    t = re.sub(r"\*\*|__|</?u>|\$\$|<[^>]+>", "", t or ""); t = re.sub(r"\s+", " ", t).strip()
    return t[:n]
files = sorted({p["exam"]["stem"] for p in pairs}, key=lambda s: (int(re.search(r"_(\d{4})_", s).group(1)), s))
for stem in files[start:start + count]:
    ups = [p for p in pairs if p["exam"]["stem"] == stem]
    print(f"\n##### {stem}")
    for p in ups:
        e, s = p["exam"], p["solution"]
        lab = e.get("exercise_label") or e.get("section_label")
        sol = "-" if s is None else (s.get("exercise_label") or s.get("section_label") or "whole")
        print(f"  == {lab} | {e['points']}pts | p{e['pages']} | items={len(e['items'])} | sol={sol} ({p['solution_match']})")
        seen = {}
        for q in qs.get(e["id"], []):
            ev = q["evidence"] or {}
            flags = []
            if q["match"] == "none": flags.append("NONE")
            if q["match"] == "parent_stub": flags.append("STUB")
            if q["match"] == "legend": flags.append("LEGEND")
            if q["match"] == "human": flags.append("HUMAN")
            if q["match"] == "none_verified": flags.append("NONE-VERIFIED")
            if q["match"] == "label_supported": flags.append("LBL")
            if ev and ev.get("label_agree") == 0: flags.append("CONTRA")
            if q["answer"]:
                k = q["answer"][:60]
                if k in seen: flags.append(f"SHARED(q{seen[k]})")
                seen.setdefault(k, q["label"])
            f = (" [" + ",".join(flags) + "]") if flags else ""
            qtag = q["qid"].split("__")[-1]
            if mode == "compact" and not flags:
                print(f"     {qtag}: {one(q['question'], 45)}  ->  a{q['answer_label'] or '?'}: {one(q['answer'], 45)}")
                continue
            print(f"     {qtag}{f}: {one(q['question'])}")
            if q["answer"]: print(f"        -> a{q['answer_label'] or '?'}: {one(q['answer'])}")
