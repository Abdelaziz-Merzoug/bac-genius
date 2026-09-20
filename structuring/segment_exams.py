"""Stage 1 — segment science exam texts into exercise records.

Input : data/processed/texts/{subject}/{stem}.txt   (one [PAGE N] block per page)
        data/processed/image_captions/index.json     (captions, linked by stem + page)
Output: data/structured/{subject}_exercises.jsonl    (one record per exercise)
        data/structured/{subject}_segmentation_report.json

Each record:
  id, subject, year, session, sujet, doc_type (exam|solution), stem,
  part (الجزء الأول/الثاني or null), exercise_label, exercise_index, points,
  pages [..], text, figures [inline [FIGURE: ...] blocks], captions [image caption files],
  items [{label, text}]  (top-level numbered sub-questions, best effort)

usage: segment_exams.py physic [math svt ...]   (default: physic math svt)
"""
import json, re, sys
from collections import Counter, defaultdict
from pathlib import Path

P = Path("C:/Users/samsung/Desktop/bac-genius")
TEXTS, OUT = P/"data/processed/texts", P/"data/structured"
CAPTION_INDEX = P/"data/processed/image_captions/index.json"

ORD = {"الأول": 1, "الاول": 1, "الثاني": 2, "الثالث": 3, "الرابع": 4, "الخامس": 5, "التجريبي": 9}
STEM_RX = re.compile(r"^bac_(?P<subject>[a-z]+)_(?P<year>\d{4})_sujet(?P<sujet>\d)(?P<sol>_solution)?(?:_session(?P<session>\d))?$")
PAGE_RX = re.compile(r"^\[PAGE (\d+)\]\s*$")
# heading: optional markdown noise, then التمرين/الجزء + ordinal, optional "(N نقاط)" in loose punctuation
HEAD_RX = re.compile(
    r"^[\s#*_\-]*(?P<kind>التمر[يب]ن|الجزء)\s+(?P<ord>الأول|الاول|الثاني|الثالث|الرابع|الخامس|التجريبي)"
    r"[\s:：*_]*(?:\(?\s*(?P<pts>[\d٠-٩]+(?:[.,]\d+)?)\s*\)?\s*(?:نقاط|نقطة|نقطتان|نقط|ن)\b[^\n]*)?")
FIG_RX = re.compile(r"\[FIGURE:.*?\]", re.S)
# numbered question marker at the start of a line / cell: "1." "1)" "1-" "(1)" "1/" "١-" "**1-**" "أ/ 1-"
ITEM_RX = re.compile(r"^[\s\(\[]*(?:الجزء\s+\S+\s*[:：]\s*)?(?:I{1,3}V?\s*[\)\.\-–/]{1,2}\s*)?(?:[أابجدهـ]\s*[/\)\-–]\s*)?(?P<label>[1-9]\d?(?:\.\d+)*|[١-٩][٠-٩]?(?:\.[٠-٩]+)*)\s*[\)\]\.\-–/:]\s*(?=\S|$)")

# RTL-reversed marker "-2 text" (the source "2-" flipped by the text layer)
ITEM_RTL_RX = re.compile(r"^\s*(?:[\-–]\s*(?P<label>[1-9]\d?|[١-٩][٠-٩]?)\s+(?=[^\d\s$])|\(\s*(?P<label2>[1-9]\d?|[١-٩][٠-٩]?)\s*$"
                         r"|(?P<label3>[1-9]\d?)\s+(?![Pp]ts?\b|[Pp]oints?\b)(?=[A-Z][a-z]))")   # English keys: "5 The text is"
PAGE_NOISE_RX = re.compile(r"^(?:صفحة|الصفحة)\s*[\d٠-٩]+\s*من\s*[\d٠-٩]+|^[\d٠-٩]+\s*/\s*[\d٠-٩]+\s*$|^page\s*\d+|اقلب الصفحة|^اختبار في مادة|^تابع (?:الإجابة|للإجابة)|^الإجابة النموذجية|^عناصر الإجابة|^\[FIGURE", re.I)

