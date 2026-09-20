import json, re, random
from pathlib import Path
import pymupdf
P=Path("C:/Users/samsung/Desktop/bac-genius")
SP=Path(r"C:\Users\samsung\AppData\Local\Temp\claude\C--Users-samsung-Desktop-bac-genius\080f53e8-a8e9-440e-a559-c5a8bdcc0ca4\scratchpad")
OUT=SP/"insp2"; OUT.mkdir(exist_ok=True)
ck=json.loads((P/"data/processed/verify_all_pages_checkpoint.json").read_text("utf-8")); res=ck["results"]
fl=json.loads((P/"data/processed/fix_corrupted_log.json").read_text("utf-8")); fixed=set(k for k,e in fl.items() if e["status"].startswith("FIXED"))
done=set(m["key"] for m in json.loads((SP/"insp"/"meta.json").read_text()))
T=P/"data/processed/texts"
def page_text(subj,stem,pn):
    c=(T/subj/(stem+".txt")).read_text("utf-8"); pages={}; cur=0; lines=[]
    for line in c.splitlines():
        m=re.match(r"^\[PAGE\s+(\d+)\]", line.strip())
        if m:
            if cur>0: pages[cur]="\n".join(lines).strip()
            cur=int(m.group(1)); lines=[]
        else:
            if cur>0: lines.append(line)
    if cur>0: pages[cur]="\n".join(lines).strip()
    return pages[pn]
cands=[]
for r in res:
    if r["subject"] in ("math","physic") and r["key"] in fixed and r["key"] not in done:
        stem,pn=r["key"].rsplit("__p",1); t=page_text(r["subject"],stem,int(pn))
        density=t.count("\\")+t.count("^")+t.count("_{")
        cands.append((density, r["key"], r["subject"], r["is_exam"]))
cands.sort(reverse=True)
rng=random.Random(918)
sol=[c for c in cands if not c[3]][:40]; ex=[c for c in cands if c[3]][:20]
sel=rng.sample(sol,14)+rng.sample(ex,6)
manifest=json.loads((P/"data/raw/manifest.json").read_text("utf-8")); ocr=json.loads((P/"data/processed/ocr_manifest.json").read_text("utf-8"))
pdf={Path(r["path"]).stem:P/r["path"] for r in manifest if not r.get("duplicate") and r["path"].lower().endswith(".pdf")}
meta=[]
for i,(dens,key,subj,is_exam) in enumerate(sel):
    stem,pn=key.rsplit("__p",1); pn=int(pn)
    pp=ocr.get(stem,{}).get("pdf_pages",[]); idx=(pp[pn-1]-1) if (pp and len(pp)>=pn) else pn-1
    doc=pymupdf.open(str(pdf[stem])); doc[idx].get_pixmap(dpi=170).save(str(OUT/("{0:02d}.png".format(i)))); doc.close()
    t=page_text(subj,stem,pn)
    forms=[]; seen=set()
    for m in re.finditer(r"\$\$?([^$]{3,200})\$\$?", t):
        f=m.group(1).strip()
        if f not in seen: seen.add(f); forms.append(f)
    (OUT/("{0:02d}.txt".format(i))).write_text(t,"utf-8")
    (OUT/("{0:02d}_formulas.txt".format(i))).write_text("\n".join(forms),"utf-8")
    meta.append({"i":i,"key":key,"subject":subj,"exam":is_exam,"density":dens,"n_formulas":len(forms)})
json.dump(meta,open(OUT/"meta.json","w"),indent=1)
for m in meta: print("  {0:02d} {1:52s} {2} dens={3} formulas={4}".format(m["i"],m["key"],"EXAM" if m["exam"] else "SOLN",m["density"],m["n_formulas"]))
