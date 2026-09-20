"""
Fix all CORRUPTED pages: re-extract via Gemini vision at 200 DPI, then RE-VERIFY.
Write only if re-verification = FAITHFUL. Otherwise keep original and mark UNRESOLVED.
Checkpointed. Backs up original page text.
"""
import json, os, re, sys, time, threading
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter

sys.stdout.reconfigure(line_buffering=True)
PROJECT = Path("C:/Users/samsung/Desktop/bac-genius")
TEXTS = PROJECT / "data/processed/texts"
MAIN = PROJECT / "data/processed/verify_all_pages_checkpoint.json"
FIXLOG = PROJECT / "data/processed/fix_corrupted_log.json"
BACKUP = PROJECT / "data/processed/page_backups_prefix.json"
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

def replace_page(content, pn, new_text):
    out=[]; in_t=False
    for line in content.splitlines():
        m=re.match(r"^\[PAGE\s+(\d+)\]", line.strip())
        if m:
            if int(m.group(1))==pn:
                in_t=True; out.append(line); out.append(new_text); continue
            else: in_t=False
        if not in_t: out.append(line)
    return "\n".join(out)

ck = json.loads(MAIN.read_text("utf-8"))
by_key = {r["key"]: r for r in ck["results"]}
targets = [r for r in ck["results"] if r["verdict"]=="CORRUPTED"]

fixlog = {}
if FIXLOG.exists():
    try: fixlog = json.loads(FIXLOG.read_text("utf-8"))
    except: pass
backups = {}
if BACKUP.exists():
    try: backups = json.loads(BACKUP.read_text("utf-8"))
    except: pass
remaining = [r for r in targets if r["key"] not in fixlog]
print("CORRUPTED pages: {0} | already processed: {1} | remaining: {2}".format(len(targets), len(fixlog), len(remaining)))

EXTRACT = """Extract ALL text from this Algerian BAC exam page COMPLETELY and EXACTLY.

CRITICAL:
1. Include EVERY scoring mark in margins and score columns (العلامة / مجزأة / مجموع, e.g. 0.25, 0.5, 3×0.5, 01, 02). Do NOT drop the score column.
2. All numbers, decimals, and totals must be exact.
3. Arabic must be in correct logical (right-to-left reading) order with correct spelling.
4. French/English words must be complete with correct accents.
5. Mathematical formulas in LaTeX ($...$). Fractions, exponents, subscripts, inequalities exact.
6. Preserve question numbering and sub-question order.
7. Render tables as markdown tables including ALL columns.
8. Do NOT omit, summarize, or invent anything.

Output ONLY the extracted text."""

VERIFY = """Compare the PDF page image with the extracted text. Decide if the extracted text is a SEMANTICALLY FAITHFUL representation.

OUTPUT RULES: Do NOT show comparison. At most 6 lines.
Line 1 exactly: SEMANTIC_VERDICT: FAITHFUL   or   SEMANTIC_VERDICT: CORRUPTED
Lines 2-6: only REAL semantic errors (wrong number/score/formula, missing sentence/section/scoring column, invented text, garbled Arabic). "none" if none.
Formatting differences are NOT errors.

EXTRACTED TEXT:
{text}"""

def render(stem, pn, dpi):
    pdf = pdf_by_stem.get(stem)
    if not pdf or not pdf.exists():
        src = ocr.get(stem,{}).get("source_pdf","")
        if src: pdf = PROJECT/src
    pp = ocr.get(stem,{}).get("pdf_pages",[])
    idx = (pp[pn-1]-1) if (pp and len(pp)>=pn) else pn-1
    doc = pymupdf.open(str(pdf)); pix = doc[idx].get_pixmap(dpi=dpi); b = pix.tobytes("png"); doc.close()
    return b

SPEND = PROJECT / "data/processed/api_spend.json"
spend_lock = threading.Lock()
spend = {"in": 0, "out": 0, "calls": 0}
if SPEND.exists():
    try: spend = json.loads(SPEND.read_text("utf-8"))
    except: pass
def record_usage(resp):
    um = getattr(resp, "usage_metadata", None)
    if not um: return
    with spend_lock:
        spend["in"] += um.prompt_token_count or 0
        spend["out"] += (um.candidates_token_count or 0) + (getattr(um, "thoughts_token_count", 0) or 0)
        spend["calls"] += 1
        spend["usd"] = round(spend["in"] * 0.75 / 1e6 + spend["out"] * 3.75 / 1e6, 4)
        if spend["calls"] % 10 == 0:
            SPEND.write_text(json.dumps(spend), "utf-8")

def gcall(contents, max_tokens):
    for attempt in range(4):
        try:
            resp = client.models.generate_content(model=MODEL, contents=contents,
                config=types.GenerateContentConfig(temperature=0.0, max_output_tokens=max_tokens,
                    thinking_config=types.ThinkingConfig(thinking_budget=2000)))
            record_usage(resp)
            return (resp.text or "").strip()
        except Exception as e:
            err=str(e)
            if "429" in err or "RESOURCE_EXHAUSTED" in err: time.sleep(20+attempt*15)
            elif "503" in err or "500" in err: time.sleep(10)
            else: raise
    raise RuntimeError("max retries")

