"""Independent final re-verification of every page that was rewritten by a fix. 2 workers, spend-tracked."""
import json, os, re, sys, time, threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter

sys.stdout.reconfigure(line_buffering=True)
PROJECT = Path("C:/Users/samsung/Desktop/bac-genius"); TEXTS = PROJECT/"data/processed/texts"
MAIN = PROJECT/"data/processed/verify_all_pages_checkpoint.json"
OUT = PROJECT/"data/processed/final_reverify_fixed.json"
WORKERS = 2
for line in (PROJECT/".env").read_text("utf-8").splitlines():
    line=line.strip()
    if line and not line.startswith("#") and "=" in line:
        k,_,v=line.partition("="); os.environ.setdefault(k.strip(), v.strip())
from google import genai
from google.genai import types
from google.genai.types import Part
import pymupdf
client=genai.Client(api_key=os.environ["GOOGLE_API_KEY"]); MODEL="models/gemini-3.6-flash"

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

manifest=json.loads((PROJECT/"data/raw/manifest.json").read_text("utf-8"))
ocr=json.loads((PROJECT/"data/processed/ocr_manifest.json").read_text("utf-8"))
pdf_by_stem={Path(r["path"]).stem:PROJECT/r["path"] for r in manifest if not r.get("duplicate")}
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

ck=json.loads(MAIN.read_text("utf-8")); by={r["key"]:r for r in ck["results"]}
fl=json.loads((PROJECT/"data/processed/fix_corrupted_log.json").read_text("utf-8"))
targets=[k for k,e in fl.items() if e["status"] in ("FIXED_VERIFIED","PARTIAL_IMPROVED")]
done={}
if OUT.exists():
    try: done={r["key"]:r for r in json.loads(OUT.read_text("utf-8")).get("results",[])}
    except: pass
remaining=[k for k in targets if k not in done]
print("Fixed pages to independently re-verify: {0} | done {1} | remaining {2}".format(len(targets), len(done), len(remaining)))

VERIFY="""Compare the PDF page image with the extracted text. Decide if the extracted text is a SEMANTICALLY FAITHFUL representation.
OUTPUT RULES: Do NOT show comparison. At most 6 lines.
Line 1 exactly: SEMANTIC_VERDICT: FAITHFUL   or   SEMANTIC_VERDICT: CORRUPTED
Lines 2-6: only REAL semantic errors (wrong number/score/formula, missing sentence/section/scoring column, invented text, garbled Arabic). "none" if none.
Formatting differences (whitespace, table layout, LaTeX vs visual math, header order) are NOT errors.

EXTRACTED TEXT:
{text}"""

def rv(key):
    stem,pn=key.rsplit("__p",1); pn=int(pn); subj=by[key]["subject"]
    text=parse_pages((TEXTS/subj/(stem+".txt")).read_text("utf-8")).get(pn,"")
    pdf=pdf_by_stem.get(stem)
    if not pdf or not pdf.exists():
        src=ocr.get(stem,{}).get("source_pdf",""); pdf=PROJECT/src if src else pdf
    pp=ocr.get(stem,{}).get("pdf_pages",[]); idx=(pp[pn-1]-1) if (pp and len(pp)>=pn) else pn-1
    try:
        doc=pymupdf.open(str(pdf)); img=doc[idx].get_pixmap(dpi=150).tobytes("png"); doc.close()
    except Exception as e:
        return {"key":key,"subject":subj,"is_exam":by[key]["is_exam"],"verdict":"ERROR","detail":str(e)[:100]}
    for a in range(4):
        try:
            resp=client.models.generate_content(model=MODEL,contents=[Part.from_bytes(data=img,mime_type="image/png"),VERIFY.format(text=text)],
                config=types.GenerateContentConfig(temperature=0.0,max_output_tokens=6000,thinking_config=types.ThinkingConfig(thinking_budget=2500)))
            record_usage(resp)
            rt=(resp.text or "").strip(); up=rt[:200].upper()
            v="FAITHFUL" if ("SEMANTIC_VERDICT: FAITHFUL" in up or "SEMANTIC_VERDICT:FAITHFUL" in up) else ("CORRUPTED" if "CORRUPTED" in up else ("FAITHFUL" if "FAITHFUL" in up else "UNCLEAR"))
            return {"key":key,"subject":subj,"is_exam":by[key]["is_exam"],"verdict":v,"detail":rt[:500]}
        except Exception as e:
            s=str(e)
            if "429" in s or "RESOURCE_EXHAUSTED" in s: time.sleep(20+a*15)
            elif "503" in s or "500" in s: time.sleep(10)
            else: return {"key":key,"subject":subj,"is_exam":by[key]["is_exam"],"verdict":"ERROR","detail":s[:100]}
    return {"key":key,"subject":subj,"is_exam":by[key]["is_exam"],"verdict":"ERROR","detail":"max retries"}

lock=threading.Lock(); results=list(done.values()); n=[0]
def save(): OUT.write_text(json.dumps({"results":results},indent=1,ensure_ascii=False),"utf-8")
with ThreadPoolExecutor(max_workers=WORKERS) as ex:
    for f in as_completed([ex.submit(rv,k) for k in remaining]):
        r=f.result()
        with lock:
            results.append(r); done[r["key"]]=r; n[0]+=1
            if n[0]%25==0:
                save(); print("  {0}/{1} | {2} | spend ${3}".format(len(done),len(targets),dict(Counter(x["verdict"] for x in results)),spend.get("usd",0)))
save()
cc=Counter(x["verdict"] for x in results)
print("\nFINAL RE-VERIFY DONE {0}/{1}: {2}".format(len(done),len(targets),dict(cc)))
# sync main checkpoint: any fixed page that fails independent re-verify goes back to CORRUPTED
regress=0
for r in results:
    if r["verdict"]=="CORRUPTED" and r["key"] in by:
        by[r["key"]]["verdict"]="CORRUPTED"; by[r["key"]]["reverify_failed"]=True; by[r["key"]]["detail"]="REVERIFY FAILED: "+r["detail"][:300]; regress+=1
    elif r["verdict"]=="FAITHFUL" and r["key"] in by:
        by[r["key"]]["independently_reverified"]=True
ck["results"]=list(by.values()); MAIN.write_text(json.dumps(ck,indent=1,ensure_ascii=False),"utf-8")
print("Regressions on independent re-verify: {0}".format(regress))
print("ALL PAGES:", dict(Counter(r["verdict"] for r in by.values())))
SPEND.write_text(json.dumps(spend), "utf-8")
print("Session spend: ${0} ({1} calls)".format(spend.get("usd",0), spend["calls"]))
