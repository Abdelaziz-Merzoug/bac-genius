"""
INDEPENDENT FINAL CHECK of the CURRENT filesystem state. No API. No reliance on prior verdicts.
A) integrity + regression on every fixed page
B) math/physics/science deep programmatic checks (LaTeX, tables, Arabic RTL, scoring values, duplicates)
C) image/caption/manifest cross-consistency, PIL-open every meaningful image, page-number bounds vs PDF
"""
import json, re, sys, io
from pathlib import Path
from collections import Counter, defaultdict
import pymupdf
from PIL import Image

sys.stdout.reconfigure(line_buffering=True)
P = Path("C:/Users/samsung/Desktop/bac-genius")
TEXTS = P/"data/processed/texts"; IMAGES = P/"data/processed/images"; CAPS = P/"data/processed/image_captions"
S = ["arabe","english","francais","islamic","math","physic","svt"]
F = []  # findings (blocking)
W = []  # warnings
def finding(cat, msg): F.append({"cat":cat,"msg":msg}); print("  [FINDING] {0}: {1}".format(cat,msg))
def warn(cat, msg): W.append({"cat":cat,"msg":msg})

def parse_pages(c):
    pages={}; cur=0; lines=[]; markers=[]
    for line in c.splitlines():
        m=re.match(r"^\[PAGE\s+(\d+)\]\s*$", line.strip())
        if m:
            if cur>0: pages[cur]="\n".join(lines).strip()
            cur=int(m.group(1)); lines=[]; markers.append(cur)
        else:
            if cur>0: lines.append(line)
    if cur>0: pages[cur]="\n".join(lines).strip()
    return pages, markers

manifest=json.loads((P/"data/raw/manifest.json").read_text("utf-8"))
ocr=json.loads((P/"data/processed/ocr_manifest.json").read_text("utf-8"))
pdf_by_stem={Path(r["path"]).stem:P/r["path"] for r in manifest if not r.get("duplicate") and r["path"].lower().endswith(".pdf")}

print("="*70); print("A) INTEGRITY + REGRESSION"); print("="*70)
backups=json.loads((P/"data/processed/page_backups_prefix.json").read_text("utf-8"))
fixlog=json.loads((P/"data/processed/fix_corrupted_log.json").read_text("utf-8"))
fixed_keys=[k for k,e in fixlog.items() if e["status"].startswith("FIXED")]
print("Fixed pages to regression-check: {0}".format(len(fixed_keys)))

all_pages={}  # key -> (subject, stem, pn, text)
pdf_pagecount={}
files=0; pages_total=0; stray_markers=0
for s in S:
    for f in sorted((TEXTS/s).glob("*.txt")):
        files+=1
        raw=f.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"): warn("bom", f.name)
        try: c=raw.decode("utf-8")
        except UnicodeDecodeError as e: finding("utf8_decode", "{0}: {1}".format(f.name, str(e)[:60])); continue
        pages, markers = parse_pages(c)
        if markers != list(range(1,len(markers)+1)): finding("page_markers", "{0}: markers={1}".format(f.name, markers[:12]))
        # stray "[PAGE" inside text (not a marker line)
        body="\n".join(pages.values())
        if re.search(r"\[PAGE\s+\d+\]", body): stray_markers+=1; finding("stray_marker_in_body", f.name)
        # PDF page count
        pdf=pdf_by_stem.get(f.stem)
        if not pdf: finding("no_pdf", f.stem); continue
        try:
            doc=pymupdf.open(str(pdf)); n=len(doc); doc.close()
        except Exception as e: finding("pdf_open", "{0}: {1}".format(f.stem, str(e)[:60])); continue
        pdf_pagecount[f.stem]=n
        pp=ocr.get(f.stem,{}).get("pdf_pages",[])
        if pp:
            if len(pp)!=len(pages): finding("ocr_pagecount_mismatch", "{0}: manifest {1} vs text {2}".format(f.stem,len(pp),len(pages)))
            if max(pp)>n: finding("ocr_page_out_of_range", "{0}: max pdf_page {1} > pdf has {2}".format(f.stem,max(pp),n))
        else:
            if len(pages)>n: finding("text_pages_exceed_pdf", "{0}: text {1} > pdf {2}".format(f.stem,len(pages),n))
        for pn,t in pages.items():
            pages_total+=1; all_pages["{0}__p{1}".format(f.stem,pn)]=(s,f.stem,pn,t)
print("Files {0}, pages {1}".format(files, pages_total))
if files!=580 or pages_total!=1505: finding("count", "files={0} pages={1}".format(files,pages_total))

