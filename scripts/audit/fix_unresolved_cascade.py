"""
Cascade for UNRESOLVED pages (mostly recitation-blocked):
  A) extract top/bottom halves separately at 200 DPI, join, verify
  B) corrections-only diff: model returns JSON [{"wrong":..., "right":...}], apply to old text, verify
Writes only if verify=FAITHFUL.
"""
import json, os, re, sys, time, threading
from pathlib import Path
from collections import Counter

sys.stdout.reconfigure(line_buffering=True)
PROJECT = Path("C:/Users/samsung/Desktop/bac-genius")
TEXTS = PROJECT/"data/processed/texts"
MAIN = PROJECT/"data/processed/verify_all_pages_checkpoint.json"
FIXLOG = PROJECT/"data/processed/fix_corrupted_log.json"
BACKUP = PROJECT/"data/processed/page_backups_prefix.json"

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
def replace_page(content,pn,new):
    out=[]; in_t=False
    for line in content.splitlines():
        m=re.match(r"^\[PAGE\s+(\d+)\]", line.strip())
        if m:
            if int(m.group(1))==pn: in_t=True; out.append(line); out.append(new); continue
            else: in_t=False
        if not in_t: out.append(line)
    return "\n".join(out)
def page_pix(stem,pn,dpi):
    pdf=pdf_by_stem.get(stem)
    if not pdf or not pdf.exists():
        src=ocr.get(stem,{}).get("source_pdf","");  pdf=PROJECT/src if src else pdf
    pp=ocr.get(stem,{}).get("pdf_pages",[]); idx=(pp[pn-1]-1) if (pp and len(pp)>=pn) else pn-1
    doc=pymupdf.open(str(pdf)); page=doc[idx]; r=page.rect
    full=page.get_pixmap(dpi=dpi).tobytes("png")
    top=page.get_pixmap(dpi=dpi, clip=pymupdf.Rect(r.x0,r.y0,r.x1,r.y0+r.height*0.55)).tobytes("png")
    bot=page.get_pixmap(dpi=dpi, clip=pymupdf.Rect(r.x0,r.y0+r.height*0.45,r.x1,r.y1)).tobytes("png")
    doc.close(); return full,top,bot
def gcall(contents,max_tokens,budget):
    last=None
    for a in range(4):
        try:
            resp=client.models.generate_content(model=MODEL,contents=contents,
                config=types.GenerateContentConfig(temperature=0.0,max_output_tokens=max_tokens,thinking_config=types.ThinkingConfig(thinking_budget=budget)))
            record_usage(resp)
            fr=str(resp.candidates[0].finish_reason) if resp.candidates else ""
            return (resp.text or "").strip(), fr
        except Exception as e:
            s=str(e); last=s
            if "429" in s or "RESOURCE_EXHAUSTED" in s: time.sleep(20+a*15)
            elif "503" in s or "500" in s: time.sleep(10)
            else: raise
    raise RuntimeError(last or "max retries")
def verdict(rt):
    up=rt[:200].upper()
    if "SEMANTIC_VERDICT: FAITHFUL" in up or "SEMANTIC_VERDICT:FAITHFUL" in up: return "FAITHFUL"
    if "SEMANTIC_VERDICT: CORRUPTED" in up or "SEMANTIC_VERDICT:CORRUPTED" in up: return "CORRUPTED"
    if "FAITHFUL" in up: return "FAITHFUL"
    if "CORRUPTED" in up: return "CORRUPTED"
    return "UNCLEAR"

EXTRACT="""Extract ALL text from this portion of an Algerian BAC exam page COMPLETELY and EXACTLY (it is a fragment of a page; extract what is visible). Include every scoring mark, number, symbol (§, /s/, etc.), Arabic header/footer text in correct order, and all question text. Output ONLY the extracted text."""
DIFF="""The extracted text below has OCR errors. Compare with the page image and return ONLY a JSON array of corrections, each {{"wrong": "<exact substring in extracted text>", "right": "<corrected substring>"}}. Include every real error: wrong numbers, garbled words, wrong symbols (e.g. $1 should be §1), garbled Arabic header/footer, missing short lines (use "wrong": "" is NOT allowed — instead anchor on an adjacent substring and include the missing text in "right"). Do not return anything except the JSON array.

EXTRACTED TEXT:
{text}"""
VERIFY="""Compare the PDF page image with the extracted text. Decide if the extracted text is a SEMANTICALLY FAITHFUL representation.
OUTPUT RULES: Do NOT show comparison. At most 6 lines.
Line 1 exactly: SEMANTIC_VERDICT: FAITHFUL   or   SEMANTIC_VERDICT: CORRUPTED
Lines 2-6: only REAL semantic errors. "none" if none. Formatting differences are NOT errors.

EXTRACTED TEXT:
{text}"""