def ar_digits(s): return s.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")).replace(",", ".")
TASHKEEL_RX = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")
NOISE_RX = re.compile(r"</?u>|</?b>|\*\*|__|\$?\\underline\{\\text\{|\}\}\$?|[‎‏]")
SUJET_RX = re.compile(r"^[\s#*_\-(]*(?:عناصر الإجابة\s*\(?\s*)?الموضوع\s+(?P<ord>الأول|الاول|الثاني)\b")
def norm_head(s): return NOISE_RX.sub("", TASHKEEL_RX.sub("", s))  # strip diacritics/tatweel/inline markup

def fragments(line):
    """Table cells, <br> fragments and ' / ' segments (solutions are markdown tables with headings
    buried in cells; some page headers carry the heading after a slash)."""
    return re.split(r"<br\s*/?>|\||\s/\s", norm_head(line))

def find_headings(line):
    for frag in fragments(line):
        h = HEAD_RX.match(frag)
        if h: yield h

def sujet_marker(line):
    for frag in fragments(line):
        m = SUJET_RX.match(frag)
        if m: return 1 if m["ord"] in ("الأول", "الاول") else 2
    return None

def parse_pages(txt):
    pages, cur, n = [], [], 0
    for line in txt.splitlines():
        m = PAGE_RX.match(line)
        if m:
            if n: pages.append((n, cur))
            n, cur = int(m.group(1)), []
        else: cur.append(line)
    if n: pages.append((n, cur))
    return pages

CELL_NOISE_RX = re.compile(r"\*\*|__|</?u>|</?b>|\\underline\{\\text\{|\}\}")
def item_label(line):
    """Question label opening this (virtual) line, as a string: "3" or hierarchical "2.2" / "4.1.2"."""
    t = CELL_NOISE_RX.sub("", TASHKEEL_RX.sub("", line)).strip()
    if re.fullmatch(r"[\d.,\s×x+]+", t) or PAGE_NOISE_RX.match(t): return None   # score cell / page footer
    m = ITEM_RX.match(t) or ITEM_RTL_RX.match(t)
    if not m: return None
    if t.startswith("(") and len(re.findall(r"\(\s*[1-9]\s*\)", t)) >= 2: return None   # "(1) … (2) …" option list
    if re.match(r"^\d+-[ء-ي]", t) and re.search(r"[ء-ي]-\d+-", t): return None  # "3-ميثيل بوتان-1-أول"
    g = m.groupdict()
    return ar_digits(g.get("label") or g.get("label2") or g.get("label3"))
def leading(label): return int(label.split(".")[0])

def virtual_lines(lines):
    """Answer keys put a whole exercise in one markdown-table cell separated by <br>: split table
    rows into cells and cells into <br> fragments so each answer step becomes its own line."""
    for l in lines:
        if "<br" in l or l.lstrip().startswith("|") or " | " in l:
            # table rows: split at pipes (a row may lose its leading pipe: "$2 \times 0,25$ | I) 1) ...")
            cells = re.split(r"(?<!\\)\|", l) if l.lstrip().startswith("|") else re.split(r"\s\|\s", l)
            for c in cells:
                for frag in re.split(r"<br\s*/?>", c):
                    if frag.strip() and not re.fullmatch(r"[\s:\-]+", frag): yield frag.strip()
        else: yield l

