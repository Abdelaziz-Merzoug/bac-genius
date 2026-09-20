"""
EXHAUSTIVE 100% PAGE VERIFICATION — all 1505 pages vs source PDFs.
Parallel workers, checkpointed, resumable. FULL page text (no truncation).
Semantic-fidelity prompt: formatting differences do NOT count.
"""
import json, os, re, sys, time, threading
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.stdout.reconfigure(line_buffering=True)

PROJECT = Path("C:/Users/samsung/Desktop/bac-genius")
TEXTS = PROJECT / "data/processed/texts"
SUBJECTS = ["arabe", "english", "francais", "islamic", "math", "physic", "svt"]
CHECKPOINT = PROJECT / "data/processed/verify_all_pages_checkpoint.json"
WORKERS = 8

for line in (PROJECT / ".env").read_text("utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

from google import genai
from google.genai import types
from google.genai.types import Part
import pymupdf

client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
MODEL = "models/gemini-3.6-flash"

manifest = json.loads((PROJECT / "data/raw/manifest.json").read_text("utf-8"))
ocr_manifest = json.loads((PROJECT / "data/processed/ocr_manifest.json").read_text("utf-8"))

pdf_by_stem = {}
for rec in manifest:
    if not rec.get("duplicate"):
        pdf_by_stem[Path(rec.get("path", "")).stem] = PROJECT / rec["path"]

def parse_pages(content):
    pages = {}; cur = 0; lines = []
    for line in content.splitlines():
        m = re.match(r"^\[PAGE\s+(\d+)\]", line.strip())
        if m:
            if cur > 0: pages[cur] = "\n".join(lines).strip()
            cur = int(m.group(1)); lines = []
        else:
            if cur > 0: lines.append(line)
    if cur > 0: pages[cur] = "\n".join(lines).strip()
    return pages

# Build complete page list
all_pages = []
for subj in SUBJECTS:
    for txt_file in sorted((TEXTS / subj).glob("*.txt")):
        stem = txt_file.stem
        pages = parse_pages(txt_file.read_text("utf-8"))
        pdf_path = pdf_by_stem.get(stem)
        if not pdf_path or not pdf_path.exists():
            src = ocr_manifest.get(stem, {}).get("source_pdf", "")
            if src: pdf_path = PROJECT / src
        if not pdf_path or not pdf_path.exists():
            continue
        pp = ocr_manifest.get(stem, {}).get("pdf_pages", [])
        for pn, text in pages.items():
            pdf_idx = (pp[pn-1] - 1) if (pp and len(pp) >= pn) else (pn - 1)
            all_pages.append({
                "key": "{0}__p{1}".format(stem, pn),
                "stem": stem, "subject": subj, "page": pn,
                "pdf_path": str(pdf_path), "pdf_idx": pdf_idx,
                "text": text, "is_exam": "solution" not in stem,
            })

print("TOTAL PAGES TO VERIFY: {0}".format(len(all_pages)))

completed = {}
if CHECKPOINT.exists():
    try:
        ck = json.loads(CHECKPOINT.read_text("utf-8"))
        completed = {r["key"]: r for r in ck.get("results", [])}
    except: pass

remaining = [p for p in all_pages if p["key"] not in completed]
print("Already done: {0} | Remaining: {1}".format(len(completed), len(remaining)))

PROMPT = """You are verifying that extracted text faithfully preserves the SEMANTIC CONTENT of a BAC exam PDF page.

Output your verdict on the FIRST line, in exactly this format:
SEMANTIC_VERDICT: FAITHFUL
or
SEMANTIC_VERDICT: CORRUPTED

Then on following lines list any errors found (or "none").

A page is FAITHFUL if all meaningful content is present and correct, even if:
- whitespace, line breaks, indentation differ
- tables are rendered as markdown/LaTeX instead of visual grids
- math is written as LaTeX instead of visual notation
- headers/footers are rearranged
- decorative elements (underlines, borders, logos) are absent
- Unicode is normalized

A page is CORRUPTED only if there is a REAL semantic defect:
- a number, decimal, score, or unit is WRONG
- a formula/equation/fraction/exponent is WRONG
- words, sentences, or whole sections are MISSING
- text was INVENTED that is not in the image
- Arabic letters are reversed/garbled so meaning changes
- question numbers or answer options are wrong or misordered
- scientific terms or labels are wrong

Be strict about real errors, but do NOT report formatting as corruption.

EXTRACTED TEXT:
{text}"""

lock = threading.Lock()
results_list = list(completed.values())
done_count = [0]
start_time = time.time()

def save_ckpt():
    tmp = CHECKPOINT.with_suffix(".tmp")
    tmp.write_text(json.dumps({
        "results": results_list,
        "total": len(all_pages),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }, indent=1, ensure_ascii=False), "utf-8")
    tmp.replace(CHECKPOINT)

def verify_page(page):
    key = page["key"]
    try:
        doc = pymupdf.open(page["pdf_path"])
        if page["pdf_idx"] >= len(doc) or page["pdf_idx"] < 0:
            doc.close()
            return {"key": key, "subject": page["subject"], "is_exam": page["is_exam"],
                    "verdict": "ERROR", "detail": "pdf page index out of range"}
        pix = doc[page["pdf_idx"]].get_pixmap(dpi=150)
        img = pix.tobytes("png")
        doc.close()
    except Exception as e:
        return {"key": key, "subject": page["subject"], "is_exam": page["is_exam"],
                "verdict": "ERROR", "detail": "render: " + str(e)[:150]}

    prompt = PROMPT.format(text=page["text"])
    for attempt in range(4):
        try:
            resp = client.models.generate_content(
                model=MODEL,
                contents=[Part.from_bytes(data=img, mime_type="image/png"), prompt],
                config=types.GenerateContentConfig(temperature=0.0, max_output_tokens=1200),
            )
            rt = (resp.text or "").strip()
            head = rt[:200].upper()
            if "SEMANTIC_VERDICT: FAITHFUL" in head or "SEMANTIC_VERDICT:FAITHFUL" in head:
                v = "FAITHFUL"
            elif "SEMANTIC_VERDICT: CORRUPTED" in head or "SEMANTIC_VERDICT:CORRUPTED" in head:
                v = "CORRUPTED"
            elif "FAITHFUL" in head:
                v = "FAITHFUL"
            elif "CORRUPTED" in head:
                v = "CORRUPTED"
            else:
                v = "UNCLEAR"
            return {"key": key, "subject": page["subject"], "is_exam": page["is_exam"],
                    "verdict": v, "detail": rt[:700]}
        except Exception as e:
            err = str(e)
            if "429" in err or "RESOURCE_EXHAUSTED" in err:
                time.sleep(20 + attempt * 15)
            elif "503" in err or "500" in err or "UNAVAILABLE" in err:
                time.sleep(10 + attempt * 5)
            else:
                return {"key": key, "subject": page["subject"], "is_exam": page["is_exam"],
                        "verdict": "ERROR", "detail": err[:200]}
    return {"key": key, "subject": page["subject"], "is_exam": page["is_exam"],
            "verdict": "ERROR", "detail": "max retries exceeded"}

with ThreadPoolExecutor(max_workers=WORKERS) as ex:
    futures = {ex.submit(verify_page, p): p for p in remaining}
    for fut in as_completed(futures):
        r = fut.result()
        with lock:
            results_list.append(r)
            completed[r["key"]] = r
            done_count[0] += 1
            n = done_count[0]
            if n % 25 == 0:
                save_ckpt()
                f_ = sum(1 for x in results_list if x["verdict"] == "FAITHFUL")
                c_ = sum(1 for x in results_list if x["verdict"] == "CORRUPTED")
                u_ = sum(1 for x in results_list if x["verdict"] == "UNCLEAR")
                e_ = sum(1 for x in results_list if x["verdict"] == "ERROR")
                el = time.time() - start_time
                rate = n / el if el > 0 else 0
                eta = (len(remaining) - n) / rate / 60 if rate > 0 else 0
                print("  {0}/{1} | FAITHFUL={2} CORRUPTED={3} UNCLEAR={4} ERR={5} | {6:.1f}p/s ETA {7:.0f}min".format(
                    len(completed), len(all_pages), f_, c_, u_, e_, rate, eta))

save_ckpt()

f_ = sum(1 for x in results_list if x["verdict"] == "FAITHFUL")
c_ = sum(1 for x in results_list if x["verdict"] == "CORRUPTED")
u_ = sum(1 for x in results_list if x["verdict"] == "UNCLEAR")
e_ = sum(1 for x in results_list if x["verdict"] == "ERROR")

ef = sum(1 for x in results_list if x.get("is_exam") and x["verdict"]=="FAITHFUL")
ec = sum(1 for x in results_list if x.get("is_exam") and x["verdict"]=="CORRUPTED")
sf = sum(1 for x in results_list if not x.get("is_exam") and x["verdict"]=="FAITHFUL")
sc = sum(1 for x in results_list if not x.get("is_exam") and x["verdict"]=="CORRUPTED")

print("\n" + "="*60)
print("EXHAUSTIVE PAGE VERIFICATION COMPLETE")
print("="*60)
print("Coverage: {0}/{1} pages".format(len(completed), len(all_pages)))
print("FAITHFUL={0} CORRUPTED={1} UNCLEAR={2} ERROR={3}".format(f_, c_, u_, e_))
print("Exams:     FAITHFUL={0} CORRUPTED={1}".format(ef, ec))
print("Solutions: FAITHFUL={0} CORRUPTED={1}".format(sf, sc))

report = {
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "coverage": "{0}/{1}".format(len(completed), len(all_pages)),
    "faithful": f_, "corrupted": c_, "unclear": u_, "error": e_,
    "exam_faithful": ef, "exam_corrupted": ec,
    "soln_faithful": sf, "soln_corrupted": sc,
    "results": results_list,
}
(PROJECT / "data/processed/verify_all_pages.json").write_text(
    json.dumps(report, indent=1, ensure_ascii=False), "utf-8")
print("\nSaved report.")
