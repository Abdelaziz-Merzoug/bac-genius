"""Tile left+right margin strips of candidate solution pages (4 pages per image) for fast score reading."""
import json, sys
from pathlib import Path
import pymupdf
from PIL import Image, ImageDraw, ImageFont

P = Path("C:/Users/samsung/Desktop/bac-genius")
OUT = Path(r"C:\Users\samsung\AppData\Local\Temp\claude\C--Users-samsung-Desktop-bac-genius\080f53e8-a8e9-440e-a559-c5a8bdcc0ca4\scratchpad\tiles"); OUT.mkdir(exist_ok=True)
manifest=json.loads((P/"data/raw/manifest.json").read_text("utf-8")); ocr=json.loads((P/"data/processed/ocr_manifest.json").read_text("utf-8"))
pdf={Path(r["path"]).stem:P/r["path"] for r in manifest if not r.get("duplicate") and r["path"].lower().endswith(".pdf")}
cands=json.loads((P/"data/processed/score_margin_candidates.json").read_text("utf-8"))
subj_filter = sys.argv[1] if len(sys.argv)>1 else None
if subj_filter: cands=[c for c in cands if c["subject"]==subj_filter]
DPI=110; FRAC=0.26; PER=4
def strips(key):
    stem,pn=key.rsplit("__p",1); pn=int(pn); pp=ocr.get(stem,{}).get("pdf_pages",[]); idx=(pp[pn-1]-1) if (pp and len(pp)>=pn) else pn-1
    doc=pymupdf.open(str(pdf[stem])); pg=doc[idx]; r=pg.rect
    L=pg.get_pixmap(dpi=DPI, clip=pymupdf.Rect(r.x0, r.y0, r.x0+r.width*FRAC, r.y1))
    R=pg.get_pixmap(dpi=DPI, clip=pymupdf.Rect(r.x1-r.width*FRAC, r.y0, r.x1, r.y1))
    li=Image.frombytes("RGB",(L.width,L.height),L.samples); ri=Image.frombytes("RGB",(R.width,R.height),R.samples); doc.close()
    return li, ri
tiles=[]
for i in range(0,len(cands),PER):
    group=cands[i:i+PER]; imgs=[]
    for c in group:
        li,ri=strips(c["key"]); imgs.append((c["key"],li,ri))
    H=max(im.height for _,l,r in imgs for im in (l,r))+40; W=sum(l.width+r.width+30 for _,l,r in imgs)
    canvas=Image.new("RGB",(W,H),"white"); d=ImageDraw.Draw(canvas); x=0
    try: font=ImageFont.truetype("arial.ttf",16)
    except: font=None
    for k,l,r in imgs:
        short=k.replace("bac_","").replace("_solution","_S").replace("_session","_s")
        d.text((x+4,4),short[:34],fill="red",font=font); d.text((x+4,20),"LEFT",fill="blue",font=font)
        canvas.paste(l,(x,40)); x+=l.width+5
        d.text((x+4,20),"RIGHT",fill="blue",font=font); canvas.paste(r,(x,40)); x+=r.width+25
        d.line([(x-12,0),(x-12,H)],fill="black",width=3)
    name="tile_{0:02d}.png".format(i//PER); canvas.save(OUT/name); tiles.append({"tile":name,"keys":[k for k,_,_ in imgs]})
json.dump(tiles,open(OUT/"tiles_index.json","w"),indent=1)
print("tiles:",len(tiles),"| pages:",len(cands))
