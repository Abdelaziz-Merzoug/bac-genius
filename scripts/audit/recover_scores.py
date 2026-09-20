"""
Recover missing scoring columns:
 A) 19 pages with a PDF text layer: extract score-like tokens with positions from the score column region,
    ordered top→bottom, append as a [SCORES] block. Mechanical and faithful to the PDF's own text.
 B) 3 pages verified visually (math_2009 p1, physic_2025 p3, svt_2008 p2): append scores read from the image.
Only appends; never alters existing text.
"""
import re, json
from pathlib import Path
import pymupdf
P=Path("C:/Users/samsung/Desktop/bac-genius"); T=P/"data/processed/texts"
manifest=json.loads((P/"data/raw/manifest.json").read_text("utf-8")); ocr=json.loads((P/"data/processed/ocr_manifest.json").read_text("utf-8"))
pdf={Path(r["path"]).stem:P/r["path"] for r in manifest if not r.get("duplicate") and r["path"].lower().endswith(".pdf")}
flag=json.loads((P/"data/processed/missing_scores_flagged.json").read_text("utf-8"))
SCORE=re.compile(r"^(?:0[.,]25|0[.,]5|0[.,]50|0[.,]75|1|01|1[.,]5|1[.,]50|1[.,]25|1[.,]75|2|02|2[.,]5|2[.,]25|2[.,]75|3|03|3[.,]5|4|04|4[.,]5|5|05|6|06|7|07|8|08|[0-9][.,]00|\d+\s*[x×]\s*[0-9][.,]\d+|[0-9][.,]\d+\s*[x×]\s*\d+|\d+[x×]\d+[.,]\d+)$")

def page_text_replace_append(stem, pn, block):
    subj=stem.split("_")[1]; f=T/subj/(stem+".txt"); c=f.read_text("utf-8")
    out=[]; cur=0; done=False
    lines=c.split("\n")
    for i,ln in enumerate(lines):
        m=re.match(r"^\[PAGE\s+(\d+)\]\s*$", ln.strip())
        if m:
            if cur==pn and not done: out.append(block); out.append(""); done=True
            cur=int(m.group(1))
        out.append(ln)
    if cur==pn and not done: out.append(block); done=True
    f.write_text("\n".join(out),"utf-8"); return done

log=[]
# A) text-layer recovery
for r in flag:
    if r.get("layer_scores",0)<2: continue
    stem,pn=r["stem"],r["page"]; pp=ocr.get(stem,{}).get("pdf_pages",[]); idx=(pp[pn-1]-1) if (pp and len(pp)>=pn) else pn-1
    doc=pymupdf.open(str(pdf[stem])); page=doc[idx]; W=page.rect.width
    words=page.get_text("words")  # x0,y0,x1,y1,word,block,line,wordno
    toks=[]
    for x0,y0,x1,y1,w,*_ in words:
        w2=w.strip().replace("×","x")
        if SCORE.match(w2): toks.append((y0,x0,w.strip()))
    if len(toks)<2: doc.close(); continue
    # score column = tokens clustered in the leftmost or rightmost 30% of page width
    left=[t for t in toks if t[1]<W*0.30]; right=[t for t in toks if t[1]>W*0.70]
    col=left if len(left)>=len(right) else right
    if len(col)<2: col=toks
    col.sort()
    seq=[t[2] for t in col]
    block="[SCORES — recovered from PDF text layer, top→bottom: {0}]".format(" | ".join(seq))
    ok=page_text_replace_append(stem,pn,block); doc.close()
    log.append({"key":r["key"],"method":"text_layer","n":len(seq),"ok":ok}); print("A", r["key"], len(seq), "scores")

# B) visually verified scans
manual={
 ("bac_math_2009_sujet1_solution",1): "[SCORES — read from source image, top→bottom: التمرين الأول: 2x0.25 | 1 | 0.75 | 0.75 | 0.5 | المجموع 03.5 || التمرين الثاني: 4x0.25 | 2x0.5 | 2x0.5 | 2x0.5 | 0.75 | 0.25 | المجموع 05 || التمرين الثالث: 1 | 0.5 | 0.5 | 0.5 | 1 | 0.5 | المجموع 04]",
 ("bac_physic_2025_sujet2_solution",3): "[SCORES — read from source image, top→bottom: 4. 0,25 | 0,25 | المجموع 0,50 || 5. 0,50 | المجموع 0,50 || ثانيا 1. 0,25x3 | المجموع 0,75 || 2. 0,25 | 0,25 | 0,25 | المجموع 0,75 || ثالثا 1. 0,25 | 0,25 | 0,25 | 0,25 | المجموع 1,00 || 2. 0,25x2 | 0,25x2 | المجموع 1,00]",
 ("bac_svt_2008_sujet1_solution",2): "[SCORES — read from source image, top→bottom: 2- 0.25x3 | المجموع 0.75 || 3- 0.5 | المجموع 0.5 || 4- 0.5x4 | المجموع 02 || II 01 | 0.25x5 | المجموع 02.25]",
}
for (stem,pn),block in manual.items():
    ok=page_text_replace_append(stem,pn,block); log.append({"key":"{0}__p{1}".format(stem,pn),"method":"manual_visual","ok":ok}); print("B", stem, pn, ok)

json.dump(log, open(P/"data/processed/recover_scores_log.json","w",encoding="utf-8"), indent=1, ensure_ascii=False)
print("\nrecovered:", sum(1 for l in log if l["ok"]), "| text_layer:", sum(1 for l in log if l["method"]=="text_layer"), "| manual:", sum(1 for l in log if l["method"]=="manual_visual"))