def parse_verdict(rt):
    up=rt[:200].upper()
    if "SEMANTIC_VERDICT: FAITHFUL" in up or "SEMANTIC_VERDICT:FAITHFUL" in up: return "FAITHFUL"
    if "SEMANTIC_VERDICT: CORRUPTED" in up or "SEMANTIC_VERDICT:CORRUPTED" in up: return "CORRUPTED"
    if "FAITHFUL" in up: return "FAITHFUL"
    if "CORRUPTED" in up: return "CORRUPTED"
    return "UNCLEAR"

file_locks = {}
def flock(p):
    with glock:
        if p not in file_locks: file_locks[p]=threading.Lock()
        return file_locks[p]
glock = threading.Lock()

def fix(r):
    key=r["key"]; stem,pn=key.rsplit("__p",1); pn=int(pn); subj=r["subject"]
    txt = TEXTS/subj/(stem+".txt")
    entry = {"key":key, "subject":subj, "original_issue": r["detail"][:400]}
    try:
        img200 = render(stem, pn, 200)
        img150 = render(stem, pn, 150)
    except Exception as e:
        entry.update(status="ERROR", note="render: "+str(e)[:100]); return entry
    with flock(str(txt)):
        content = txt.read_text("utf-8"); pages = parse_pages(content); old = pages.get(pn,"")
    entry["old_len"]=len(old)
    best=None
    for attempt in range(2):
        try:
            new = gcall([Part.from_bytes(data=img200, mime_type="image/png"), EXTRACT], 12000)
        except Exception as e:
            entry.update(status="ERROR", note="extract: "+str(e)[:100]); return entry
        # strip code fences if any
        new = re.sub(r"^```[a-z]*\n?", "", new).strip(); new = re.sub(r"\n?```$", "", new).strip()
        if len(new) < 80:
            entry.setdefault("attempts",[]).append({"len":len(new),"verdict":"TOO_SHORT"}); continue
        try:
            vr = gcall([Part.from_bytes(data=img150, mime_type="image/png"), VERIFY.format(text=new)], 6000)
        except Exception as e:
            entry.update(status="ERROR", note="verify: "+str(e)[:100]); return entry
        v = parse_verdict(vr)
        entry.setdefault("attempts",[]).append({"len":len(new),"verdict":v,"detail":vr[:300]})
        if v=="FAITHFUL":
            best=new; break
        if best is None: best_cand=(new,vr)
    if best is not None:
        with flock(str(txt)):
            content = txt.read_text("utf-8")
            backups[key]=old
            txt.write_text(replace_page(content, pn, best), "utf-8")
        entry.update(status="FIXED_VERIFIED", new_len=len(best))
    else:
        entry.update(status="UNRESOLVED", note="re-extraction did not verify FAITHFUL; original kept")
    return entry

lock=threading.Lock(); n=[0]
def save():
    FIXLOG.write_text(json.dumps(fixlog, indent=1, ensure_ascii=False), "utf-8")
    BACKUP.write_text(json.dumps(backups, indent=0, ensure_ascii=False), "utf-8")

with ThreadPoolExecutor(max_workers=WORKERS) as ex:
    futs=[ex.submit(fix,r) for r in remaining]
    for f in as_completed(futs):
        e=f.result()
        with lock:
            fixlog[e["key"]]=e; n[0]+=1
            if n[0]%10==0:
                save(); cc=Counter(x["status"] for x in fixlog.values())
                print("  {0}/{1} | {2} | spend ${3}".format(n[0], len(remaining), dict(cc), spend.get("usd",0)))
save()
SPEND.write_text(json.dumps(spend), "utf-8")
print("Session spend: ${0} ({1} calls, {2} in, {3} out)".format(spend.get("usd",0), spend["calls"], spend["in"], spend["out"]))
cc=Counter(x["status"] for x in fixlog.values())
print("\nFIX PASS DONE: {0}".format(dict(cc)))
# Update main checkpoint verdicts for fixed pages
for k,e in fixlog.items():
    if e["status"]=="FIXED_VERIFIED" and k in by_key:
        by_key[k]["verdict"]="FAITHFUL"; by_key[k]["detail"]="FIXED+REVERIFIED: "+by_key[k]["detail"][:300]; by_key[k]["fixed"]=True
    elif e["status"]=="UNRESOLVED" and k in by_key:
        by_key[k]["unresolved"]=True
ck["results"]=list(by_key.values()); MAIN.write_text(json.dumps(ck,indent=1,ensure_ascii=False),"utf-8")
print("Main checkpoint updated. Now: {0}".format(dict(Counter(r["verdict"] for r in by_key.values()))))