fixlog=json.loads(FIXLOG.read_text("utf-8"))
backups=json.loads(BACKUP.read_text("utf-8")) if BACKUP.exists() else {}
ck=json.loads(MAIN.read_text("utf-8")); by_key={r["key"]:r for r in ck["results"]}
targets=[k for k,e in fixlog.items() if e["status"]=="UNRESOLVED"]
print("UNRESOLVED to cascade: {0}".format(len(targets)))

for key in targets:
    stem,pn=key.rsplit("__p",1); pn=int(pn); subj=by_key[key]["subject"]; txt=TEXTS/subj/(stem+".txt")
    content=txt.read_text("utf-8"); old=parse_pages(content).get(pn,"")
    e=fixlog[key]; e.setdefault("cascade",[])
    try: full,top,bot=page_pix(stem,pn,200)
    except Exception as ex: e["cascade"].append({"stage":"render","err":str(ex)[:100]}); continue
    done=False
    # Stage A: halves
    try:
        t1,f1=gcall([Part.from_bytes(data=top,mime_type="image/png"),EXTRACT],8000,1500)
        t2,f2=gcall([Part.from_bytes(data=bot,mime_type="image/png"),EXTRACT],8000,1500)
        joined=(t1+"\n"+t2).strip()
        e["cascade"].append({"stage":"A_halves","len":len(joined),"finish":[f1,f2]})
        if len(joined)>=0.5*len(old) and len(joined)>80:
            vr,_=gcall([Part.from_bytes(data=full,mime_type="image/png"),VERIFY.format(text=joined)],6000,2500)
            v=verdict(vr); e["cascade"][-1]["verdict"]=v; e["cascade"][-1]["detail"]=vr[:250]
            if v=="FAITHFUL":
                backups[key]=old; txt.write_text(replace_page(content,pn,joined),"utf-8")
                e["status"]="FIXED_VERIFIED"; e["method"]="halves"; e["new_len"]=len(joined); done=True
    except Exception as ex: e["cascade"].append({"stage":"A_halves","err":str(ex)[:120]})
    # Stage B: diff
    if not done:
        try:
            dj,fr=gcall([Part.from_bytes(data=full,mime_type="image/png"),DIFF.format(text=old)],6000,2000)
            dj=re.sub(r"^```(?:json)?\s*","",dj).strip(); dj=re.sub(r"\s*```$","",dj).strip()
            m=re.search(r"\[.*\]",dj,re.S); corr=json.loads(m.group(0)) if m else []
            applied=0; new=old
            for c in corr:
                w=c.get("wrong",""); r=c.get("right","")
                if w and w in new and w!=r: new=new.replace(w,r); applied+=1
            e["cascade"].append({"stage":"B_diff","corrections":len(corr),"applied":applied,"finish":fr})
            if applied>0:
                vr,_=gcall([Part.from_bytes(data=full,mime_type="image/png"),VERIFY.format(text=new)],6000,2500)
                v=verdict(vr); e["cascade"][-1]["verdict"]=v; e["cascade"][-1]["detail"]=vr[:250]
                if v=="FAITHFUL":
                    backups[key]=old; txt.write_text(replace_page(content,pn,new),"utf-8")
                    e["status"]="FIXED_VERIFIED"; e["method"]="diff"; e["new_len"]=len(new); done=True
                elif applied>=1:
                    # partial improvement: keep improved text but leave status UNRESOLVED_IMPROVED
                    backups[key]=old; txt.write_text(replace_page(content,pn,new),"utf-8")
                    e["status"]="PARTIAL_IMPROVED"; e["method"]="diff"; e["new_len"]=len(new); e["remaining"]=vr[:250]
        except Exception as ex: e["cascade"].append({"stage":"B_diff","err":str(ex)[:120]})
    print("  {0}: {1}".format(key, e["status"]))
    FIXLOG.write_text(json.dumps(fixlog,indent=1,ensure_ascii=False),"utf-8")
    BACKUP.write_text(json.dumps(backups,indent=0,ensure_ascii=False),"utf-8")
    time.sleep(1)

for k,e in fixlog.items():
    if k in by_key:
        if e["status"]=="FIXED_VERIFIED": by_key[k]["verdict"]="FAITHFUL"; by_key[k]["fixed"]=True; by_key[k].pop("unresolved",None)
        elif e["status"] in ("UNRESOLVED","PARTIAL_IMPROVED"): by_key[k]["unresolved"]=True
ck["results"]=list(by_key.values()); MAIN.write_text(json.dumps(ck,indent=1,ensure_ascii=False),"utf-8")
print("\nCASCADE DONE:", dict(Counter(fixlog[k]["status"] for k in targets)))
print("ALL PAGES:", dict(Counter(r["verdict"] for r in by_key.values())))
SPEND.write_text(json.dumps(spend), "utf-8")
print("Session spend: ${0} ({1} calls)".format(spend.get("usd",0), spend["calls"]))
