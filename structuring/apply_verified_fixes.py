"""Apply the 55 individually-verified fixes from the targeted review of:
  (1) all francais from_unit overrides, (2) all [SCORES...]/score-only candidates,
  (3) the 6 previously-unresolved Phase4 cases.
Each entry's block/from_unit was independently confirmed by reading the actual question
text against the actual candidate block's text (not by label-number pattern alone).
Reuses override_alignment.py's exact "set" semantics (overrides file + audit log entry).
"""
import json, sys, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from align_questions_semantic import blocks_of, canonicalize, OUT

OV = OUT / "alignment_overrides.json"
BY = "human review 2026-09-25 (targeted from_unit/SCORES-bracket/unresolved audit)"

def one(t, n=160):
    return re.sub(r"\s+", " ", re.sub(r"\*\*|<[^>]+>", "", t or "")).strip()[:n]

def unit(unit_id):
    subj = unit_id.split("_")[1]
    for l in open(OUT / f"{subj}_pairs.jsonl", encoding="utf-8"):
        p = json.loads(l)
        if p["exam"]["id"] == unit_id:
            return p
    raise SystemExit(f"unit not found: {unit_id}")

# (qid, block_or_list, note, from_unit_or_None)
FIXES = []

# --- Group 1: francais from_unit block-index corrections (verified by reading each
# question against the actual candidate block content, not by label arithmetic alone) ---
def seq(prefix, from_unit, mapping):
    for q, b in mapping.items():
        FIXES.append((f"{prefix}__q{q}", b,
                       "Targeted audit: from_unit block was systematically mis-indexed after a "
                       "later re-segmentation shifted block numbers; verified correct block by "
                       "matching actual question content (not label) against actual block content.",
                       from_unit))

seq("bac_francais_2010_sujet2__s2", "bac_francais_2010_sujet1__s2",
    {1:10,2:11,3:12,4:13,5:14,6:15,7:16,8:17,9:18,10:19})
seq("bac_francais_2011_sujet2__s2", "bac_francais_2011_sujet1__s2",
    {1:11,2:12,3:13,4:14,5:15,6:16,7:17,8:18,9:19})
seq("bac_francais_2012_sujet2__s2", "bac_francais_2012_sujet1__s2",
    {9:18,10:19})
seq("bac_francais_2013_sujet2__s2", "bac_francais_2013_sujet1__s2",
    {1:11,2:12,3:13,4:14,5:15,6:16,7:17,8:18,9:19,10:20})
seq("bac_francais_2014_sujet2__s2", "bac_francais_2014_sujet1__s2",
    {1:11,2:12,3:13,4:14,5:15,6:16,7:17,8:18,9:19,10:20})

FIXES.append(("bac_francais_2021_sujet1__s3__q1", [5,6,7],
    "Targeted audit: override pointed at unrelated comprehension items (labels 1/4/5) from the "
    "same from_unit instead of the actual compte-rendu grading grid (labels 1/2/3 with "
    "'accroche-condensation' structure, matching the compte-rendu prompt).",
    "bac_francais_2021_sujet2__s3"))
FIXES.append(("bac_francais_2021_sujet1__s3__q2", [8,9,10],
    "Targeted audit: override pointed at a mix of an unrelated comprehension item and the "
    "compte-rendu grid instead of the actual essay grid (labels 1/2/3 with "
    "'Introduction-developpement-conclusion' structure, matching the argumentative-essay prompt).",
    "bac_francais_2021_sujet2__s3"))

# --- Group 2: score-only / OCR-bracket bugs (same unit, verified against full block text) ---
FIXES.append(("bac_arabe_2024_sujet2__s3__q2", 2,
    "Targeted audit: stored answer was only a '[SCORES...]'-derived score fragment; real content "
    "(i'rab of 'محمد'/'عاطفة' etc.) found at block 2 of the same unit.", None))
FIXES.append(("bac_english_2012_sujet1__s2__q5", 3,
    "Targeted audit: stored answer was only a score/topic-heading fragment; real reordering "
    "answer '1.c 2.b 3.d 4.a' found at block 3 of the same unit.", None))
FIXES.append(("bac_islamic_2011_sujet1__s1__q5", [9,10,11,12,13,14],
    "Targeted audit: stored answer was only the heading+score fragment; the 3 benefits were each "
    "split into their own mis-numbered blocks (a known sub-enumeration segmentation issue) at "
    "blocks 9-14 of the same unit.", None))
FIXES.append(("bac_islamic_2014_sujet2__s1__q5", [4,5,6,7,8,9,10,11],
    "Targeted audit: stored answer was only the heading+grading-note fragment; the 7 benefits were "
    "each split into their own mis-numbered blocks (same sub-enumeration issue) at blocks 4-11 of "
    "the same unit.", None))
