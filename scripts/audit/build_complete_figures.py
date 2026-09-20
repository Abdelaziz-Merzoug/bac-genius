"""
Build COMPLETE figure renders from source PDFs for every page containing a GRAPH/DIAGRAM/TABLE/FIGURE image.
Clusters embedded-image bboxes (strips/tiles) into one region and renders it at 200 DPI directly from the PDF,
so the saved figure is guaranteed complete and identical to the source.
Output: data/processed/figures/{subject}/{stem}_page{n}_fig{k}.png + figures_manifest.json
"""
import json, re, sys
from pathlib import Path
from collections import defaultdict, Counter
import pymupdf

sys.stdout.reconfigure(line_buffering=True)
P = Path("C:/Users/samsung/Desktop/bac-genius")
OUT = P/"data/processed/figures"; OUT.mkdir(exist_ok=True)
manifest=json.loads((P/"data/raw/manifest.json").read_text("utf-8"))
ocr=json.loads((P/"data/processed/ocr_manifest.json").read_text("utf-8"))
pdf_by_stem={Path(r["path"]).stem:P/r["path"] for r in manifest if not r.get("duplicate") and r["path"].lower().endswith(".pdf")}
cls=json.loads((P/"data/processed/image_classification.json").read_text("utf-8"))["results"]
FIG={"GRAPH","DIAGRAM","TABLE","FIGURE"}

# pages that contain at least one figure-class image, with the set of figure-class img indices
pages=defaultdict(lambda: {"fig_idx":set(), "cats":Counter()})
pat=re.compile(r"^(.+)_page(\d+)_img(\d+)\.png$")
for r in cls:
    if r["category"] in FIG:
        m=pat.match(r["file"]); stem,pn,k=m.group(1),int(m.group(2)),int(m.group(3))
        pages[(r["subject"],stem,pn)]["fig_idx"].add(k); pages[(r["subject"],stem,pn)]["cats"][r["category"]]+=1
print("Pages with figure-class images: {0}".format(len(pages)))

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
                    ea=pymupdf.Rect(a.x0-gap,a.y0-gap,a.x1+gap,a.y1+gap)
                    if ea.intersects(b): a=a|b; rects.pop(i); merged=True; changed=True; break
            out.append(a)
        rects=out
    return rects

fig_manifest=[]; n_fig=0; n_fullpage=0; skipped=0
for (subj,stem,pn),info in sorted(pages.items()):
    pdf=pdf_by_stem.get(stem)
    if not pdf: skipped+=1; continue
    doc=pymupdf.open(str(pdf)); page=doc[pdf_index(stem,pn)]; pr=page.rect
    infos=page.get_image_info(xrefs=True)
    # index images in the same order the extractor used (page.get_images order == xref order in get_images())
    xref_order=[im[0] for im in page.get_images(full=True)]
    by_xref=defaultdict(list)
    for ii in infos: by_xref[ii.get("xref")].append(pymupdf.Rect(ii["bbox"]))
    fig_rects=[]; member_files=defaultdict(list)
    for k in info["fig_idx"]:
        if 1<=k<=len(xref_order):
            for rc in by_xref.get(xref_order[k-1],[]): fig_rects.append(rc)
    # add ALL image rects on page so adjacent strips/tiles of the same figure get merged even if some were classified EQUATION/TEXTUAL
    all_rects=[rc for lst in by_xref.values() for rc in lst]
    if not fig_rects:
        # fallback: could not map -> use all rects
        fig_rects=all_rects
    clusters=cluster(all_rects) if all_rects else []
    # keep only clusters that contain at least one figure-class rect
    keep=[]
    for c in clusters:
        if any(c.intersects(fr) for fr in fig_rects): keep.append(c)
    (OUT/subj).mkdir(exist_ok=True)
    k=0
    for c in keep:
        c=c & pr
        if c.width<40 or c.height<40: continue
        is_full = c.width>=pr.width*0.85 and c.height>=pr.height*0.85
        pad=6; clip=pymupdf.Rect(max(pr.x0,c.x0-pad),max(pr.y0,c.y0-pad),min(pr.x1,c.x1+pad),min(pr.y1,c.y1+pad))
        k+=1; name="{0}_page{1}_fig{2}.png".format(stem,pn,k)
        page.get_pixmap(dpi=200, clip=clip).save(str(OUT/subj/name)); n_fig+=1
        if is_full: n_fullpage+=1
        fig_manifest.append({"figure":"data/processed/figures/{0}/{1}".format(subj,name),"subject":subj,"stem":stem,"page":pn,
            "source_pdf":str(pdf.relative_to(P)).replace("\\","/"),"pdf_page_index":pdf_index(stem,pn),
            "bbox_pt":[round(clip.x0,1),round(clip.y0,1),round(clip.x1,1),round(clip.y1,1)],"full_page":is_full,
            "categories_on_page":dict(info["cats"])})
    doc.close()
    if len(fig_manifest)%100==0 and fig_manifest: print("  ...{0} figures".format(len(fig_manifest)))
(P/"data/processed/figures_manifest.json").write_text(json.dumps({"total":n_fig,"full_page_renders":n_fullpage,"pages_covered":len(pages),"figures":fig_manifest},indent=1,ensure_ascii=False),"utf-8")
print("\nComplete figures rendered: {0} ({1} full-page) from {2} pages | skipped {3}".format(n_fig,n_fullpage,len(pages),skipped))
print("By subject:", dict(Counter(f["subject"] for f in fig_manifest)))
