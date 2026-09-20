"""Render the i-th remaining disagreement page (ranked) + print Claude's unmatched items and a text excerpt.
usage: adj_show.py <i> [dpi] [--text]"""
import json, sys, re
from pathlib import Path
import pymupdf
P=Path("C:/Users/samsung/Desktop/bac-genius"); T=P/"data/processed/texts"
OUT=Path(r"C:\Users\samsung\AppData\Local\Temp\claude\C--Users-samsung-Desktop-bac-genius\080f53e8-a8e9-440e-a559-c5a8bdcc0ca4\scratchpad\adj2"); OUT.mkdir(exist_ok=True)
manifest=json.loads((P/"data/raw/manifest.json").read_text("utf-8")); ocr=json.loads((P/"data/processed/ocr_manifest.json").read_text("utf-8"))
pdf={Path(r["path"]).stem:P/r["path"] for r in manifest if not r.get("duplicate") and r["path"].lower().endswith(".pdf")}
adj={a["key"]:a for a in json.loads((P/"data/processed/claude_adjudication_list.json").read_text("utf-8"))}
rank=json.loads((P/"data/processed/adj_rank2.json").read_text("utf-8"))
order=[r["key"] for r in rank]+[k for k in adj if k not in {r["key"] for r in rank}]
FIXED={"bac_svt_2016_sujet1_session1__p2","bac_svt_2016_sujet1_solution_session1__p1","bac_svt_2016_sujet2_solution_session1__p5",
       "bac_physic_2013_sujet1_solution__p2","bac_physic_2013_sujet1_solution__p3","bac_physic_2011_sujet2_solution__p1"}
LOG=P/"data/processed/adjudication_visual_log.json"
done={l["key"] for l in json.loads(LOG.read_text("utf-8"))} if LOG.exists() else set()
remaining=[k for k in order if k not in FIXED and k not in done]
if len(sys.argv)<2 or sys.argv[1]=="list":
    print("remaining:",len(remaining))
    for i,k in enumerate(remaining): print(i,k,adj[k]["n_real"],"numeric_only" if adj[k]["numeric_only"] else "")
    sys.exit()
i=int(sys.argv[1]); dpi=int(sys.argv[2]) if len(sys.argv)>2 and sys.argv[2].isdigit() else 100
key=remaining[i]; a=adj[key]; stem,pn=key.rsplit("__p",1); pn=int(pn); subj=stem.split("_")[1]
pp=ocr.get(stem,{}).get("pdf_pages",[]); idx=(pp[pn-1]-1) if (pp and len(pp)>=pn) else pn-1
doc=pymupdf.open(str(pdf[stem])); pix=doc[idx].get_pixmap(dpi=dpi); out=OUT/(key+".png"); pix.save(str(out)); doc.close()
print("KEY:",key,"| n_real:",a["n_real"],"| numeric_only:",a["numeric_only"],"|",out.name,pix.width,pix.height)
for it in a["items"]: print("  -",it["claude"][:110],"| missing:",it["missing"][:8])
if "--text" in sys.argv:
    c=(T/subj/(stem+".txt")).read_text("utf-8"); pages={}; cur=0; lines=[]
    for line in c.splitlines():
        m=re.match(r"^\[PAGE\s+(\d+)\]\s*$", line.strip())
        if m:
            if cur>0: pages[cur]="\n".join(lines)
            cur=int(m.group(1)); lines=[]
        else:
            if cur>0: lines.append(line)
    if cur>0: pages[cur]="\n".join(lines)
    print("---- TEXT ----"); print(pages.get(pn,"")[:6000])
