"""Stage 1 (language subjects) — segment arabe/islamic/francais/english texts into SECTION records.
Language subjects are RAG-only (config/streams.py), so the unit is the exam section, not an exercise.

Sections per subject (canonical keys):
  arabe    : text (النص) | fikri (البناء الفكري) | lughawi (البناء اللغوي) | naqdi (التقويم النقدي)
  islamic  : part1 (الجزء الأول) | part2 (الجزء الثاني)
  francais : text (Texte) | comprehension (I. Compréhension) | production (II. Production écrite)
  english  : reading (Part One / A. Comprehension incl. the text) | exploration (B. Text Exploration)
             | writing (Part Two: Written Expression)
Output: data/structured/{subject}_sections.jsonl + {subject}_segmentation_report.json  (same record shape as
science exercises, with section_key/section_label instead of exercise_index/label).
usage: segment_language.py [arabe islamic francais english]
"""
import json, re, sys
from collections import Counter, defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from segment_exams import (P, TEXTS, OUT, CAPTION_INDEX, STEM_RX, PAGE_RX, FIG_RX, parse_pages, split_items,
                           norm_head, ar_digits, fragments)

PTS = r"[\s:：\-–]*[\(\[]?\s*(?P<pts>[\d٠-٩]+(?:[.,]\d+)?)\s*[\)\]]?\s*(?:نقاط|نقطة|نقط|points?|pts?)"
SECTIONS = {
    "arabe": [("text", r"النص\s*(?:[:：]|$)"), ("questions", r"الأسئلة\s*:?\s*$"),
              ("fikri", r"(?:أولا|اولا|أ|ب|ج)?[\s\-–:\.\)]*البناء الفكري"), ("lughawi", r"(?:ثانيا|أ|ب|ج)?[\s\-–:\.\)]*البناء اللغوي"),
              ("naqdi", r"(?:ثالثا|ج)?[\s\-–:\.\)]*التقويم النقدي")],
    "islamic": [("part1", r"الجزء الأول"), ("part2", r"الجزء الثاني")],
    "francais": [("text", r"texte\s*:?\s*$"), ("questions", r"questions\s*:?\s*$"),
                 ("comprehension", r"(?:I\s*[\.\-–/:]?\s*)?compr[ée]hension(?:\s+de\s+l['’][ée]crit)?"),
                 ("production", r"(?:II\s*[\.\-–/:]?\s*)?production(?:\s+de\s+l['’])?\s*[ée]crite?\b|II\s*[\.\-–/:]?\s*production\b")],
    "english": [("reading", r"part\s+(?:one|1|I)\b(?!I)"), ("exploration", r"B[\)/\.\-]?\s*text\s+exploration"),
                ("writing", r"part\s+(?:two|2|II)\b")],
}
HEADER_RX = re.compile(r"الجمهورية|وزارة|الديوان|امتحان بكالوريا|دورة|الشعب|اختبار في مادة|المدة|المترشح|الموضوع|يحتوي الموضوع|"
                       r"^صفحة|^\[PAGE|République|Ministère|Office|Examen|Session|Filière|Épreuve|Durée|candidat|Sujet\s*\d|Page \d|^\s*$")
LABELS = {"text": "النص", "questions": "الأسئلة", "fikri": "البناء الفكري", "lughawi": "البناء اللغوي", "naqdi": "التقويم النقدي",
          "part1": "الجزء الأول", "part2": "الجزء الثاني", "comprehension": "Compréhension de l'écrit",
          "production": "Production écrite", "reading": "Part One: Reading", "exploration": "Text Exploration",
          "writing": "Part Two: Written Expression"}
LEAD = r"^[\s#*_\-–>\(\[]*"

def compile_sections(subj):
    return [(k, re.compile(LEAD + rx + r"(?:" + PTS + r")?", re.I)) for k, rx in SECTIONS[subj]]

def find_section(line, rules):
    for frag in fragments(line):
        for key, rx in rules:
            m = rx.match(frag)
            if m: return key, m
    return None, None