# regression on fixed pages
reg_bad=0; shrunk=[]
for k in fixed_keys:
    if k not in all_pages: finding("fixed_page_missing", k); reg_bad+=1; continue
    t=all_pages[k][3]
    if len(t)<80: finding("fixed_page_too_short", "{0}: {1}c".format(k,len(t))); reg_bad+=1
    old=backups.get(k,"")
    if old and len(t) < 0.5*len(old): shrunk.append((k,len(old),len(t)))
if shrunk:
    for k,o,n in shrunk: warn("fixed_page_shrunk", "{0}: {1}->{2}".format(k,o,n))
print("Regression: {0} bad, {1} shrunk >50% (warn)".format(reg_bad, len(shrunk)))

print("\n"+"="*70); print("B) MATH / PHYSICS / SCIENCE DEEP CHECKS"); print("="*70)
latex_issues=[]; table_issues=[]; arabic_pres=[]; weird_scores=[]; dup_lines=[]; rev_arabic=[]; empty_frac=[]
REV=["تاريغت","لودج","ةراشإ","جاتنتسا","ةيبيرجتلا","ةيملعلا","ةلادلا","ةيضايرلا","ةغللا","ةيملاسلإا","ةيبرعلا","ةعيبطلا","ةايحلا","ءايزيفلا","ةباجلإا","ةملاعلا","عوضوملا"]
VALID_SCORES={"0.25","0.5","0.50","0.75","1","01","1.5","1.50","2","02","2.5","3","03","3.5","4","04","5","05","6","06","7","07","8","08","0,25","0,5","0,50","0,75","1,5","1,50","2,5","4,5","04,5","0.125","1.25","1.75","2.25","2.75","3.25","3.5","3.75","4.25","4.5","4.75","5.5","6.5","7.5","9","10","11","12","13","14","15","16","17","18","19","20"}
for k,(s,stem,pn,t) in all_pages.items():
    # LaTeX: $ balance (count of single $ not part of $$)
    stripped=t.replace("$$","")
    if stripped.count("$")%2==1: latex_issues.append((k,"odd $ count"))
    # brace balance inside math-heavy pages
    if s in ("math","physic","svt") and "\\" in t:
        ob=t.count("{"); cb=t.count("}")
        if abs(ob-cb)>2: latex_issues.append((k,"braces {0} vs {1}".format(ob,cb)))
        # \frac with fewer than 2 brace groups following
        for m in re.finditer(r"\\frac(?!\{[^{}]*\}\{)", t):
            ctx=t[m.start():m.start()+30]
            if not re.match(r"\\frac\{", ctx): empty_frac.append((k,ctx[:25]))
        # dangling ^ or _ at end of token
        if re.search(r"[\^_]\s*(?:\$|\n|$)", t): latex_issues.append((k,"dangling ^/_"))
    # markdown tables: consistent column count per table
    rows=[ln for ln in t.splitlines() if ln.strip().startswith("|") and ln.strip().endswith("|")]
    if len(rows)>=3:
        counts=[ln.count("|") for ln in rows]
        c=Counter(counts).most_common(1)[0][0]
        bad=sum(1 for x in counts if x!=c)
        if bad> max(1, len(rows)//3): table_issues.append((k,"cols {0}, {1}/{2} rows deviate".format(c-1,bad,len(rows))))
    # Arabic presentation forms => visual-order extraction leak
    if re.search(r"[\uFB50-\uFDFF\uFE70-\uFEFF]", t): arabic_pres.append(k)
    for r in REV:
        if r in t: rev_arabic.append((k,r)); break
    # scoring values in solutions: numbers adjacent to score cues
    if "solution" in stem:
        for m in re.finditer(r"(\d+(?:[.,]\d+)?)\s*(?:نقطة|نقاط|pts|pt|points)", t):
            v=m.group(1)
            if v not in VALID_SCORES and v.replace(",",".") not in VALID_SCORES:
                try:
                    fv=float(v.replace(",","."))
                    if fv>20 or (fv*4)!=int(fv*4): weird_scores.append((k,v))
                except: weird_scores.append((k,v))
    # duplicated long lines within a page
    seen=Counter(ln.strip() for ln in t.splitlines() if len(ln.strip())>=45)
    d=[ln for ln,n in seen.items() if n>=2 and not ln.startswith("|") and not re.match(r"^[\-=_*|:\s]+$", ln)]
    if d: dup_lines.append((k,len(d),d[0][:60]))

def rep(name, items, sev, show=6):
    if items:
        print("\n  [{0}] {1}: {2}".format(sev,name,len(items)))
        for x in items[:show]: print("    ", x)
        if len(items)>show: print("     ... +{0}".format(len(items)-show))
        (finding if sev=="FINDING" else warn)(name, "{0} pages".format(len(items)))
    else: print("  OK: {0} = 0".format(name))
rep("latex_delimiter_or_brace", latex_issues, "WARN")
rep("frac_without_two_args", empty_frac, "WARN")
rep("markdown_table_inconsistent", table_issues, "WARN")
rep("arabic_presentation_forms", arabic_pres, "FINDING")
rep("reversed_arabic", rev_arabic, "FINDING")
rep("weird_score_values", weird_scores, "WARN")
rep("duplicated_lines_in_page", dup_lines, "WARN")

print("\n"+"="*70); print("C) IMAGES / CAPTIONS / MANIFEST CROSS-CONSISTENCY"); print("="*70)
inv=json.loads((P/"data/processed/image_inventory.json").read_text("utf-8"))
cls=json.loads((P/"data/processed/image_classification.json").read_text("utf-8"))["results"]
MEAN={"GRAPH","DIAGRAM","TABLE","FIGURE","EQUATION"}
mean_files={r["file"]:r for r in cls if r["category"] in MEAN}
img_on_disk=set(); pil_fail=[]; page_oob=[]; stem_missing=[]
pat=re.compile(r"^(.+)_page(\d+)_img(\d+)\.png$")
n_img=0
for s in S:
    for im in (IMAGES/s).glob("*.png"):
        n_img+=1; img_on_disk.add(im.name)
        m=pat.match(im.name)
        if not m: finding("img_name", im.name); continue
        stem,pg=m.group(1),int(m.group(2))
        if stem not in pdf_pagecount: stem_missing.append(im.name); continue
        if pg>pdf_pagecount[stem]: page_oob.append((im.name,pg,pdf_pagecount[stem]))
        if im.name in mean_files:
            try:
                with Image.open(im) as pi: pi.verify()
                with Image.open(im) as pi:
                    if pi.width<1 or pi.height<1: pil_fail.append(im.name)
            except Exception as e: pil_fail.append(im.name)
print("Images on disk: {0} | meaningful PIL-verified: {1}".format(n_img, len(mean_files)))
if n_img!=4046: finding("image_count", n_img)
rep("image_stem_without_pdf", stem_missing, "FINDING")
rep("image_page_out_of_range", page_oob, "FINDING")
rep("meaningful_image_pil_fail", pil_fail, "FINDING")
inv_names=set(r["file"] for r in inv)
if inv_names!=img_on_disk: finding("inventory_vs_disk", "inv {0} vs disk {1}".format(len(inv_names),len(img_on_disk)))
else: print("  OK: inventory matches disk exactly")

n_cap=0; cap_bad=[]; cap_name_mismatch=[]
for s in S:
    d=CAPS/s
    if not d.exists(): continue
    for cf in d.glob("*.json"):
        n_cap+=1
        try: j=json.loads(cf.read_text("utf-8"))
        except Exception: cap_bad.append(cf.name); continue
        ref=j.get("image_file","")
        if not (P/ref).exists(): cap_bad.append(cf.name+" (ref)"); continue
        if Path(ref).stem!=cf.stem: cap_name_mismatch.append(cf.name)
        if not j.get("description","").strip(): cap_bad.append(cf.name+" (desc)")
        m=pat.match(Path(ref).name)
        if m and (j.get("stem")!=m.group(1) or int(j.get("page_num",-1))!=int(m.group(2))): cap_name_mismatch.append(cf.name+" (meta)")
print("Captions: {0}".format(n_cap))
if n_cap!=853: finding("caption_count", n_cap)
rep("caption_invalid_or_broken", cap_bad, "FINDING")
rep("caption_name_meta_mismatch", cap_name_mismatch, "FINDING")

print("\n"+"="*70); print("SUMMARY"); print("="*70)
print("FINDINGS (blocking): {0}".format(len(F)))
for x in F: print("  [!] {0}: {1}".format(x["cat"],x["msg"]))
print("WARNINGS: {0}".format(len(W)))
for x in W[:20]: print("  [~] {0}: {1}".format(x["cat"],x["msg"]))
(P/"data/processed/independent_final_check.json").write_text(json.dumps({"findings":F,"warnings":W,"files":files,"pages":pages_total,"images":n_img,"captions":n_cap,
    "latex_issues":latex_issues,"table_issues":table_issues,"weird_scores":weird_scores,"dup_lines":dup_lines,"empty_frac":empty_frac},indent=1,ensure_ascii=False),"utf-8")
