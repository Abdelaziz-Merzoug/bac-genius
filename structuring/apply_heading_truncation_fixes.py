"""Targeted fix pass for the 'heading-only truncation' bug pattern discovered during
Phase 5 audit: stored answers that are just a section heading (or a partial capture)
while the real list/content sits immediately after in the same solution block but was
never captured by the alignment pipeline. Also includes a handful of related bugs
found while systematically searching for this pattern (wrong-item mappings, a
misclassified solution_missing case, and 3 previously-Phase5-confirmed-but-unfixed bugs).

Every block index below was independently verified by reading the actual question text
against the actual block content (not by label-number pattern alone), following the
same methodology as the prior targeted review (see apply_verified_fixes.py).
"""
import json, sys, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from align_questions_semantic import blocks_of, canonicalize, OUT

OV = OUT / "alignment_overrides.json"
BY = "human review 2026-09-25b (heading-only-truncation systematic sweep)"

def one(t, n=160):
    return re.sub(r"\s+", " ", re.sub(r"\*\*|<[^>]+>", "", t or "")).strip()[:n]

def unit(unit_id):
    subj = unit_id.split("_")[1]
    for l in open(OUT / f"{subj}_pairs.jsonl", encoding="utf-8"):
        p = json.loads(l)
        if p["exam"]["id"] == unit_id:
            return p
    raise SystemExit(f"unit not found: {unit_id}")

# (qid, block_or_list, note)
FIXES = []

def add(qid, block, note):
    FIXES.append((qid, block, note))

TRUNC = ("Targeted fix: stored answer was only the section heading (or a partial "
          "capture); the real list/content sits in the immediately-following block(s) "
          "of the same solution unit but was not captured.")

add("bac_arabe_2015_sujet2__s2__q5", [5, 6, 7, 8], TRUNC)
add("bac_english_2010_sujet2__s2__q3", [3, 4],
    "Targeted fix: question requires completing both sentence (1.b) and (2.b); "
    "stored answer only had 1.b, missing 2.b which sits in the adjacent block.")
add("bac_english_2011_sujet1__s2__q3", [3, 4],
    "Targeted fix: question requires rewriting both sentence (1.b) and (2.b); "
    "stored answer only had 1.b, missing 2.b which sits in the adjacent block.")
add("bac_english_2017_sujet1_session1__s2__q2", [1],
    "Targeted fix: question asks to complete the verb/noun/adjective chart (item 2); "
    "stored answer instead held an unrelated later item (3.2's sentence completion). "
    "The chart itself is glued into the same block as item 1.")
add("bac_english_2017_sujet1_session2__s2__q3", [3, 4],
    "Targeted fix: question requires rewriting both sentence (1.B) and (2.B); "
    "stored answer only had 1.B, missing 2.B which sits in the adjacent block.")
add("bac_english_2018_sujet2__s2__q3", [4, 5],
    "Targeted fix: question requires transforming both sentence (1.B) and (2.B); "
    "stored answer only had 1.B, missing 2.B which sits in the adjacent block.")
add("bac_english_2022_sujet1__s2__q4", [7, 8, 9, 10],
    "Targeted fix: question asks to reorder all 4 given sentences; stored answer only "
    "captured the 4th (last) sentence, missing sentences 1-3 which are each their own "
    "adjacent block (sub-enumeration segmentation issue).")
add("bac_english_2023_sujet1__s2__q4", [4, 5], TRUNC)
add("bac_english_2023_sujet2__s2__q4", [4, 5], TRUNC)
add("bac_english_2024_sujet1__s2__q3", [3, 4, 5], TRUNC)
add("bac_islamic_2009_sujet1__s1__q3", [2, 3, 4], TRUNC)
add("bac_islamic_2011_sujet2__s1__q4",
    [12, 13, 14],
    "Targeted fix: question asks to mention 2 Quranic values and classify them (labeled "
    "'3/' in the source's own numbering, one off from the question's own '4/' label); "
    "stored answer instead held the unrelated '4/ استخراج أربع فوائد' item due to this "
    "label mismatch.")
add("bac_islamic_2013_sujet2__s1__q3", [2, 3, 4, 5], TRUNC)
add("bac_islamic_2013_sujet2__s1__q4", [12, 13, 14, 15, 16, 17], TRUNC)
add("bac_islamic_2013_sujet2__s1__q5", [18, 19, 20, 21, 22, 23, 24], TRUNC)
add("bac_islamic_2013_sujet2__s1__q6", [25, 26, 27, 28, 29, 30, 31, 32], TRUNC)
add("bac_islamic_2013_sujet2__s2__q4", [3, 4, 5, 6, 7], TRUNC)
add("bac_islamic_2015_sujet2__s2__q1", [11],
    "Targeted fix: question asks for both the concept of work (part أ) and Islam's view "
    "of it (part ب); stored answer only had one bullet from part ب's list; block 11 "
    "contains part أ's full definition plus part ب's heading (glued block).")
