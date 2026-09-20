"""Final integrity + reconciliation on CURRENT filesystem after all fixes."""
import json, re, struct
from pathlib import Path
from collections import Counter

P = Path("C:/Users/samsung/Desktop/bac-genius")
TEXTS = P/"data/processed/texts"; IMAGES = P/"data/processed/images"; CAPS = P/"data/processed/image_captions"
S = ["arabe","english","francais","islamic","math","physic","svt"]

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

out = {}
manifest = json.loads((P/"data/raw/manifest.json").read_text("utf-8"))
ocr = json.loads((P/"data/processed/ocr_manifest.json").read_text("utf-8"))
pdfs_disk = sorted(str(f.relative_to(P)).replace("\\","/") for f in (P/"data/raw").rglob("*.pdf"))
uniq = [r for r in manifest if not r.get("duplicate") and r["path"].lower().endswith(".pdf")]
dup = [r for r in manifest if r.get("duplicate")]
curric = [r for r in manifest if not r.get("duplicate") and not r["path"].lower().endswith(".pdf")]
out["pdfs_on_disk"]=len(pdfs_disk); out["unique_exam_pdfs"]=len(uniq); out["duplicate_pdfs"]=len(dup); out["curriculum_txt_records"]=len(curric)
out["missing_unique_pdfs"]=sum(1 for r in uniq if not (P/r["path"]).exists())

files=0; pages=0; pchars=0; fchars=0; empty=0; short=0; fffd=0; null=0; pua=0; nonseq=0
exam_pages=0; soln_pages=0
rev=["تاريغت","لودج","ةراشإ","جاتنتسا","ةيبيرجتلا","ةيملعلا","ةلادلا","ةيضايرلا","ةغللا","ةيملاسلإا","ةيبرعلا","ةعيبطلا","ةايحلا","ءايزيفلا"]
revc=0; garbled_fr=0
latex={"sqrt","frac","nbsp","cdot","ldots","left","right","text","hline","begin","infty","lim","quad","mathbb","vec","overrightarrow"}
stems=set()
for s in S:
    for f in sorted((TEXTS/s).glob("*.txt")):
        files+=1; stems.add(f.stem); c=f.read_text("utf-8"); fchars+=len(c)
        pg=parse_pages(c); pages+=len(pg)
        if sorted(pg)!=list(range(1,len(pg)+1)): nonseq+=1
        is_exam="solution" not in f.stem
        for pn,t in pg.items():
            pchars+=len(t)
            if is_exam: exam_pages+=1
            else: soln_pages+=1
            if not t: empty+=1
            elif len(t)<30: short+=1
            if "\ufffd" in t: fffd+=1
            if "\x00" in t: null+=1
            if re.search(r"[\uE000-\uF8FF]",t): pua+=1
            for r in rev:
                if r in t: revc+=1; break
            w=[x for x in re.findall(r"\b[a-zA-ZÀ-ÿ]{4,}\b",t) if x.lower() not in latex]
            if len(w)>=8:
                g=sum(1 for x in w if sum(1 for ch in x.lower() if ch in "aeiouyàâäéèêëïîôùûüÿ")/len(x)<0.12)
                if g/len(w)>0.25: garbled_fr+=1
out.update(text_files=files, text_pages=pages, exam_pages=exam_pages, solution_pages=soln_pages,
           page_text_chars=pchars, file_total_chars=fchars, empty_pages=empty, very_short_pages=short,
           fffd_pages=fffd, null_pages=null, pua_pages=pua, nonsequential_files=nonseq,
           reversed_arabic_pages=revc, garbled_latin_pages=garbled_fr)
out["ocr_manifest_entries"]=len(ocr); out["ocr_covers_all_text"]=set(ocr)==stems
out["text_stems_match_unique_pdfs"]= stems==set(Path(r["path"]).stem for r in uniq)

imgs=0; zero=0; badhdr=0; ipat=re.compile(r"^(.+)_page(\d+)_img(\d+)\.png$"); orphan=0
for s in S:
    for im in (IMAGES/s).glob("*.png"):
        imgs+=1; b=im.read_bytes()
        if len(b)==0: zero+=1
        elif b[:4]!=b"\x89PNG": badhdr+=1
        m=ipat.match(im.name)
        if not m or m.group(1) not in stems: orphan+=1
out.update(images=imgs, zero_size_images=zero, bad_png_header=badhdr, orphan_images=orphan)

caps=0; badjson=0; broken=0; nodesc=0
for s in S:
    d=CAPS/s
    if not d.exists(): continue
    for cf in d.glob("*.json"):
        caps+=1
        try: j=json.loads(cf.read_text("utf-8"))
        except: badjson+=1; continue
        if not (P/j.get("image_file","")).exists(): broken+=1
        if not j.get("description","").strip(): nodesc+=1
out.update(captions=caps, caption_invalid_json=badjson, caption_broken_refs=broken, caption_empty_desc=nodesc)

for k,v in out.items(): print("{0}: {1}".format(k,v))
(P/"data/processed/final_integrity.json").write_text(json.dumps(out,indent=2),"utf-8")
