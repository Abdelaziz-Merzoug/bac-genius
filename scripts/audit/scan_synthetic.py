import re
from pathlib import Path
from collections import Counter
T=Path("C:/Users/samsung/Desktop/bac-genius/data/processed/texts")
hits=Counter(); pages=[]
pats={
 "svg_datauri": r"data:image/svg\+xml",
 "svg_tag": r"<svg\b",
 "base64_img": r"data:image/(?:png|jpeg|jpg|gif);base64",
 "html_img_tag": r"<img\b",
 "md_image_link": r"!\[[^\]]*\]\((?!data:)[^)]*\)",
 "tikz": r"\\begin\{tikzpicture\}",
 "mermaid": r"```mermaid",
 "code_fence": r"```",
}
for s in ["arabe","english","francais","islamic","math","physic","svt"]:
    for f in (T/s).glob("*.txt"):
        t=f.read_text("utf-8")
        for k,p in pats.items():
            n=len(re.findall(p,t))
            if n: hits[k]+=n; pages.append((k,s,f.name,n))
print("Artifact counts across corpus:")
for k,n in hits.most_common():
    print("  {0}: {1} occurrences in {2} files".format(k,n,sum(1 for x in pages if x[0]==k)))
for key in ["svg_datauri","base64_img","html_img_tag","tikz","mermaid"]:
    lst=[x for x in pages if x[0]==key]
    if lst:
        print("\n{0} files:".format(key))
        for k,s,f,n in lst[:15]: print("   {0}/{1} x{2}".format(s,f,n))
        if len(lst)>15: print("   ... +{0}".format(len(lst)-15))