FIXES.append(("bac_islamic_2015_sujet2__s2__q3", [19,20,21,22,23,24,25,26,27],
    "Targeted audit: stored answer was only a score fragment; the 8 duties were each split into "
    "their own mis-numbered blocks (same sub-enumeration issue) at blocks 19-27 of the same unit.",
    None))
FIXES.append(("bac_physic_2024_sujet2__ex3__q6.4", 17,
    "Targeted audit: stored answer was only the trailing '[SCORES...]' fragment; real conclusion "
    "'تزداد قيمة tau_f عند استخدام مزيج غير متكافئ...' found at block 17 of the same unit.", None))
FIXES.append(("bac_svt_2008_sujet2__ex3__q3#2", 8,
    "Targeted audit: stored answer was only a score fragment; real diagram-task content "
    "('انجاز رسم تخطيطي لمعقد مناعي صلب') found at block 8 of the same unit.", None))
FIXES.append(("bac_svt_2010_sujet1__ex2__q3", 5,
    "Targeted audit: stored answer was only a score fragment; real conclusion about CO2 fixation "
    "found at block 5 of the same unit.", None))
# incidentally confirmed while re-checking the unit above (same truncation-bug class from Phase4)
FIXES.append(("bac_svt_2010_sujet1__ex2__q1", [0,1,2,3],
    "Targeted audit (found while re-checking the unit for q3): stored answer stopped right after "
    "the heading 'ب- كتابة البيانات من 1 الى 10' without the actual 10-item list, which exists "
    "split across blocks 1-3 of the same unit (sub-enumeration issue) alongside block 0's "
    "figure-identification content.", None))

# --- Group 3: previously-unresolved cases, now resolved with recoverable content ---
FIXES.append(("bac_physic_2011_sujet1__ex5__q1", 0,
    "Targeted audit of Phase4 'unresolved': block 0 (unlabeled, since it is the unit's first block "
    "with no numeric marker before it) contains the full protocol for preparing solution S, "
    "directly answering the question.", None))
FIXES.append(("bac_svt_2025_sujet1__ex2__q8", 4,
    "Targeted audit of Phase4 'unresolved': block 4 contains a leading score fragment followed by "
    "the real answer describing figure (c)/pyrenoid membrane permeability, directly answering the "
    "question.", None))
FIXES.append(("bac_svt_2025_sujet1__ex3__q10", 6,
    "Targeted audit of Phase4 'unresolved': block 6 contains the 'health advice' content (q2's own "
    "answer) followed by the real answer -- 'الجزء الثالث: مخطط...' flowchart -- directly "
    "answering this question.", None))

print(f"{len(FIXES)} fixes to apply")

overrides = json.loads(OV.read_text("utf-8")) if OV.exists() else {}
audit_entries = []

# cache current questions per subject for audit-log "old_mapping"
qcache = {}
def cur_question(qid):
    subj = qid.split("_")[1]
    if subj not in qcache:
        qcache[subj] = {json.loads(l)["qid"]: json.loads(l) for l in open(OUT / f"{subj}_questions.jsonl", encoding="utf-8")}
    return qcache[subj].get(qid)

applied = 0
for qid, block, note, from_unit in FIXES:
    old = overrides.get(qid)
    entry = {"block": block, "note": note, "by": BY}
    if from_unit:
        entry["from_unit"] = from_unit
    overrides[qid] = entry

    cur = cur_question(qid)
    src_unit = from_unit or qid.split("__q")[0]
    new_blocks = block if isinstance(block, list) else [block]
    try:
        bl = canonicalize(blocks_of(unit(src_unit)["solution"]))
        evidence = [one(bl[i]["text"]) for i in new_blocks]
    except Exception as e:
        evidence = [f"<error resolving block text: {e}>"]
    audit_entries.append({
        "exam_id": qid.split("__q")[0],
        "question_id": qid,
        "question": one(cur["question"]) if cur else None,
        "old_mapping": {"match": cur["match"], "answer_label": cur["answer_label"], "answer": one(cur["answer"])} if cur else None,
        "previous_override": old,
        "new_mapping": {"match": "human", "blocks": new_blocks, "from_unit": from_unit},
        "evidence": evidence, "reason": note, "by": BY,
    })
    applied += 1

OV.write_text(json.dumps(overrides, ensure_ascii=False, indent=1), "utf-8")
with open(OUT / "alignment_audit_log.jsonl", "a", encoding="utf-8") as fo:
    for e in audit_entries:
        fo.write(json.dumps(e, ensure_ascii=False) + "\n")

print(f"applied {applied} overrides, logged {len(audit_entries)} audit entries")
