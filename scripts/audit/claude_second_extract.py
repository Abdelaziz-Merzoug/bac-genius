"""
Independent second extraction with Claude Sonnet 5 on all Gemini-re-extracted pages.
For each page: Claude lists every formula/number from the image → normalized fuzzy-match against
the LaTeX/numbers in the current text → pages with unmatched items are flagged for visual adjudication.
Checkpointed, spend-tracked, hard budget cap.
"""
import os, sys, json, base64, re, time, threading, difflib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
import anthropic, pymupdf

sys.stdout.reconfigure(line_buffering=True)
P = Path("C:/Users/samsung/Desktop/bac-genius"); T = P/"data/processed/texts"
CK = P/"data/processed/claude_second_extract_checkpoint.json"
MODEL = "claude-sonnet-5"; PRICE_IN, PRICE_OUT = 2.0, 10.0
BUDGET_USD = 4.40; WORKERS = 4

for line in (P/".env").read_text("utf-8").splitlines():
    line=line.strip()
    if line and not line.startswith("#") and "=" in line:
        k,_,v=line.partition("="); os.environ.setdefault(k.strip(), v.strip())
client = anthropic.Anthropic(max_retries=4)

manifest=json.loads((P/"data/raw/manifest.json").read_text("utf-8")); ocr=json.loads((P/"data/processed/ocr_manifest.json").read_text("utf-8"))
pdf={Path(r["path"]).stem:P/r["path"] for r in manifest if not r.get("duplicate") and r["path"].lower().endswith(".pdf")}
fl=json.loads((P/"data/processed/fix_corrupted_log.json").read_text("utf-8"))
targets=sorted(k for k,e in fl.items() if e["status"].startswith("FIXED"))
print("Target pages:", len(targets))

def parse_pages(c):
    pages={}; cur=0; lines=[]
    for line in c.splitlines():
        m=re.match(r"^\[PAGE\s+(\d+)\]\s*$", line.strip())
        if m:
            if cur>0: pages[cur]="\n".join(lines).strip()
            cur=int(m.group(1)); lines=[]
        else:
            if cur>0: lines.append(line)
    if cur>0: pages[cur]="\n".join(lines).strip()
    return pages

PROMPT = """This is a page from an Algerian BAC exam or its official answer key.
Transcribe EVERY mathematical/scientific expression and every number that appears on the page, as LaTeX, one per line, in reading order.
Include: equations, inequalities, limits, fractions, exponents, roots, vectors, intervals, numeric values with units, scoring marks (0.25, 0.5, 2×0.25 ...), isotope notation, chemical equations.
Exclude: prose, headers, page numbers. Do not explain. Do not correct anything — transcribe exactly what is printed, even if it looks mathematically wrong.
Output only the list."""

def norm(s):
    s=s.strip().strip("$").strip()
    s=s.replace("\\dfrac","\\frac").replace("\\left","").replace("\\right","").replace("\\displaystyle","").replace("\\,","").replace("\\;","").replace("\\!","")
    s=s.replace("\\text{","{").replace("\\mathrm{","{").replace("\\mathbb{","{").replace("\\overrightarrow","\\vec").replace("\\overline","\\bar")
    s=re.sub(r"\\(?:quad|qquad|cdot|times)",lambda m:{"\\cdot":"*","\\times":"*"}.get(m.group(0),""),s)
    s=s.replace("×","*").replace("·","*").replace("−","-").replace("–","-").replace("≈","=").replace("\\approx","=").replace("\\simeq","=").replace("≃","=")
    s=s.replace(",",".")  # decimal comma
    s=re.sub(r"\s+","",s)
    s=re.sub(r"\{([^{}])\}",r"\1",s)  # {x} -> x for single chars
    return s

def key_tokens(s):
    """Extract the discriminating atoms: numbers, signs adjacent to numbers/variables, exponents, subscripts."""
    n=norm(s)
    nums=re.findall(r"-?\d+(?:\.\d+)?",n)
    exps=re.findall(r"\^\{?[^{}\s]{1,12}\}?",n)
    subs=re.findall(r"_\{?[^{}\s]{1,8}\}?",n)
    return nums, exps, subs

def page_corpus(text):
    forms=[norm(m.group(1)) for m in re.finditer(r"\$\$?([^$]{1,300})\$\$?", text)]
    whole=norm(text)
    return forms, whole

