"""
Fallback figure capture for pages whose text carries a [FIGURE ...] placeholder but which still have NO figure
render after build_complete_figures.py (embedded images) and build_vector_figures.py (vector paths).
Causes seen: (a) the graph is an embedded image the classifier labelled EQUATION/TEXTUAL, (b) the whole page is one
scanned image. Strategy: render clusters of ALL embedded images on the page (>=45pt); if the page is a single
full-page scan (or nothing else qualifies) render the full page at 200 DPI. Output *_ffig{k}.png, appended to figures_manifest.json.
"""
import json, re, sys
from pathlib import Path
from collections import defaultdict, Counter
import pymupdf
sys.stdout.reconfigure(line_buffering=True)
P=Path("C:/Users/samsung/Desktop/bac-genius"); T=P/"data/processed/texts"; OUT=P/"data/processed/figures"
manifest=json.loads((P/"data/raw/manifest.json").read_text("utf-8")); ocr=json.loads((P/"data/processed/ocr_manifest.json").read_text("utf-8"))
pdf_by_stem={Path(r["path"]).stem:P/r["path"] for r in manifest if not r.get("duplicate") and r["path"].lower().endswith(".pdf")}
fm=json.loads((P/"data/processed/figures_manifest.json").read_text("utf-8"))
fm["figures"]=[f for f in fm["figures"] if "_ffig" not in f["figure"]]
for old in OUT.rglob("*_ffig*.png"): old.unlink()
have={(f["stem"],f["page"]) for f in fm["figures"]}

def pdf_index(stem,pn):
    pp=ocr.get(stem,{}).get("pdf_pages",[]); return (pp[pn-1]-1) if (pp and len(pp)>=pn) else pn-1
def cluster(rects, gap=14):
    rects=[pymupdf.Rect(r) for r in rects]; changed=True
    while changed:
        changed=False; out=[]
        while rects:
            a=rects.pop(); merged=True
            while merged:
                merged=False
                for i,b in enumerate(rects):
                    if pymupdf.Rect(a.x0-gap,a.y0-gap,a.x1+gap,a.y1+gap).intersects(b): a=a|b; rects.pop(i); merged=True; changed=True; break
            out.append(a)
        rects=out
    return rects

targets=[]
for f in sorted(T.rglob("*.txt")):
    stem=f.stem; cur=0; seen=set()
    for line in f.read_text("utf-8").splitlines():
        m=re.match(r"^\[PAGE\s+(\d+)\]\s*$", line.strip())
        if m: cur=int(m.group(1)); continue
        if "[FIGURE" in line and cur>0 and (stem,cur) not in have and (stem,cur) not in seen: seen.add((stem,cur)); targets.append((stem,cur))
print("placeholder pages without any figure render:",len(targets))
log=[]
for stem,pn in targets:
    subj=stem.split("_")[1]; pdf=pdf_by_stem.get(stem)
    if not pdf: continue
    doc=pymupdf.open(str(pdf)); page=doc[pdf_index(stem,pn)]; pr=page.rect
    rects=[pymupdf.Rect(i["bbox"]) for i in page.get_image_info()]
    rects=[r&pr for r in rects if (r&pr).width>=45 and (r&pr).height>=45]
    clusters=[c for c in cluster(rects) if c.width>=45 and c.height>=45]
    full=[c for c in clusters if c.width>=pr.width*0.85 and c.height>=pr.height*0.85]
    if not clusters or full:
        clips=[pr]; mode="full_page"
    else:
        clips=[pymupdf.Rect(max(pr.x0,c.x0-8),max(pr.y0,c.y0-8),min(pr.x1,c.x1+8),min(pr.y1,c.y1+8)) for c in sorted(clusters,key=lambda c:(c.y0,c.x0))]; mode="image_clusters"
    (OUT/subj).mkdir(exist_ok=True)
    for k,clip in enumerate(clips,1):
        name="{0}_page{1}_ffig{2}.png".format(stem,pn,k)
        page.get_pixmap(dpi=200, clip=clip).save(str(OUT/subj/name))
        fm["figures"].append({"figure":"data/processed/figures/{0}/{1}".format(subj,name),"subject":subj,"stem":stem,"page":pn,
            "source_pdf":str(pdf.relative_to(P)).replace("\\","/"),"pdf_page_index":pdf_index(stem,pn),
            "bbox_pt":[round(clip.x0,1),round(clip.y0,1),round(clip.x1,1),round(clip.y1,1)],"full_page":mode=="full_page","type":"fallback_"+mode})
        log.append({"stem":stem,"page":pn,"figure":name,"mode":mode})
    doc.close(); print(" ",stem,pn,mode,len(clips))
fm["total"]=len(fm["figures"]); fm["fallback_figures"]=len(log); fm["pages_covered"]=len({(f["stem"],f["page"]) for f in fm["figures"]})
(P/"data/processed/figures_manifest.json").write_text(json.dumps(fm,indent=1,ensure_ascii=False),"utf-8")
(P/"data/processed/fallback_figures_log.json").write_text(json.dumps(log,indent=1,ensure_ascii=False),"utf-8")
print("fallback figures:",len(log),"| by mode:",dict(Counter(l["mode"] for l in log)),"| figures total:",fm["total"],"| pages covered:",fm["pages_covered"])
