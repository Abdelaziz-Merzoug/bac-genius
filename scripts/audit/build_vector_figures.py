"""
Capture VECTOR-DRAWN figures (graphs, curves, diagrams drawn as PDF paths, not embedded images).
build_complete_figures.py only clustered embedded-image bboxes, so pages whose graphs are vector paths
(most 2016+ digital physics/math/svt PDFs) had NO saved figure. This pass:
  1. scans every text page of every unique PDF for "graphic" drawing paths (bezier curves, diagonal
     segments, small filled markers) — straight axis-aligned lines alone (table borders) do not qualify;
  2. clusters graphic paths together with nearby straight paths (axes, grid) into figure regions;
  3. skips regions already covered >=60% by an existing embedded-image figure render;
  4. renders each region at 200 DPI to figures/{subject}/{stem}_page{n}_vfig{k}.png and appends to figures_manifest.json.
usage: python scripts/audit/build_vector_figures.py [--dry]
"""
import json, re, sys
from pathlib import Path
from collections import defaultdict, Counter
import pymupdf

sys.stdout.reconfigure(line_buffering=True)
P = Path("C:/Users/samsung/Desktop/bac-genius"); T = P/"data/processed/texts"; OUT = P/"data/processed/figures"
DRY = "--dry" in sys.argv
manifest=json.loads((P/"data/raw/manifest.json").read_text("utf-8")); ocr=json.loads((P/"data/processed/ocr_manifest.json").read_text("utf-8"))
pdf_by_stem={Path(r["path"]).stem:P/r["path"] for r in manifest if not r.get("duplicate") and r["path"].lower().endswith(".pdf")}
fm=json.loads((P/"data/processed/figures_manifest.json").read_text("utf-8"))
existing=defaultdict(list)
for f in fm["figures"]:
    if "_vfig" in f["figure"] or "_ffig" in f["figure"]: continue   # only embedded-image figures (and manual _mfig) count as prior coverage
    existing[(f["stem"],f["page"])].append(pymupdf.Rect(f["bbox_pt"]))
fm["figures"]=[f for f in fm["figures"] if "_vfig" not in f["figure"] and "_ffig" not in f["figure"]]  # vector + fallback entries are rebuilt
if not DRY:
    for old in OUT.rglob("*_vfig*.png"): old.unlink()

MIN_GRAPHIC=12     # graphic segments needed for a cluster (>=20pt paths); short-segment-only clusters need MIN_SHORT
MIN_SHORT=30
# Reviewed visually (contact sheets, 2026-09-18): false positives (formulas/text drawn as paths, score strip) and fragments
# superseded by a merged manual render (*_mfig*.png, kept outside this script). Never re-emit these.
EXCLUDE={"bac_math_2023_sujet2_solution_page1_vfig1.png","bac_math_2023_sujet2_solution_page2_vfig1.png",
         "bac_physic_2017_sujet2_solution_session2_page3_vfig1.png","bac_physic_2022_sujet2_solution_page2_vfig1.png",
         "bac_svt_2019_sujet1_solution_page5_vfig1.png","bac_svt_2019_sujet2_page2_vfig2.png","bac_svt_2019_sujet2_page2_vfig3.png",
         "bac_svt_2019_sujet2_page2_vfig4.png","bac_svt_2026_sujet2_solution_page6_vfig1.png","bac_svt_2026_sujet2_solution_page6_vfig2.png"}
GAP=16             # pt merge distance
MIN_SIZE=45        # pt minimum figure side

def pdf_index(stem,pn):
    pp=ocr.get(stem,{}).get("pdf_pages",[]); return (pp[pn-1]-1) if (pp and len(pp)>=pn) else pn-1

def n_pages(stem):
    c=(T/stem.split("_")[1]/(stem+".txt")).read_text("utf-8")
    return len(re.findall(r"^\[PAGE\s+\d+\]\s*$", c, re.M))

def graphic_weight(d, pr):
    """Graphic segments in a drawing: bezier curves and non-axis-aligned line segments.
    Paths >= 20pt count fully (curves, axes-with-slope, diagrams). Paths < 20pt count only when they hold <= 4
    segments (a curve drawn as a chain of short polyline pieces); small paths with many segments are glyph
    outlines (text drawn as paths) and count 0. Axis-aligned straight lines/rects (table borders) count 0."""
    r=d["rect"]
    if r.width>pr.width*0.95 and r.height>pr.height*0.95: return 0   # page frame
    w=0
    for it in d["items"]:
        op=it[0]
        if op in ("c","qu"): w+=1
        elif op=="l":
            p1,p2=it[1],it[2]
            if abs(p1.x-p2.x)>0.3 and abs(p1.y-p2.y)>0.3: w+=1   # any non-axis-aligned segment
    if max(r.width,r.height)<20 and w>4: return 0   # glyph outline
    return w

def is_graphic(d, pr): return graphic_weight(d,pr)>0

