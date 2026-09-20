"""Final targeted pass on the last corrupted pages: 300 DPI, LaTeX-safe diff JSON, up to 3 iterative diff rounds,
quarter-page chunk extraction for recitation-blocked pages."""
import json, os, re, sys, time, threading
from pathlib import Path
from collections import Counter

sys.stdout.reconfigure(line_buffering=True)
PROJECT = Path("C:/Users/samsung/Desktop/bac-genius"); TEXTS = PROJECT/"data/processed/texts"
MAIN = PROJECT/"data/processed/verify_all_pages_checkpoint.json"; FIXLOG = PROJECT/"data/processed/fix_corrupted_log.json"
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
SPEND = PROJECT/"data/processed/api_spend.json"; _sl=threading.Lock()
spend = json.loads(SPEND.read_text("utf-8")) if SPEND.exists() else {"in":0,"out":0,"calls":0}
def record_usage(resp):
    um=getattr(resp,"usage_metadata",None)
    if not um: return
    with _sl:
        spend["in"]+=um.prompt_token_count or 0; spend["out"]+=(um.candidates_token_count or 0)+(getattr(um,"thoughts_token_count",0) or 0)
        spend["calls"]+=1; spend["usd"]=round(spend["in"]*0.75/1e6+spend["out"]*3.75/1e6,4); SPEND.write_text(json.dumps(spend),"utf-8")

manifest=json.loads((PROJECT/"data/raw/manifest.json").read_text("utf-8")); ocr=json.loads((PROJECT/"data/processed/ocr_manifest.json").read_text("utf-8"))
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
def get_page(stem,pn):
    pdf=pdf_by_stem.get(stem)
    if not pdf or not pdf.exists():
        src=ocr.get(stem,{}).get("source_pdf",""); pdf=PROJECT/src if src else pdf
    pp=ocr.get(stem,{}).get("pdf_pages",[]); idx=(pp[pn-1]-1) if (pp and len(pp)>=pn) else pn-1
    doc=pymupdf.open(str(pdf)); return doc, doc[idx]
def gcall(contents,max_tokens,budget):
    for a in range(4):
        try:
            resp=client.models.generate_content(model=MODEL,contents=contents,config=types.GenerateContentConfig(temperature=0.0,max_output_tokens=max_tokens,thinking_config=types.ThinkingConfig(thinking_budget=budget)))
            record_usage(resp); fr=str(resp.candidates[0].finish_reason) if resp.candidates else ""
            return (resp.text or "").strip(), fr
        except Exception as e:
            s=str(e)
            if "429" in s or "RESOURCE_EXHAUSTED" in s: time.sleep(20+a*15)
            elif "503" in s or "500" in s: time.sleep(10)
            else: raise
    raise RuntimeError("max retries")
def verdict(rt):
    up=rt[:200].upper()
    if "SEMANTIC_VERDICT: FAITHFUL" in up or "SEMANTIC_VERDICT:FAITHFUL" in up: return "FAITHFUL"
    if "SEMANTIC_VERDICT: CORRUPTED" in up or "SEMANTIC_VERDICT:CORRUPTED" in up: return "CORRUPTED"
    if "FAITHFUL" in up: return "FAITHFUL"
    if "CORRUPTED" in up: return "CORRUPTED"
    return "UNCLEAR"
def parse_json_latex_safe(s):
    s=re.sub(r"^```(?:json)?\s*","",s).strip(); s=re.sub(r"\s*```$","",s).strip()
    m=re.search(r"\[.*\]",s,re.S); s=m.group(0) if m else s
    try: return json.loads(s)
    except Exception: pass
    # escape backslashes that are not valid JSON escapes
    s2=re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', s)
    try: return json.loads(s2)
    except Exception: pass
    try: return json.loads(s2, strict=False)
    except Exception: return []

VERIFY="""Compare the PDF page image with the extracted text. Decide if the extracted text is a SEMANTICALLY FAITHFUL representation.
OUTPUT RULES: Do NOT show comparison. At most 6 lines.
Line 1 exactly: SEMANTIC_VERDICT: FAITHFUL   or   SEMANTIC_VERDICT: CORRUPTED
Lines 2-6: only REAL semantic errors. "none" if none. Formatting differences are NOT errors.

EXTRACTED TEXT:
{text}"""
DIFF="""The extracted text below has a small number of OCR errors. Look VERY carefully at the page image (signs + and -, exponents, subscripts A/B/C, table cells, duplicated passages, missing question numbers) and return ONLY a JSON array of corrections: [{{"wrong": "<exact substring copied from the extracted text>", "right": "<corrected substring>"}}].
Rules: "wrong" must be copied EXACTLY from the extracted text (including LaTeX). To delete a duplicated passage, set "right" to "". To insert missing text, anchor "wrong" on the adjacent existing text and include it plus the insertion in "right". Escape backslashes as \\\\ in JSON strings. Return nothing except the JSON array.
{hint}
EXTRACTED TEXT:
{text}"""
EXTRACT_CHUNK="""Extract ALL text visible in this fragment of an Algerian BAC exam page COMPLETELY and EXACTLY. Keep French accents, § symbols, numbers, question numbering. Output ONLY the extracted text."""

fixlog=json.loads(FIXLOG.read_text("utf-8")); backups=json.loads(BACKUP.read_text("utf-8")) if BACKUP.exists() else {}
ck=json.loads(MAIN.read_text("utf-8")); by={r["key"]:r for r in ck["results"]}
targets=[k for k,e in fixlog.items() if e["status"] in ("UNRESOLVED","PARTIAL_IMPROVED")]
print("Final targeted pass on {0} pages".format(len(targets)))

