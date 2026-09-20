"""
For every MEANINGFUL image (GRAPH/DIAGRAM/TABLE/FIGURE/EQUATION), verify against source PDF page:
- image actually appears on that page
- not cropped / no missing labels/axes/legends
- correct orientation
- no corruption
"""
import json, os, sys, time, threading
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter

sys.stdout.reconfigure(line_buffering=True)
PROJECT = Path("C:/Users/samsung/Desktop/bac-genius")
IMAGES = PROJECT / "data/processed/images"
CLASS = PROJECT / "data/processed/classify_images_checkpoint.json"
CHECKPOINT = PROJECT / "data/processed/verify_images_source_checkpoint.json"
WORKERS = 2

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

SPEND = PROJECT / "data/processed/api_spend.json"
_spend_lock = threading.Lock()
spend = {"in": 0, "out": 0, "calls": 0}
if SPEND.exists():
    try: spend = json.loads(SPEND.read_text("utf-8"))
    except: pass
def record_usage(resp):
    um = getattr(resp, "usage_metadata", None)
    if not um: return
    with _spend_lock:
        spend["in"] += um.prompt_token_count or 0
        spend["out"] += (um.candidates_token_count or 0) + (getattr(um, "thoughts_token_count", 0) or 0)
        spend["calls"] += 1
        spend["usd"] = round(spend["in"] * 0.75 / 1e6 + spend["out"] * 3.75 / 1e6, 4)
        if spend["calls"] % 10 == 0: SPEND.write_text(json.dumps(spend), "utf-8")

manifest = json.loads((PROJECT/"data/raw/manifest.json").read_text("utf-8"))
ocr = json.loads((PROJECT/"data/processed/ocr_manifest.json").read_text("utf-8"))
pdf_by_stem = {Path(r["path"]).stem: PROJECT/r["path"] for r in manifest if not r.get("duplicate")}

cls = json.loads(CLASS.read_text("utf-8"))["results"]
MEANINGFUL = {"GRAPH","DIAGRAM","TABLE","FIGURE","EQUATION"}
targets = [r for r in cls if r["category"] in MEANINGFUL]
print("Meaningful images to verify vs source: {0}".format(len(targets)))
print("By category:", dict(Counter(r["category"] for r in targets)))

completed={}
if CHECKPOINT.exists():
    try: completed={r["file"]:r for r in json.loads(CHECKPOINT.read_text("utf-8")).get("results",[])}
    except: pass
remaining=[r for r in targets if r["file"] not in completed]
print("Done: {0} | Remaining: {1}".format(len(completed), len(remaining)))

PROMPT = """You are given TWO images:
IMAGE 1 = an image EXTRACTED from a BAC exam PDF (category: {cat}).
IMAGE 2 = the FULL source PDF page it was extracted from.

Verify that IMAGE 1 faithfully represents the corresponding region of IMAGE 2.

OUTPUT (max 4 lines, no reasoning):
Line 1 exactly: IMAGE_VERDICT: FAITHFUL   or   IMAGE_VERDICT: DEFECTIVE   or   IMAGE_VERDICT: NOT_ON_PAGE
Line 2: ISSUE: none | cropped (missing labels/axes/legend/part of figure) | wrong orientation | corrupted/garbled | different content
Line 3: NOTE: one short sentence.

FAITHFUL = the extracted image contains the same visual information as that region on the page (labels, axes, numbers, curves, structures all present). Resolution differences do not matter.
DEFECTIVE = something meaningful is missing, cut off, rotated, or corrupted.
NOT_ON_PAGE = this image does not appear anywhere on the page."""

lock=threading.Lock(); results=list(completed.values()); n=[0]; t0=time.time()
def save():
    tmp=CHECKPOINT.with_suffix(".tmp")
    tmp.write_text(json.dumps({"results":results,"timestamp":datetime.now(timezone.utc).isoformat()},indent=0,ensure_ascii=False),"utf-8")
    tmp.replace(CHECKPOINT)

def render_page(stem, pn):
    pdf = pdf_by_stem.get(stem)
    if not pdf or not pdf.exists():
        src = ocr.get(stem,{}).get("source_pdf","")
        if src: pdf = PROJECT/src
    pp = ocr.get(stem,{}).get("pdf_pages",[])
    idx = (pp[pn-1]-1) if (pp and len(pp)>=pn) else pn-1
    doc = pymupdf.open(str(pdf))
    if idx>=len(doc) or idx<0: doc.close(); return None
    pix = doc[idx].get_pixmap(dpi=120); b=pix.tobytes("png"); doc.close(); return b

def verify(r):
    try:
        img = (IMAGES/r["subject"]/r["file"]).read_bytes()
        page = render_page(r["stem"], r["page"])
        if page is None: return dict(r, iverdict="ERROR", issue="page index out of range", note="")
    except Exception as e:
        return dict(r, iverdict="ERROR", issue=str(e)[:100], note="")
    for attempt in range(4):
        try:
            resp=client.models.generate_content(model=MODEL,
                contents=[Part.from_bytes(data=img,mime_type="image/png"), Part.from_bytes(data=page,mime_type="image/png"), PROMPT.format(cat=r["category"])],
                config=types.GenerateContentConfig(temperature=0.0, max_output_tokens=1500,
                    thinking_config=types.ThinkingConfig(thinking_budget=800)))
            record_usage(resp)
            rt=(resp.text or "").strip(); up=rt[:150].upper()
            if "NOT_ON_PAGE" in up: v="NOT_ON_PAGE"
            elif "DEFECTIVE" in up: v="DEFECTIVE"
            elif "FAITHFUL" in up: v="FAITHFUL"
            else: v="UNCLEAR"
            issue=""; note=""
            for ln in rt.splitlines():
                u=ln.upper()
                if u.startswith("ISSUE:"): issue=ln[6:].strip()
                elif u.startswith("NOTE:"): note=ln[5:].strip()
            return dict(r, iverdict=v, issue=issue[:150], note=note[:200])
        except Exception as e:
            err=str(e)
            if "429" in err or "RESOURCE_EXHAUSTED" in err: time.sleep(20+attempt*15)
            elif "503" in err or "500" in err: time.sleep(10)
            else: return dict(r, iverdict="ERROR", issue=err[:100], note="")
    return dict(r, iverdict="ERROR", issue="max retries", note="")

with ThreadPoolExecutor(max_workers=WORKERS) as ex:
    futs=[ex.submit(verify,r) for r in remaining]
    for f in as_completed(futs):
        x=f.result()
        with lock:
            results.append(x); completed[x["file"]]=x; n[0]+=1
            if n[0]%25==0:
                save(); cc=Counter(y["iverdict"] for y in results); el=time.time()-t0; rate=n[0]/el
                print("  {0}/{1} | {2} | ETA {3:.0f}min".format(len(completed),len(targets),dict(cc),(len(remaining)-n[0])/rate/60 if rate else 0))
save()
cc=Counter(y["iverdict"] for y in results)
print("\nDONE {0}/{1}: {2}".format(len(completed),len(targets),dict(cc)))
(PROJECT/"data/processed/verify_images_vs_source.json").write_text(json.dumps({"total":len(targets),"verdicts":dict(cc),"results":results},indent=0,ensure_ascii=False),"utf-8")
SPEND.write_text(json.dumps(spend), "utf-8")
print("Session spend: ${0} ({1} calls)".format(spend.get("usd",0), spend["calls"]))