def split_items(lines):
    """Top-level numbered sub-questions. A new item starts at a line whose label continues the
    numbering (n+1), or restarts at 1 (roman-numbered sub-parts I/II re-number their questions);
    letters (أ/ب, a/b) and out-of-sequence numbers stay inside the current item."""
    items, cur, expect = [], None, 1
    for l in virtual_lines(lines):
        lab = item_label(l)
        if lab is not None:
            n = leading(lab)
            # hierarchical labels (1.1, 2.3.1) always open an item; flat ones must continue or restart
            if "." in lab or n == expect or n == 1 or (cur is None and n <= 12) or (cur and n > leading(cur["label"]) and n <= 15):
                if cur: items.append(cur)
                cur, expect = {"label": lab, "text": l.strip()}, n + 1
                continue
        if cur: cur["text"] += "\n" + l.rstrip()
    if cur: items.append(cur)
    return [i for i in items if i["text"].strip()]

def segment_file(path, captions_by_stem_page):
    stem = path.stem
    m = STEM_RX.match(stem)
    if not m: return None, "unparsed_stem"
    meta = {"subject": m["subject"], "year": int(m["year"]), "sujet": int(m["sujet"]),
            "session": int(m["session"]) if m["session"] else None,
            "doc_type": "solution" if m["sol"] else "exam", "stem": stem}
    pages = parse_pages(path.read_text("utf-8"))
    # verified 2026-09-20: page 5 of this answer key is a stray copy of sujet2's التمرين الأول
    # (complete in bac_physic_2024_sujet2_solution) -> skip it
    if stem == "bac_physic_2024_sujet1_solution":
        pages = [(pn, ls) for pn, ls in pages if pn != 5]
    recs, part, part_pts, cur, preamble = [], None, None, None, []
    notes = []
    def close():
        if cur and any(l.strip() for l in cur["lines"]):
            same = next((r for r in recs if r["part"] == cur["part"] and r["exercise_index"] == cur["exercise_index"]), None)
            if same:  # heading repeated after a page break ("تابع التمرين ...") -> continuation
                same["lines"] += cur["lines"]; same["pages"] += [p for p in cur["pages"] if p not in same["pages"]]
                notes.append(f"merged repeated heading {cur['exercise_label']} p{cur['pages']}")
            else: recs.append(cur)
    flat = [(pn, line) for pn, lines in pages for line in lines]
    def restarts_after(i):
        """True if the first exercise heading after flat[i] restarts the numbering (index <= max seen)."""
        seen = max([r["exercise_index"] for r in recs] + [cur["exercise_index"] if cur else 0])
        for _, l in flat[i+1:]:
            h = next((h for h in find_headings(l) if h["kind"] != "الجزء"), None)
            if h: return ORD[h["ord"]] <= seen
        return False
    for i, (pn, line) in enumerate(flat):
        if True:
            sj = sujet_marker(line)
            if sj and sj != meta["sujet"] and restarts_after(i):
                # the PDF continues with the OTHER subject's answers (present in its own file) -> stop here
                # (a marker NOT followed by a restart is an official header typo on a continuation page)
                notes.append(f"dropped content after 'الموضوع {sj}' marker at p{pn}"); break
            heads = list(find_headings(line))
            ex = next((h for h in heads if h["kind"] != "الجزء"), None)
            pt = next((h for h in heads if h["kind"] == "الجزء"), None)
            if pt and pt["pts"] is None and cur is not None:
                # SVT style: "الجزء الأول:" without points is a sub-part INSIDE the current exercise
                cur.setdefault("subparts", []).append(f"الجزء {pt['ord']}")
                pt = None
            if pt:
                part = f"الجزء {pt['ord']}"
                part_pts = float(ar_digits(pt["pts"])) if pt["pts"] else None
                close(); cur = None  # part heading closes the exercise; the next التمرين opens a new one
            if ex:
                close()
                pts = float(ar_digits(ex["pts"])) if ex["pts"] else None
                # التمرين التجريبي often carries no points of its own: it is the whole الجزء الثاني
                src = "heading" if pts is not None else ("part" if part_pts is not None else None)
                cur = {"part": part, "exercise_label": f"التمرين {ex['ord']}", "exercise_index": ORD[ex["ord"]],
                       "points": pts if pts is not None else part_pts, "points_source": src,
                       "pages": [pn], "lines": [line.strip()]}
                continue
            if pt: continue
            if cur:
                if pn not in cur["pages"]: cur["pages"].append(pn)
                cur["lines"].append(line.rstrip())
            else:
                preamble.append(line.rstrip())
    close()
    # first exercise heading missing (answer keys often start straight into the answers):
    # a substantial preamble before a first heading that is not الأول -> it is التمرين الأول
    body = [l for l in preamble if l.strip() and not PAGE_RX.match(l)]
    if recs and recs[0]["exercise_index"] not in (1, None) and len("".join(body)) > 300:
        recs.insert(0, {"part": recs[0]["part"], "exercise_label": "التمرين الأول", "exercise_index": 1,
                        "points": None, "points_source": None, "pages": [pages[0][0]], "lines": body,
                        "heading_inferred": True})
        notes.append("inferred التمرين الأول from preamble"); preamble = []
    if not recs and meta["doc_type"] == "solution":
        # answer key without recognizable exercise headings: keep it whole so exam<->solution
        # alignment can still fall back to the document level
        recs = [{"part": None, "exercise_label": None, "exercise_index": None, "points": None,
                 "points_source": None, "pages": [pn for pn, _ in pages],
                 "lines": [l for _, ls in pages for l in ls], "whole_document": True}]
        preamble = []
    out = []
    for i, r in enumerate(recs, 1):
        text = "\n".join(r.pop("lines")).strip()
        text = re.sub(r"\n{3,}", "\n\n", text)
        caps = [c for pg in r["pages"] for c in captions_by_stem_page.get((stem, pg), [])]
        out.append({"id": f"{stem}__ex{i}", **meta, **r, "text": text,
                    "figures": FIG_RX.findall(text), "captions": caps,
                    "items": split_items(text.splitlines())})
    return {"records": out, "preamble": "\n".join(preamble).strip(), "n_pages": len(pages), "notes": notes}, None