add("bac_islamic_2017_sujet1_session1__s1__q1", [0, 1, 2, 3, 4, 5], TRUNC)
add("bac_islamic_2017_sujet1_session1__s1__q3", [6, 7, 8, 9, 10, 11, 12, 13, 14], TRUNC)
add("bac_islamic_2018_sujet1__s2__q1", [0],
    "Targeted fix: stored answer was a trailing 'ملاحظة' (note) line instead of the "
    "actual content; block 0 holds the real answer (meaning of responsibility + its "
    "effect on family harmony).")
add("bac_physic_2014_sujet1__ex4__q2", [2],
    "Targeted fix: stored answer was only the heading restating the graph equation; "
    "the actual computed values (v0=3.16 m/s, f=1.2N) sit in the same block but were "
    "not captured.")
add("bac_svt_2008_sujet1__ex3__q3", [3], TRUNC)
add("bac_svt_2014_sujet1__ex2__q1", [1, 2, 3, 4, 5, 6], TRUNC)
add("bac_svt_2014_sujet1__ex3__q1", [1, 2, 3, 4],
    "Targeted fix: stored answer only had the molecule name (antibody), missing all 8 "
    "numbered labels which sit in the following blocks (sub-enumeration segmentation).")
add("bac_svt_2019_sujet1__ex1__q1", [1], TRUNC)
add("bac_svt_2019_sujet2__ex1__q1", [0, 1, 2, 3, 4, 5, 6, 7, 8], TRUNC)

# --- Phase 5 audit findings, confirmed incorrect but not yet fixed ---
add("bac_islamic_2010_sujet2__s1__q4", [11, 12, 13, 14, 15, 16, 17], TRUNC)
add("bac_islamic_2015_sujet2__s1__q5", [6, 7, 8, 9, 10], TRUNC)
add("bac_francais_2009_sujet2__s2__q6", [5],
    "Phase 5 finding: misclassified as solution_missing; the matching content ('.6.Elles "
    "font l'objet de beaucoup...si bien que...') is glued into the same block already "
    "used for item 5's answer.")
add("bac_svt_2019_sujet1__ex3__q2#2", [2],
    "Phase 5 finding: misclassified as solution_missing; block 2 (Part II, item 1) "
    "directly explains the immune-escape mechanism this question asks about using "
    "medium (a)/(b) results.")
add("bac_svt_2019_sujet1__ex3__q1#2", [3],
    "Phase 5 finding: misclassified as solution_missing; block 3 (Part II, item 2) "
    "directly discusses the two treatment methods (IL2, TIL) this question describes.")
add("bac_svt_2020_sujet1__ex1__q1",
    list(range(0, 20)),
    "Phase 5 finding: stored answer was only the heading with no table content; the "
    "full 10-row table (numbered labels, physical states, rock types, discontinuity "
    "names) spans blocks 0-19 of the same item.")
add("bac_svt_2025_sujet1__ex3__q1", [1, 2, 3, 4, 5],
    "Phase 5 finding: stored answer was cut off mid-description of fig(b)'s mechanism "
    "(missing the 'in the presence of Mtb' continuation and the final 'الربط' section "
    "that explicitly confirms hypothesis 1, which is the actual verification the "
    "question asks for); extending to block 5 captures the full mechanism and "
    "confirmation.")

print(f"{len(FIXES)} fixes to apply")

overrides = json.loads(OV.read_text("utf-8")) if OV.exists() else {}
audit_entries = []

qcache = {}
def cur_question(qid):
    subj = qid.split("_")[1]
    if subj not in qcache:
        qcache[subj] = {json.loads(l)["qid"]: json.loads(l) for l in open(OUT / f"{subj}_questions.jsonl", encoding="utf-8")}
    return qcache[subj].get(qid)

applied = 0
for qid, block, note in FIXES:
    old = overrides.get(qid)
    entry = {"block": block, "note": note, "by": BY}
    overrides[qid] = entry

    cur = cur_question(qid)
    src_unit = qid.split("__q")[0]
    new_blocks = block if isinstance(block, list) else [block]
    try:
        bl = canonicalize(blocks_of(unit(src_unit)["solution"]))
        evidence = [one(bl[i]["text"]) for i in new_blocks]
    except Exception as e:
        evidence = [f"<error resolving block text: {e}>"]
    audit_entries.append({
        "exam_id": src_unit,
        "question_id": qid,
        "question": one(cur["question"]) if cur else None,
        "old_mapping": {"match": cur["match"], "answer_label": cur["answer_label"], "answer": one(cur["answer"])} if cur else None,
        "previous_override": old,
        "new_mapping": {"match": "human", "blocks": new_blocks},
        "evidence": evidence, "reason": note, "by": BY,
    })
    applied += 1

OV.write_text(json.dumps(overrides, ensure_ascii=False, indent=1), "utf-8")
with open(OUT / "alignment_audit_log.jsonl", "a", encoding="utf-8") as fo:
    for e in audit_entries:
        fo.write(json.dumps(e, ensure_ascii=False) + "\n")

print(f"applied {applied} overrides, logged {len(audit_entries)} audit entries")
