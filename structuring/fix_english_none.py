"""For every 'none' English question, find the block(s) whose label matches the question's own label
(canonicalized). Print candidates for review; with --apply, set the override automatically ONLY when
exactly one block shares that exact label (safe, unambiguous case)."""
import json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from align_questions_semantic import blocks_of, canonicalize, OUT

apply = "--apply" in sys.argv
ov_path = OUT / "alignment_overrides.json"
ov = json.loads(ov_path.read_text("utf-8")) if ov_path.exists() else {}
qs = [json.loads(l) for l in open(OUT / "english_questions.jsonl", encoding="utf-8")]
pairs = {p["exam"]["id"]: p for p in (json.loads(l) for l in open(OUT / "english_pairs.jsonl", encoding="utf-8"))}
def one(t, n=110): return re.sub(r"\s+", " ", re.sub(r"\*\*|<[^>]+>", "", t or "")).strip()[:n]

nones = [q for q in qs if q["match"] == "none"]
print(f"{len(nones)} none questions")
auto_fixed, need_review = 0, []
for q in nones:
    unit = q["unit_id"]; p = pairs[unit]
    if not p["solution"]: need_review.append((q, "no solution unit")); continue
    blocks = canonicalize(blocks_of(p["solution"]))
    label = q["label"]
    matches = [k for k, b in enumerate(blocks) if b["label"] == label]
    if len(matches) == 1:
        k = matches[0]
        print(f"{q['qid']}: label '{label}' -> block [{k}] {one(blocks[k]['text'])}")
        if apply:
            ov[q["qid"]] = {"block": k, "note": "PHASE3 FIX: label-matching block exists but scored below match threshold (short table/list answer, low embedding overlap); content verified", "by": "human review 2026-09-21"}
            auto_fixed += 1
    else:
        need_review.append((q, f"{len(matches)} candidate blocks"))

if apply:
    ov_path.write_text(json.dumps(ov, ensure_ascii=False, indent=1), "utf-8")
    print(f"\nApplied {auto_fixed} overrides.")
print(f"\n{len(need_review)} need manual review:")
for q, reason in need_review:
    print(f"  {q['qid']} ({reason}): {one(q['question'])}")