def cluster(rects, gap):
    rects=[pymupdf.Rect(r) for r in rects]; changed=True
    while changed:
        changed=False; out=[]
        while rects:
            a=rects.pop(); merged=True
            while merged:
                merged=False
                for i,b in enumerate(rects):
                    if pymupdf.Rect(a.x0-gap,a.y0-gap,a.x1+gap,a.y1+gap).intersects(b):
                        a=a|b; rects.pop(i); merged=True; changed=True; break
            out.append(a)
        rects=out
    return rects

log=[]; n_new=0; pages_scanned=0; pages_with=0
for stem in sorted(pdf_by_stem):
    subj=stem.split("_")[1]
    if not (T/subj/(stem+".txt")).exists(): continue
    try: doc=pymupdf.open(str(pdf_by_stem[stem]))
    except Exception as e: print("open fail",stem,e); continue
    for pn in range(1, n_pages(stem)+1):
        idx=pdf_index(stem,pn)
        if idx>=len(doc): continue
        page=doc[idx]; pr=page.rect; pages_scanned+=1
        try: dr=page.get_drawings()
        except Exception: continue
        weighted=[(d["rect"],graphic_weight(d,pr)) for d in dr]
        graphic=[(r,w) for r,w in weighted if w>0]
        if sum(w for _,w in graphic)<MIN_GRAPHIC: continue
        straight=[r for r,w in weighted if w==0 and r.width<pr.width*0.95]
        gclusters=cluster([r for r,_ in graphic], GAP)
        keep=[]
        for gc in gclusters:
            members=sum(w for r,w in graphic if gc.intersects(r))
            big=sum(w for r,w in graphic if gc.intersects(r) and max(r.width,r.height)>=20)
            if big<MIN_GRAPHIC and members<MIN_SHORT: continue
            # absorb straight paths (axes, ticks, frame) touching the cluster
            box=pymupdf.Rect(gc)
            # absorb only straight paths of comparable size (axes, ticks, frame) — table borders are far larger than the graph
            lim_w=1.6*gc.width+24; lim_h=1.6*gc.height+24
            for _ in range(3):
                for s in straight:
                    if s.width<=lim_w and s.height<=lim_h and pymupdf.Rect(box.x0-GAP,box.y0-GAP,box.x1+GAP,box.y1+GAP).intersects(s):
                        box=box|s
            box=box & pr
            if box.width<MIN_SIZE or box.height<MIN_SIZE: continue
            # skip if an existing embedded-image figure already covers it
            covered=False
            for ex in existing.get((stem,pn),[]):
                inter=box & ex
                if not inter.is_empty and inter.get_area()>=0.6*box.get_area(): covered=True; break
            if covered: continue
            keep.append((box,members))
        # merge boxes that overlap substantially (different seed clusters growing into the same region)
        merged=True
        while merged and len(keep)>1:
            merged=False
            for i in range(len(keep)):
                for j in range(i+1,len(keep)):
                    a,b=keep[i][0],keep[j][0]; inter=a&b
                    if not inter.is_empty and inter.get_area()>=0.5*min(a.get_area(),b.get_area()):
                        keep[i]=(a|b,keep[i][1]+keep[j][1]); keep.pop(j); merged=True; break
                if merged: break
        if not keep: continue
        pages_with+=1
        (OUT/subj).mkdir(exist_ok=True)
        for k,(box,members) in enumerate(sorted(keep,key=lambda x:(x[0].y0,x[0].x0)),1):
            pad=18; clip=pymupdf.Rect(max(pr.x0,box.x0-pad),max(pr.y0,box.y0-pad),min(pr.x1,box.x1+pad),min(pr.y1,box.y1+pad))
            name="{0}_page{1}_vfig{2}.png".format(stem,pn,k)
            if name in EXCLUDE: continue
            if not DRY: page.get_pixmap(dpi=200, clip=clip).save(str(OUT/subj/name))
            n_new+=1
            fm["figures"].append({"figure":"data/processed/figures/{0}/{1}".format(subj,name),"subject":subj,"stem":stem,"page":pn,
                "source_pdf":str(pdf_by_stem[stem].relative_to(P)).replace("\\","/"),"pdf_page_index":idx,
                "bbox_pt":[round(clip.x0,1),round(clip.y0,1),round(clip.x1,1),round(clip.y1,1)],"full_page":False,
                "type":"vector","graphic_paths":members})
            log.append({"stem":stem,"page":pn,"figure":name,"graphic_paths":members,"bbox":[round(v) for v in clip]})
    doc.close()

fm["total"]=len(fm["figures"]); fm["vector_figures"]=n_new; fm["pages_covered"]=len({(f["stem"],f["page"]) for f in fm["figures"]})
if not DRY:
    (P/"data/processed/figures_manifest.json").write_text(json.dumps(fm,indent=1,ensure_ascii=False),"utf-8")
    (P/"data/processed/vector_figures_log.json").write_text(json.dumps(log,indent=1,ensure_ascii=False),"utf-8")
print("pages scanned:",pages_scanned,"| pages with new vector figures:",pages_with,"| vector figures rendered:",n_new)
print("by subject:",dict(Counter(l["stem"].split("_")[1] for l in log)))
print("figures total now:",fm["total"],"| pages covered:",fm["pages_covered"])