for key in targets:
    stem,pn=key.rsplit("__p",1); pn=int(pn); subj=by[key]["subject"]; txt=TEXTS/subj/(stem+".txt")
    content=txt.read_text("utf-8"); cur=parse_pages(content).get(pn,""); orig=cur
    e=fixlog[key]; e.setdefault("final_pass",[])
    doc,page=get_page(stem,pn); r=page.rect
    full300=page.get_pixmap(dpi=300).tobytes("png"); full150=page.get_pixmap(dpi=150).tobytes("png")
    hint=""
    if e.get("remaining"): hint="Known remaining issue from a previous check: "+e["remaining"][:300].replace("\n"," ")
    elif e.get("cascade"):
        for c in e["cascade"]:
            if c.get("detail"): hint="Known issue from a previous check: "+c["detail"][:300].replace("\n"," "); break
    done=False
    # Stage 0: recitation-blocked -> quarter chunks
    was_recitation = any("RECITATION" in str(c.get("finish","")) for c in e.get("cascade",[]))
    if was_recitation:
        parts=[]; ok=True
        for i in range(4):
            y0=r.y0+r.height*max(0,i*0.25-0.03); y1=r.y0+r.height*min(1,(i+1)*0.25+0.03)
            b=page.get_pixmap(dpi=220, clip=pymupdf.Rect(r.x0,y0,r.x1,y1)).tobytes("png")
            t,fr=gcall([Part.from_bytes(data=b,mime_type="image/png"),EXTRACT_CHUNK],6000,1200)
            if "RECITATION" in fr or not t: ok=False; e["final_pass"].append({"stage":"quarters","chunk":i,"finish":fr,"len":len(t)}); break
            parts.append(t)
        if ok:
            joined="\n".join(parts).strip()
            vr,_=gcall([Part.from_bytes(data=full150,mime_type="image/png"),VERIFY.format(text=joined)],6000,2500); v=verdict(vr)
            e["final_pass"].append({"stage":"quarters","verdict":v,"len":len(joined),"detail":vr[:250]})
            if v=="FAITHFUL":
                backups.setdefault(key,orig); txt.write_text(replace_page(content,pn,joined),"utf-8"); e["status"]="FIXED_VERIFIED"; e["method"]="quarters"; done=True
            else:
                cur=joined; content=replace_page(content,pn,joined)  # continue into diff rounds on the better text
    # Stage 1-3: iterative LaTeX-safe diffs at 300 DPI
    rounds=0
    while not done and rounds<3:
        rounds+=1
        dj,fr=gcall([Part.from_bytes(data=full300,mime_type="image/png"),DIFF.format(hint=hint,text=cur)],8000,2500)
        if "RECITATION" in fr: e["final_pass"].append({"stage":"diff"+str(rounds),"finish":fr}); break
        corr=parse_json_latex_safe(dj); applied=0; new=cur
        for c in corr if isinstance(corr,list) else []:
            w=c.get("wrong",""); rt=c.get("right","")
            if w and w in new and w!=rt: new=new.replace(w,rt,1); applied+=1
        vr,_=gcall([Part.from_bytes(data=full150,mime_type="image/png"),VERIFY.format(text=new)],6000,2500); v=verdict(vr)
        e["final_pass"].append({"stage":"diff"+str(rounds),"corrections":len(corr) if isinstance(corr,list) else -1,"applied":applied,"verdict":v,"detail":vr[:250]})
        if applied>0 or new!=cur:
            backups.setdefault(key,orig); txt.write_text(replace_page(content,pn,new),"utf-8"); content=replace_page(content,pn,new); cur=new
        if v=="FAITHFUL":
            e["status"]="FIXED_VERIFIED"; e["method"]="diff300_r"+str(rounds); e["new_len"]=len(new); done=True
        else:
            hint="Remaining issue: "+vr[:300].replace("\n"," ")
            if applied==0 and rounds>=2: break
    if not done:
        e["status"]="UNRESOLVED_FINAL"; e["remaining"]=(e["final_pass"][-1].get("detail","") if e["final_pass"] else "")[:300]
    doc.close()
    print("  {0}: {1} ({2})".format(key, e["status"], e.get("method","")))
    FIXLOG.write_text(json.dumps(fixlog,indent=1,ensure_ascii=False),"utf-8"); BACKUP.write_text(json.dumps(backups,indent=0,ensure_ascii=False),"utf-8")

for k,e in fixlog.items():
    if k in by:
        if e["status"]=="FIXED_VERIFIED": by[k]["verdict"]="FAITHFUL"; by[k]["fixed"]=True; by[k].pop("unresolved",None)
        elif e["status"]=="UNRESOLVED_FINAL": by[k]["verdict"]="CORRUPTED"; by[k]["unresolved"]=True; by[k]["detail"]="UNRESOLVED after 3 strategies: "+e.get("remaining","")[:250]
ck["results"]=list(by.values()); MAIN.write_text(json.dumps(ck,indent=1,ensure_ascii=False),"utf-8")
print("\nFINAL PASS:", dict(Counter(fixlog[k]["status"] for k in targets)))
print("ALL PAGES:", dict(Counter(r["verdict"] for r in by.values())))
print("Session spend: ${0} ({1} calls)".format(spend.get("usd",0), spend["calls"]))