def segment_file(path, rules, captions):
    stem = path.stem
    m = STEM_RX.match(stem)
    if not m: return None
    meta = {"subject": m["subject"], "year": int(m["year"]), "sujet": int(m["sujet"]),
            "session": int(m["session"]) if m["session"] else None,
            "doc_type": "solution" if m["sol"] else "exam", "stem": stem}
    pages = parse_pages(path.read_text("utf-8"))
    secs, cur, preamble = [], None, []
    for pn, lines in pages:
        for line in lines:
            key, h = find_section(line, rules)
            if key == "questions":           # "الأسئلة:" / "QUESTIONS" only closes the text section
                if cur and cur["section_key"] == "text": secs.append(cur); cur = None
                continue
            if key and not (cur and cur["section_key"] == key):
                if cur: secs.append(cur)
                pts = float(ar_digits(h["pts"])) if h.groupdict().get("pts") else None
                cur = {"section_key": key, "section_label": LABELS[key], "points": pts, "pages": [pn], "lines": [line.strip()]}
                continue
            if cur:
                if pn not in cur["pages"]: cur["pages"].append(pn)
                cur["lines"].append(line.rstrip())
            else: preamble.append(line.rstrip())
    if cur: secs.append(cur)
    notes = []
    # 2008-era PDFs: page 1 can carry the TAIL of the other subject (its last section) before this
    # subject's passage starts. A "late" section that precedes the primary one is that tail.
    LATE, PRIMARY = {"lughawi", "naqdi", "production", "exploration", "writing", "part2"}, {"fikri", "comprehension", "reading", "part1"}
    while meta["doc_type"] == "exam" and len(secs) > 1 and secs[0]["section_key"] in LATE \
            and any(s["section_key"] in PRIMARY for s in secs[1:]):
        foreign = secs.pop(0)
        notes.append(f"dropped leading {foreign['section_key']} section (tail of the other subject) p{foreign['pages']}")
        if not any(s["section_key"] == "text" for s in secs):
            # the passage may sit at the end of that foreign block: take it from the first long line on
            fl = foreign["lines"]
            def passage_start(i):  # a paragraph (not a numbered prompt) with another long line close by
                return len(fl[i].strip()) >= 150 and not re.match(r"^\s*\d+[\.\)\-]", fl[i]) \
                    and sum(len(x.strip()) >= 150 for x in fl[i+1:i+6]) >= 1
            start = next((i for i in range(len(fl)) if passage_start(i)), None)
            if start is not None:
                secs.insert(0, {"section_key": "text", "section_label": LABELS["text"], "points": None,
                                "pages": foreign["pages"], "lines": foreign["lines"][start:], "heading_inferred": True})
                notes.append("recovered passage from the tail block")
    # merge repeated keys (section continued after a page-break header) keeping first occurrence order
    merged = {}
    for s in secs:
        if s["section_key"] in merged:
            t = merged[s["section_key"]]; t["lines"] += s["lines"]; t["pages"] += [p for p in s["pages"] if p not in t["pages"]]
        else: merged[s["section_key"]] = s
    secs = list(merged.values())
    # arabe/francais exams: the passage often has no "النص"/"Texte" heading and sits before the questions
    if meta["subject"] in ("arabe", "francais") and meta["doc_type"] == "exam" and "text" not in merged and secs:
        body = [l for l in preamble if not HEADER_RX.search(l.strip())]
        if len("".join(body)) > 300:
            secs.insert(0, {"section_key": "text", "section_label": LABELS["text"], "points": None,
                            "pages": [pages[0][0]], "lines": body, "heading_inferred": True}); preamble = []
    whole = False
    if not secs:  # no recognizable section (some answer keys): keep the whole document
        secs = [{"section_key": "whole", "section_label": "whole document", "points": None,
                 "pages": [pn for pn, _ in pages], "lines": [l for _, ls in pages for l in ls]}]; whole = True; preamble = []
    out = []
    for i, s in enumerate(secs, 1):
        text = re.sub(r"\n{3,}", "\n\n", "\n".join(s.pop("lines")).strip())
        out.append({"id": f"{stem}__s{i}", **meta, **s, "text": text, "figures": FIG_RX.findall(text),
                    "captions": [c for pg in s["pages"] for c in captions.get((stem, pg), [])],
                    "items": split_items(text.splitlines()), "whole_document": whole})
    return {"records": out, "preamble": "\n".join(preamble).strip(), "notes": notes}

def main(subjects):
    idx = json.loads(CAPTION_INDEX.read_text("utf-8"))
    caps = defaultdict(list)
    for c in idx:
        if c.get("content_type") != "full_page_text": caps[(c["stem"], c["page_num"])].append(c["caption_file"])
    for subj in subjects:
        rules = compile_sections(subj)
        rep = {"files": 0, "skipped_combined": 0, "sections": 0, "whole_document": [], "section_sets": Counter(), "by_doc_type": Counter(), "notes": {}}
        with open(OUT/f"{subj}_sections.jsonl", "w", encoding="utf-8") as fo:
            for f in sorted((TEXTS/subj).glob("*.txt")):
                if "_and_" in f.stem: rep["skipped_combined"] += 1; continue
                res = segment_file(f, rules, caps)
                if not res: continue
                rep["files"] += 1
                if res["notes"]: rep["notes"][f.stem] = res["notes"]
                keys = tuple(r["section_key"] for r in res["records"])
                if keys == ("whole",): rep["whole_document"].append(f.stem)
                rep["section_sets"][f"{res['records'][0]['doc_type']}:" + "+".join(keys)] += 1
                for r in res["records"]:
                    fo.write(json.dumps(r, ensure_ascii=False) + "\n"); rep["sections"] += 1; rep["by_doc_type"][r["doc_type"]] += 1
        rep["section_sets"] = dict(rep["section_sets"].most_common()); rep["by_doc_type"] = dict(rep["by_doc_type"])
        (OUT/f"{subj}_segmentation_report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), "utf-8")
        print(subj, json.dumps(rep, ensure_ascii=False))

if __name__ == "__main__":
    main(sys.argv[1:] or ["arabe", "islamic", "francais", "english"])
