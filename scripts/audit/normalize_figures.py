"""Replace synthetic figure markup (SVG data-URIs, base64 placeholders, <img>, tikz, ASCII-art code fences,
markdown image links) with honest [FIGURE: ...] placeholders that keep any labels/alt text. Also apply 2 confirmed text fixes."""
import re, json
from pathlib import Path
from collections import Counter
P=Path("C:/Users/samsung/Desktop/bac-genius"); T=P/"data/processed/texts"
log=Counter(); changed_files=[]

def labels_from(block):
    # keep meaningful tokens: words (latin/arabic), numbers with units, LaTeX-ish tokens; drop box-drawing/ascii-art punctuation
    toks=re.findall(r"[A-Za-zÀ-ÿ\u0600-\u06FF][A-Za-zÀ-ÿ\u0600-\u06FF0-9_'^,.\-]*|\d+(?:[.,]\d+)?\s*[A-Za-z%°]*", block)
    out=[]; seen=set()
    for t in toks:
        t=t.strip(" .,")
        if len(t)<2 or t in seen: continue
        if re.fullmatch(r"[\-_|/\\+^<>=~]+", t): continue
        seen.add(t); out.append(t)
    return out[:40]

for s in ["arabe","english","francais","islamic","math","physic","svt"]:
    for f in sorted((T/s).glob("*.txt")):
        t=f.read_text("utf-8"); o=t
        # 1) markdown image links incl. data URIs / svg / base64 / fake paths
        def md_img(m):
            alt=m.group(1).strip(); log["md_image_link"]+=1
            return "[FIGURE: {0}]".format(alt) if alt and alt.lower() not in ("graph","image","figure","img") else "[FIGURE]"
        t=re.sub(r"!\[([^\]]*)\]\((?:data:[^)]*?|[^)]*)\)", md_img, t)
        # leftover bare svg tags
        t=re.sub(r"<svg\b.*?</svg>", "[FIGURE]", t, flags=re.S)
        # 2) html img
        def html_img(m):
            alt=re.search(r'alt="([^"]*)"', m.group(0)); log["html_img"]+=1
            return "[FIGURE: {0}]".format(alt.group(1)) if alt else "[FIGURE]"
        t=re.sub(r"<img\b[^>]*>", html_img, t)
        # 3) tikz
        def tikz(m):
            log["tikz"]+=1; lab=labels_from(m.group(0)); return "[FIGURE: labels: {0}]".format(", ".join(lab)) if lab else "[FIGURE]"
        t=re.sub(r"\\begin\{tikzpicture\}.*?\\end\{tikzpicture\}", tikz, t, flags=re.S)
        # 4) code fences containing ascii-art (any fence): keep labels
        def fence(m):
            body=m.group(2); log["code_fence"]+=1
            # if it contains a [PAGE n] marker, don't touch (spans pages) — handle by splitting
            if re.search(r"^\[PAGE\s+\d+\]\s*$", body, re.M): log["fence_spans_page"]+=1; return m.group(0)
            lab=labels_from(body)
            return "[FIGURE: ASCII rendition removed; labels: {0}]".format(", ".join(lab)) if lab else "[FIGURE: ASCII rendition removed]"
        t=re.sub(r"```(\w*)\n(.*?)```", fence, t, flags=re.S)
        if t!=o:
            f.write_text(t,"utf-8"); changed_files.append(str(f.relative_to(P)).replace("\\","/"))

# fences that span page markers: close them at the page boundary by removing the stray fence lines
for rel in list(changed_files)+[str(p.relative_to(P)).replace("\\","/") for s in ["math","physic","svt"] for p in (T/s).glob("*.txt")]:
    f=P/rel; t=f.read_text("utf-8")
    if "```" in t:
        # remove any remaining fence lines and convert their inner ascii-art lines to a single placeholder per contiguous block
        lines=t.split("\n"); out=[]; inside=False; buf=[]
        for ln in lines:
            if ln.strip().startswith("```"):
                if inside:
                    lab=labels_from("\n".join(buf)); out.append("[FIGURE: ASCII rendition removed; labels: {0}]".format(", ".join(lab)) if lab else "[FIGURE: ASCII rendition removed]"); buf=[]
                inside=not inside; log["fence_fixed_spanning"]+=1; continue
            if inside:
                if re.match(r"^\[PAGE\s+\d+\]\s*$", ln.strip()):
                    lab=labels_from("\n".join(buf)); out.append("[FIGURE: ASCII rendition removed; labels: {0}]".format(", ".join(lab)) if lab else "[FIGURE: ASCII rendition removed]"); buf=[]
                    out.append(ln); inside=False
                else: buf.append(ln)
            else: out.append(ln)
        if inside and buf:
            lab=labels_from("\n".join(buf)); out.append("[FIGURE: ASCII rendition removed; labels: {0}]".format(", ".join(lab)) if lab else "[FIGURE: ASCII rendition removed]")
        nt="\n".join(out)
        if nt!=t: f.write_text(nt,"utf-8"); changed_files.append(rel)

# confirmed text fixes from independent visual inspection
fixes=[
 ("math/bac_math_2013_sujet1_solution.txt", r"\left(e^{\alpha - 1} = -\frac{\alpha}{\alpha - 1}\right)", r"\left(e^{\frac{1}{\alpha - 1}} = -\frac{\alpha}{\alpha - 1}\right)"),
 ("math/bac_math_2017_sujet2_solution_session1.txt", "نقطة تلاقي الاحمدة", "نقطة تلاقي الاعمدة"),
]
for rel,old,new in fixes:
    f=T/rel; t=f.read_text("utf-8"); n=t.count(old)
    if n==0: print("!! NOT FOUND:", rel, old[:40])
    else: f.write_text(t.replace(old,new),"utf-8"); log["text_fix:"+rel.split("/")[-1]]+=n; changed_files.append("data/processed/texts/"+rel)

print("Replacements:", dict(log))
print("Files changed:", len(set(changed_files)))
json.dump({"log":dict(log),"files":sorted(set(changed_files))}, open(P/"data/processed/normalize_figures_log.json","w",encoding="utf-8"), indent=1, ensure_ascii=False)
