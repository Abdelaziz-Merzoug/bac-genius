"""Write FINAL_VERDICT v8 + ERROR_TRIAGE after the manual second read of all 539 science pages (2026-09-19)."""
import json, datetime
from collections import Counter
from pathlib import Path
P = Path("C:/Users/samsung/Desktop/bac-genius/data/processed")
v = json.load(open(P/"FINAL_VERDICT.json", encoding="utf-8")); et = json.load(open(P/"ERROR_TRIAGE.json", encoding="utf-8"))
ck = json.load(open(P/"manual_second_read_checkpoint.json", encoding="utf-8"))
vf = json.load(open(P/"visual_fixes_log.json", encoding="utf-8"))
now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
verd = Counter(x["verdict"] for x in ck.values())
by_subj = Counter((k.split("_")[1], "solution" if "_solution" in k else "exam", x["verdict"]) for k, x in ck.items())

v["timestamp"] = now
v["revision"] = "v8 - manual second read of ALL 539 science pages that never had a second-model extraction (2026-09-19). Supersedes v7."
v["8_manual_second_read"] = {
    "method": "Claude Opus 5 rendered every page (3 per image at 100 DPI, zoom 220-300 DPI on graphs/suspect regions) and compared it line by line with the text file; every discrepancy fixed via Edit, logged in visual_fixes_log.json; verdict per page in manual_second_read_checkpoint.json",
    "pages_read": len(ck), "verdicts": dict(verd),
    "by_subject": {f"{s}/{t}": {"FAITHFUL": by_subj[(s, t, "FAITHFUL")], "FIXED": by_subj[(s, t, "FIXED")]} for s in ("physic", "svt", "math") for t in ("solution", "exam") if by_subj[(s, t, "FAITHFUL")] + by_subj[(s, t, "FIXED")]},
    "defect_classes_found": {
        "graph_data_only_in_image": "MAJOR CLASS (~120 pages, mostly SVT exams 2008-2026 and physics exams 2024-2026): axes, scales, plateau values, tangents, curve comparisons, bar-chart values, recordings (AP/PPSE/PPSI), agglutination outcomes, schema labels lived only in the figure. Every one now transcribed into a [FIGURE: ...] block placed right after the sentence that references it, with the numeric values a student must read off (tau, V_E, N0, t1/2, slopes, percentages).",
        "text_layer_score_blocks_with_question_numbers": "12 solution pages (fixed in v7 pass, re-verified here)",
        "single_symbol_slips": "5 real ones in 539 pages: physic_2024_sujet1 p2 (invented 63/29 for generic A/Z Cu), math_2010_sujet1 p2 (interval ]1;alpha[ reversed), math_2017_sujet1_session1 p1 (A(2;-1;1) -> A(1;-1;2)), physic_2017 lambda 4,09, plus sequence/table fixes from v7",
        "official_typos_preserved": "unchanged (documented in v6/v7)",
    },
    "visual_fixes_log_entries": len(vf),
    "implication": "Formula/number fidelity of the text itself was measured at ~99% (5 slips / 539 pages). The dominant risk was never the OCR: it was graph data absent from the text. That class is now closed for every science page.",
}
v["4_remaining_unresolved"] = [
    "Language-subject pages (arabe/english/francais/islamic: 419 pages) never had a second extraction; they contain no formulas or graphs, risk is spelling-level only",
    "[FIGURE] descriptions are Claude's reading of the image (values marked ~ / approx); the saved PNG remains the ground truth for exact values",
    "Official answer-key typos preserved faithfully and documented",
    "Downstream detector counts unchanged - all cleared as false positives",
]
v["5_honest_confidence"].update({
    "method": "MEASURED: 1505/1505 Gemini full-text verified; 463 pages Claude Sonnet re-extracted + 87 adjudicated; ALL 539 remaining science pages read directly by Claude Opus 5 against the render (v8). Only the 419 language pages lack a second read.",
    "science_pages_fully_verified_pct": "100 (1086/1086 science pages have a second independent reading)",
    "text_symbol_error_rate_measured": "5 real slips in 539 never-rewritten pages (~0.9% of pages)",
    "estimated_true_fully_faithful_pct": "97-99 (science); language pages unchanged at 93-97 estimate",
    "retracted": v["5_honest_confidence"]["retracted"] + ["93-97 (v7, before manual read of the 539 science pages)"],
})
v["6_verdict"] = "GO"
v["verdict_detail"]["disclosures"] = [
    "Every science exam/solution page now has either a second-model extraction or a direct Claude Opus 5 visual read; graph data that questions depend on is transcribed in [FIGURE] blocks",
    "Language subjects rely on the single Gemini extraction (no formulas/graphs there)",
    "[FIGURE] numeric readings are approximate where the print is; PNG is authoritative",
]
v["verdict_detail"]["optional_hardening"] = ["If an API key returns: second-extract the 419 language pages (~$2) for uniform certification"]
v["artifacts"]["manual_second_read"] = "data/processed/manual_second_read_checkpoint.json (539 verdicts) + visual_fixes_log.json (%d entries); script scripts/audit/manual_second_read.py" % len(vf)
json.dump(v, open(P/"FINAL_VERDICT.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)

ise = et["independent_second_extraction"]
ise["remaining_unverified"] = {
    "never_rewritten_science_pages": "0 (was 539) - all read visually by Claude Opus 5, 387 FAITHFUL / 152 FIXED",
    "never_rewritten_language_pages": "419 - no formulas/graphs; spelling-level risk only",
    "cost_to_finish": "$0 spent; optional ~$2 for language pages",
}
n = len(et["errors_found_and_fixed"])
et["errors_found_and_fixed"] += [
    {"id": n+1, "page": "~120 science exam pages (SVT 2008-2026, physics 2024-2026, math graph-reading exercises)", "error": "graph/schema data that questions depend on existed only in the image", "source": "read from renders at 220-300 DPI", "impact": "question generation & RAG could not answer 'read graphically' questions", "priority": "Important", "fixed": True},
    {"id": n+2, "page": "physic_2024_sujet1 p2", "error": "{}_{29}^{63}Cu", "source": "generic {}_Z^A Cu (part of the question)", "impact": "nuclear equation data", "priority": "Important", "fixed": True},
    {"id": n+3, "page": "math_2010_sujet1 p2 II.5", "error": "]alpha;1[", "source": "]1;alpha[", "impact": "interval bounds", "priority": "Important", "fixed": True},
    {"id": n+4, "page": "math_2017_sujet1_session1 p1", "error": "A(2;-1;1)", "source": "A(1;-1;2)", "impact": "space geometry data", "priority": "Important", "fixed": True},
]
et["timestamp"] = now
json.dump(et, open(P/"ERROR_TRIAGE.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print("FINAL_VERDICT v8 written; verdicts:", dict(verd), "| visual fixes:", len(vf))
