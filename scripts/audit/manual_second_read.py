"""
Manual second extraction (API-free): Claude reads page renders directly and compares against the text file.
Covers the 539 science pages (math/physic/svt) that never had a second-model extraction.
Checkpointed per page in data/processed/manual_second_read_checkpoint.json so it survives sessions.

usage:
  manual_second_read.py list                 -> progress + next pages
  manual_second_read.py next [N]             -> render next N unread pages (2 per image, 100 DPI) + print their text
  manual_second_read.py show <key> [dpi]     -> render a single page (zoom)
  manual_second_read.py log <key> <VERDICT> <note...>   VERDICT in FAITHFUL | FIXED | NOTE
"""
import json, re, sys, datetime
from pathlib import Path
import pymupdf
from PIL import Image, ImageDraw

P = Path("C:/Users/samsung/Desktop/bac-genius"); T = P/"data/processed/texts"
OUT = Path(r"C:\Users\samsung\AppData\Local\Temp\claude\C--Users-samsung-Desktop-bac-genius\080f53e8-a8e9-440e-a559-c5a8bdcc0ca4\scratchpad\msr"); OUT.mkdir(exist_ok=True)
CK = P/"data/processed/manual_second_read_checkpoint.json"
manifest = json.loads((P/"data/raw/manifest.json").read_text("utf-8")); ocr = json.loads((P/"data/processed/ocr_manifest.json").read_text("utf-8"))
pdf = {Path(r["path"]).stem: P/r["path"] for r in manifest if not r.get("duplicate") and r["path"].lower().endswith(".pdf")}

def pdf_index(stem, pn):
    pp = ocr.get(stem, {}).get("pdf_pages", []); return (pp[pn-1]-1) if (pp and len(pp) >= pn) else pn-1

def pages_of(stem):
    c = (T/stem.split("_")[1]/(stem+".txt")).read_text("utf-8")
    return re.split(r"^\[PAGE \d+\]\s*$", c, flags=re.M)[1:]

# target list: science pages with no second extraction, ordered solutions first (RAG answers), then exams
never = json.loads((P/"data/processed/pages_without_second_extraction.json").read_text("utf-8"))
sci = [k for k in never if k.split("_")[1] in ("math", "physic", "svt")]
def prio(k):
    subj = k.split("_")[1]; sol = "_solution" in k
    return (0 if sol else 1, {"physic": 0, "svt": 1, "math": 2}[subj], k)
targets = sorted(sci, key=prio)

ck = json.loads(CK.read_text("utf-8")) if CK.exists() else {}
todo = [k for k in targets if k not in ck]

cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
if cmd == "list":
    from collections import Counter
    print("targets:", len(targets), "| done:", len(ck), "| remaining:", len(todo))
    print("verdicts:", dict(Counter(v["verdict"] for v in ck.values())))
    print("by subject remaining:", dict(Counter((k.split("_")[1], "sol" if "_solution" in k else "exam") for k in todo)))
    print("next:", todo[:6])
elif cmd == "show":
    key = sys.argv[2]; dpi = int(sys.argv[3]) if len(sys.argv) > 3 else 130
    stem, pn = key.rsplit("__p", 1); pn = int(pn)
    doc = pymupdf.open(str(pdf[stem])); pix = doc[pdf_index(stem, pn)].get_pixmap(dpi=dpi); out = OUT/(key+".png"); pix.save(str(out)); doc.close()
    print(out, pix.width, pix.height)
elif cmd == "next":
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    grp = todo[:n]; ims = []
    for key in grp:
        stem, pn = key.rsplit("__p", 1); pn = int(pn)
        doc = pymupdf.open(str(pdf[stem])); pix = doc[pdf_index(stem, pn)].get_pixmap(dpi=100)
        ims.append((key, Image.frombytes("RGB", (pix.width, pix.height), pix.samples))); doc.close()
    W = sum(im.width+12 for _, im in ims); H = max(im.height for _, im in ims)+26
    canvas = Image.new("RGB", (W, H), "white"); d = ImageDraw.Draw(canvas); x = 0
    for key, im in ims:
        d.text((x+4, 4), key.replace("bac_", ""), fill="red"); canvas.paste(im, (x, 26)); x += im.width+12
        d.line([(x-6, 0), (x-6, H)], fill="black", width=3)
    out = OUT/"next.png"; canvas.save(str(out)); print("IMAGE:", out, canvas.size)
    for key in grp:
        stem, pn = key.rsplit("__p", 1); pn = int(pn); txt = pages_of(stem)[pn-1].strip()
        print("\n" + "="*30, key, "="*30); print(txt[:5000])
elif cmd == "log":
    key, verdict = sys.argv[2], sys.argv[3]; note = " ".join(sys.argv[4:])
    assert verdict in ("FAITHFUL", "FIXED", "NOTE"), verdict
    ck[key] = {"verdict": verdict, "note": note, "method": "Claude Opus 5 direct read of 100-DPI render vs text", "ts": datetime.datetime.now().isoformat(timespec="minutes")}
    CK.write_text(json.dumps(ck, indent=1, ensure_ascii=False), "utf-8")
    print("logged", key, verdict, "| done", len(ck), "/", len(targets))