def main(subjects):
    OUT.mkdir(exist_ok=True)
    idx = json.loads(CAPTION_INDEX.read_text("utf-8"))
    caps = defaultdict(list)
    for c in idx:
        if c.get("content_type") != "full_page_text":
            caps[(c["stem"], c["page_num"])].append(c["caption_file"])
    for subj in subjects:
        files = sorted((TEXTS/subj).glob("*.txt"))
        rep = {"files": 0, "skipped_combined": 0, "unparsed": [], "zero_exercises": [], "exercises": 0,
               "by_doc_type": Counter(), "exercises_per_exam": Counter(), "points_missing": 0, "notes": {}}
        with open(OUT/f"{subj}_exercises.jsonl", "w", encoding="utf-8") as fo:
            for f in files:
                if "_and_" in f.stem: rep["skipped_combined"] += 1; continue
                res, err = segment_file(f, caps)
                if err: rep["unparsed"].append(f.stem); continue
                rep["files"] += 1
                if res["notes"]: rep["notes"][f.stem] = res["notes"]
                if not res["records"]: rep["zero_exercises"].append(f.stem); continue
                for r in res["records"]:
                    fo.write(json.dumps(r, ensure_ascii=False) + "\n")
                    rep["exercises"] += 1; rep["by_doc_type"][r["doc_type"]] += 1
                    if r["points"] is None and r["doc_type"] == "exam": rep["points_missing"] += 1
                if res["records"][0]["doc_type"] == "exam":
                    rep["exercises_per_exam"][len(res["records"])] += 1
        rep["by_doc_type"] = dict(rep["by_doc_type"]); rep["exercises_per_exam"] = dict(sorted(rep["exercises_per_exam"].items()))
        (OUT/f"{subj}_segmentation_report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), "utf-8")
        print(subj, json.dumps(rep, ensure_ascii=False))

if __name__ == "__main__":
    main(sys.argv[1:] or ["physic", "math", "svt"])