def match(item, forms, whole):
    """Return (matched:bool, best_ratio)."""
    ni=norm(item)
    if len(ni)<2: return True, 1.0
    if ni in whole: return True, 1.0
    best=0.0
    for f in forms:
        if ni in f or f in ni and len(f)>=max(4,len(ni)//2): return True, 1.0
        r=difflib.SequenceMatcher(None, ni, f).ratio()
        if r>best: best=r
    # numeric-only items (scores, values): check presence of the number
    nums,exps,subs=key_tokens(item)
    if nums and not exps and not subs and len(ni)<=8:
        return all(n in whole for n in nums), best
    return best>=0.92, best

spend={"in":0,"out":0,"calls":0,"usd":0.0}
lock=threading.Lock()
done={}
if CK.exists():
    try:
        d=json.loads(CK.read_text("utf-8")); done={r["key"]:r for r in d["results"]}; spend=d.get("spend",spend)
    except: pass
remaining=[k for k in targets if k not in done]
print("Done:",len(done),"| remaining:",len(remaining),"| spend so far: ${:.3f}".format(spend["usd"]))

def render(stem,pn):
    pp=ocr.get(stem,{}).get("pdf_pages",[]); idx=(pp[pn-1]-1) if (pp and len(pp)>=pn) else pn-1
    doc=pymupdf.open(str(pdf[stem])); b=doc[idx].get_pixmap(dpi=150).tobytes("png"); doc.close(); return b

def work(key):
    stem,pn=key.rsplit("__p",1); pn=int(pn); subj=stem.split("_")[1]
    with lock:
        if spend["usd"]>=BUDGET_USD: return {"key":key,"status":"BUDGET_STOP"}
    try: png=render(stem,pn)
    except Exception as e: return {"key":key,"status":"ERROR","err":"render "+str(e)[:80]}
    b64=base64.standard_b64encode(png).decode()
    try:
        resp=client.messages.create(model=MODEL,max_tokens=4000,thinking={"type":"adaptive"},output_config={"effort":"low"},
            messages=[{"role":"user","content":[{"type":"image","source":{"type":"base64","media_type":"image/png","data":b64}},{"type":"text","text":PROMPT}]}])
    except anthropic.APIStatusError as e:
        return {"key":key,"status":"ERROR","err":"api {} {}".format(e.status_code,str(e)[:80])}
    except Exception as e:
        return {"key":key,"status":"ERROR","err":str(e)[:100]}
    u=resp.usage; c=u.input_tokens*PRICE_IN/1e6+u.output_tokens*PRICE_OUT/1e6
    with lock:
        spend["in"]+=u.input_tokens; spend["out"]+=u.output_tokens; spend["calls"]+=1; spend["usd"]=round(spend["usd"]+c,4)
    text="".join(b.text for b in resp.content if b.type=="text")
    items=[l.strip() for l in text.splitlines() if l.strip() and len(l.strip())>1]
    cur=parse_pages((T/subj/(stem+".txt")).read_text("utf-8")).get(pn,"")
    forms,whole=page_corpus(cur)
    unmatched=[]
    for it in items:
        ok,r=match(it,forms,whole)
        if not ok: unmatched.append({"claude":it,"best":round(r,2)})
    return {"key":key,"subject":subj,"status":"OK","n_items":len(items),"n_unmatched":len(unmatched),"unmatched":unmatched[:25],"cost":round(c,4),"stop":resp.stop_reason}

def save():
    CK.write_text(json.dumps({"results":list(done.values()),"spend":spend,"model":MODEL},indent=1,ensure_ascii=False),"utf-8")

n=0
with ThreadPoolExecutor(max_workers=WORKERS) as ex:
    futs={ex.submit(work,k):k for k in remaining}
    for f in as_completed(futs):
        r=f.result()
        with lock:
            done[r["key"]]=r; n+=1
            if n%20==0:
                save(); st=Counter(x["status"] for x in done.values()); fl_=sum(1 for x in done.values() if x.get("n_unmatched",0)>0)
                print("  {0}/{1} | {2} | flagged {3} | ${4:.3f}".format(len(done),len(targets),dict(st),fl_,spend["usd"]))
            if spend["usd"]>=BUDGET_USD:
                print("BUDGET CAP reached at ${:.3f}".format(spend["usd"]))
save()
st=Counter(x["status"] for x in done.values()); flagged=[x for x in done.values() if x.get("n_unmatched",0)>0]
print("\nDONE {0}/{1} | {2} | spend ${3:.3f} ({4} calls)".format(len(done),len(targets),dict(st),spend["usd"],spend["calls"]))
print("Pages with unmatched items:", len(flagged))
by=Counter(x["subject"] for x in flagged); print("  by subject:", dict(by))
