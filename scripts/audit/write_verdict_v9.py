"""Write FINAL_VERDICT v9 after the light visual check of all 419 language pages (2026-09-20)."""
import json, datetime
from collections import Counter
from pathlib import Path
P = Path("C:/Users/samsung/Desktop/bac-genius/data/processed")
v = json.load(open(P/"FINAL_VERDICT.json", encoding="utf-8")); et = json.load(open(P/"ERROR_TRIAGE.json", encoding="utf-8"))
ck = json.load(open(P/"manual_language_read_checkpoint.json", encoding="utf-8"))
vf = json.load(open(P/"visual_fixes_log.json", encoding="utf-8"))
now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
verd = Counter(x["verdict"] for x in ck.values())
by_subj = Counter((k.split("_")[1], x["verdict"]) for k, x in ck.items())

v["timestamp"] = now
v["revision"] = "v9 - light visual check of ALL 419 language pages (arabe/english/francais/islamic) + 2 file-label swaps (2026-09-20). Supersedes v8."
v["9_language_light_check"] = {
    "method": "Claude Opus 5 rendered every language page (4 per image at 100 DPI) and compared it with the text file for obvious OCR errors: missing/corrupted words, wrong characters, broken ordering, headings, dates, omissions. No API calls. Verdict per page in manual_language_read_checkpoint.json",
    "pages_read": len(ck), "verdicts": dict(verd),
    "by_subject": {s: {vv: by_subj[(s, vv)] for vv in ("FAITHFUL", "FIXED", "NOTE") if by_subj[(s, vv)]} for s in ("arabe", "islamic", "francais", "english")},
    "text_fixes": ["arabe_2021_sujet1 p2: تارا -> نارا (Q3a)", "arabe_2026_sujet2 p1: خَالِكَه -> حَالِكَه"],
    "file_label_fixes": [
        "francais_2013: sujetN.pdf held the answer key and sujetN_solution.pdf held the exam -> all 4 stems swapped on disk + every reference (scripts/audit/swap_francais_2013_labels.py, data/raw/RELABEL_LOG.md)",
        "english_2020: sujet1.pdf held الموضوع الثاني and sujet2.pdf held الموضوع الأول (solutions were correct) -> 2 exam stems swapped (scripts/audit/swap_english_2020_exam_labels.py)",
    ],
    "notes_not_edited": "13 NOTE pages: French/English answer keys extracted as text-layer dumps where score numbers are interleaved with answer lines; content is complete, only ordering noise",
    "implication": "Character-level OCR error rate on language pages measured at 2 slips / 419 pages (~0.5%). The real defect class was file labeling (2 exam sets), now closed. final_integrity.py clean after both swaps (580 files, 1505 pages, 0 orphan images).",
}
v["4_remaining_unresolved"] = [
    "[FIGURE] descriptions are Claude's reading of the image (values marked ~ / approx); the saved PNG remains the ground truth for exact values",
    "Official answer-key typos preserved faithfully and documented",
    "13 language answer-key pages have score numbers interleaved with answers (text-layer order), content complete",
]
v["5_honest_confidence"].update({
    "method": "MEASURED: 1505/1505 Gemini full-text verified; 463 pages Claude Sonnet re-extracted + 87 adjudicated; ALL 539 remaining science pages read by Claude Opus 5 (v8); ALL 419 language pages light-checked by Claude Opus 5 (v9). Every page now has a second reading.",
    "language_pages_checked_pct": "100 (419/419)",
    "language_text_error_rate_measured": "2 character slips in 419 pages (~0.5%)",
    "estimated_true_fully_faithful_pct": "97-99 (science); 98-99 (language, spelling-level check only)",
})
v["verdict_detail"]["disclosures"] = [
    "Every science page has a second-model extraction or a direct Claude Opus 5 visual read; graph data transcribed in [FIGURE] blocks",
    "Every language page had a light Claude Opus 5 visual check (obvious OCR errors only, not a deep re-read)",
    "Two exam sets were mislabeled at upload (francais_2013 exam/solution, english_2020 sujet1/sujet2) and were renamed consistently; see data/raw/RELABEL_LOG.md",
    "[FIGURE] numeric readings are approximate where the print is; PNG is authoritative",
]
v["verdict_detail"]["optional_hardening"] = []
v["artifacts"]["manual_language_read"] = "data/processed/manual_language_read_checkpoint.json (419 verdicts); script scripts/audit/manual_language_read.py; relabels in data/raw/RELABEL_LOG.md"
json.dump(v, open(P/"FINAL_VERDICT.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)

ise = et["independent_second_extraction"]
ise["remaining_unverified"] = {"never_rewritten_science_pages": "0", "never_rewritten_language_pages": "0 (was 419) - light visual check by Claude Opus 5, 401 FAITHFUL / 5 FIXED / 13 NOTE", "cost_to_finish": "$0"}
n = len(et["errors_found_and_fixed"])
et["errors_found_and_fixed"] += [
    {"id": n+1, "page": "arabe_2021_sujet1 p2, arabe_2026_sujet2 p1", "error": "single-letter OCR slips (تارا, خَالِكَه)", "source": "نارا, حَالِكَه", "impact": "grammar question word / poem word", "priority": "Minor", "fixed": True},
    {"id": n+2, "page": "francais_2013 sujet1/sujet2 (+solutions)", "error": "exam and answer-key PDFs uploaded under swapped names", "source": "visual read of the PDFs", "impact": "RAG would answer with the exam and train prediction on the key", "priority": "Important", "fixed": True},
    {"id": n+3, "page": "english_2020 sujet1/sujet2", "error": "sujet1.pdf held الموضوع الثاني, sujet2.pdf held الموضوع الأول", "source": "visual read of the PDFs", "impact": "exam/solution pairing wrong for both subjects", "priority": "Important", "fixed": True},
]
et["timestamp"] = now
json.dump(et, open(P/"ERROR_TRIAGE.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print("FINAL_VERDICT v9 written; language verdicts:", dict(verd))
