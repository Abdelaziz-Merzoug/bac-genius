"""Second pass on UNCLEAR pages: verdict-only prompt, 4000 tokens, no reasoning shown."""
import json, os, re, sys, time, threading
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter

sys.stdout.reconfigure(line_buffering=True)
PROJECT = Path("C:/Users/samsung/Desktop/bac-genius")
TEXTS = PROJECT / "data/processed/texts"
SUBJECTS = ["arabe","english","francais","islamic","math","physic","svt"]
MAIN = PROJECT / "data/processed/verify_all_pages_checkpoint.json"
WORKERS = 6

for line in (PROJECT / ".env").read_text("utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k,_,v = line.partition("="); os.environ.setdefault(k.strip(), v.strip())
from google import genai
from google.genai import types
from google.genai.types import Part
import pymupdf
client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
MODEL = "models/gemini-3.6-flash"

manifest = json.loads((PROJECT/"data/raw/manifest.json").read_text("utf-8"))
ocr = json.loads((PROJECT/"data/processed/ocr_manifest.json").read_text("utf-8"))
pdf_by_stem = {Path(r["path"]).stem: PROJECT/r["path"] for r in manifest if not r.get("duplicate")}

def parse_pages(c):
    pages={}; cur=0; lines=[]
    for line in c.splitlines():
        m=re.match(r"^\[PAGE\s+(\d+)\]", line.strip())
        if m:
            if cur>0: pages[cur]="\n".join(lines).strip()
            cur=int(m.group(1)); lines=[]
        else:
            if cur>0: lines.append(line)
    if cur>0: pages[cur]="\n".join(lines).strip()
    return pages

ck = json.loads(MAIN.read_text("utf-8"))
results = ck["results"]
by_key = {r["key"]: r for r in results}
targets = [r for r in results if r["verdict"] in ("UNCLEAR","ERROR")]
print("Re-checking {0} UNCLEAR/ERROR pages".format(len(targets)))

PROMPT = """Compare the PDF page image with the extracted text. Decide if the extracted text is a SEMANTICALLY FAITHFUL representation.

IMPORTANT OUTPUT RULES:
- Do NOT show your comparison process.
- Do NOT quote matching passages.
- Your ENTIRE response must be at most 6 lines.
- Line 1 must be exactly: SEMANTIC_VERDICT: FAITHFUL   or   SEMANTIC_VERDICT: CORRUPTED
- Lines 2-6: only list REAL semantic errors (wrong number/score/formula, missing sentence/section/scoring column, invented text, garbled Arabic that changes meaning). Write "none" if there are none.

Formatting differences (whitespace, table layout, LaTeX vs visual math, header order, missing underlines) are NOT errors.

EXTRACTED TEXT:
{text}"""

def recheck(r):
    stem, pn = r["key"].rsplit("__p",1); pn=int(pn)
    subj = r["subject"]
    txt = TEXTS/subj/(stem+".txt")
    pages = parse_pages(txt.read_text("utf-8"))
    text = pages.get(pn,"")
    pdf = pdf_by_stem.get(stem)
    if not pdf or not pdf.exists():
        src = ocr.get(stem,{}).get("source_pdf","")
        if src: pdf = PROJECT/src
    pp = ocr.get(stem,{}).get("pdf_pages",[])
    idx = (pp[pn-1]-1) if (pp and len(pp)>=pn) else pn-1
    try:
        doc = pymupdf.open(str(pdf)); pix = doc[idx].get_pixmap(dpi=150); img = pix.tobytes("png"); doc.close()
    except Exception as e:
        return dict(r, verdict="ERROR", detail="render: "+str(e)[:120], pass_="2")
    for attempt in range(4):
        try:
            resp = client.models.generate_content(model=MODEL,
                contents=[Part.from_bytes(data=img, mime_type="image/png"), PROMPT.format(text=text)],
                config=types.GenerateContentConfig(temperature=0.0, max_output_tokens=6000,
                    thinking_config=types.ThinkingConfig(thinking_budget=2500)))
            rt=(resp.text or "").strip(); up=rt[:200].upper()
            if "SEMANTIC_VERDICT: FAITHFUL" in up or "SEMANTIC_VERDICT:FAITHFUL" in up: v="FAITHFUL"
            elif "SEMANTIC_VERDICT: CORRUPTED" in up or "SEMANTIC_VERDICT:CORRUPTED" in up: v="CORRUPTED"
            elif "FAITHFUL" in up: v="FAITHFUL"
            elif "CORRUPTED" in up: v="CORRUPTED"
            else: v="UNCLEAR"
            return dict(r, verdict=v, detail=rt[:700], pass_="2")
        except Exception as e:
            err=str(e)
            if "429" in err or "RESOURCE_EXHAUSTED" in err: time.sleep(20+attempt*15)
            elif "503" in err or "500" in err: time.sleep(10)
            else: return dict(r, verdict="ERROR", detail=err[:150], pass_="2")
    return dict(r, verdict="ERROR", detail="max retries", pass_="2")

lock=threading.Lock(); n=[0]
with ThreadPoolExecutor(max_workers=WORKERS) as ex:
    futs=[ex.submit(recheck,r) for r in targets]
    for f in as_completed(futs):
        nr=f.result()
        with lock:
            by_key[nr["key"]]=nr; n[0]+=1
            if n[0]%25==0:
                cc=Counter(by_key[t["key"]]["verdict"] for t in targets)
                print("  {0}/{1} re-checked | {2}".format(n[0], len(targets), dict(cc)))
                ck["results"]=list(by_key.values()); MAIN.write_text(json.dumps(ck,indent=1,ensure_ascii=False),"utf-8")
ck["results"]=list(by_key.values()); MAIN.write_text(json.dumps(ck,indent=1,ensure_ascii=False),"utf-8")
cc=Counter(by_key[t["key"]]["verdict"] for t in targets)
print("\nSecond pass done: {0}".format(dict(cc)))
allc=Counter(r["verdict"] for r in by_key.values())
print("ALL PAGES NOW: {0}".format(dict(allc)))
