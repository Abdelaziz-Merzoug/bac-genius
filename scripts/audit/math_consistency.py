"""
A) Arithmetic self-consistency in math/physic/svt solution pages:
   find numeric computations like \frac{a}{b} = c, a \times b = c, a/b = c, \sqrt{a}=c, a^b = c
   and verify (allowing rounding ±3% or ±1 last digit). Mismatch => candidate wrong number.
B) Exam <-> solution formula cross-check: formulas ($...$ with '=') that match after stripping one sign or one exponent
   but differ in the original => candidate sign/exponent error.
"""
import re, json, math
from pathlib import Path
from collections import defaultdict
P=Path("C:/Users/samsung/Desktop/bac-genius"); T=P/"data/processed/texts"
S=["math","physic","svt"]
def parse_pages(c):
    pages={}; cur=0; lines=[]
    for line in c.splitlines():
        m=re.match(r"^\[PAGE\s+(\d+)\]\s*$", line.strip())
        if m:
            if cur>0: pages[cur]="\n".join(lines).strip()
            cur=int(m.group(1)); lines=[]
        else:
            if cur>0: lines.append(line)
    if cur>0: pages[cur]="\n".join(lines).strip()
    return pages
NUM=r"(-?\d+(?:[.,]\d+)?)"
POW=r"(?:\s*(?:\\times|×|\.)\s*10\^\{?(-?\d+)\}?)?"
def fnum(s): return float(s.replace(",","."))
def val(base,exp):
    v=fnum(base);
    return v*(10**int(exp)) if exp else v
def close(a,b):
    if b==0: return abs(a)<1e-9
    rel=abs(a-b)/max(abs(b),1e-12)
    # allow rounding to 2-3 sig figs
    return rel<=0.03 or abs(a-b)<=0.5*10**(math.floor(math.log10(abs(b)))-2) if b!=0 else False

arith=[]
pat_frac=re.compile(r"\\frac\{\s*"+NUM+POW+r"\s*(?:\\times|×)?\s*"+NUM+r"?"+POW+r"\s*\}\{\s*"+NUM+POW+r"\s*\}\s*(?:=|\\simeq|\\approx|≈|≃)\s*"+NUM+POW)
pat_mul=re.compile(NUM+POW+r"\s*(?:\\times|×)\s*"+NUM+POW+r"\s*(?:=|\\simeq|\\approx|≈|≃)\s*"+NUM+POW)
pat_div=re.compile(NUM+POW+r"\s*/\s*"+NUM+POW+r"\s*(?:=|\\simeq|\\approx|≈|≃)\s*"+NUM+POW)
pat_sqrt=re.compile(r"\\sqrt\{\s*"+NUM+POW+r"\s*\}\s*(?:=|\\simeq|\\approx|≈|≃)\s*"+NUM+POW)
for s in S:
    for f in sorted((T/s).glob("*solution*.txt")):
        for pn,t in parse_pages(f.read_text("utf-8")).items():
            key="{0}__p{1}".format(f.stem,pn)
            for m in pat_frac.finditer(t):
                a,ae,a2,a2e,b,be,c,ce=m.groups()
                try:
                    num=val(a,ae)*(val(a2,a2e) if a2 else 1); den=val(b,be); got=num/den; exp=val(c,ce)
                    if not close(got,exp): arith.append({"key":key,"expr":m.group(0)[:90],"computed":round(got,6),"stated":exp})
                except: pass
            for m in pat_mul.finditer(t):
                a,ae,b,be,c,ce=m.groups()
                try:
                    got=val(a,ae)*val(b,be); exp=val(c,ce)
                    if not close(got,exp): arith.append({"key":key,"expr":m.group(0)[:90],"computed":round(got,6),"stated":exp})
                except: pass
            for m in pat_div.finditer(t):
                a,ae,b,be,c,ce=m.groups()
                try:
                    got=val(a,ae)/val(b,be); exp=val(c,ce)
                    if not close(got,exp): arith.append({"key":key,"expr":m.group(0)[:90],"computed":round(got,6),"stated":exp})
                except: pass
            for m in pat_sqrt.finditer(t):
                a,ae,c,ce=m.groups()
                try:
                    got=math.sqrt(val(a,ae)); exp=val(c,ce)
                    if not close(got,exp): arith.append({"key":key,"expr":m.group(0)[:90],"computed":round(got,6),"stated":exp})
                except: pass

# B) exam<->solution cross-check
def norm(f): return re.sub(r"\s+","",f).replace("\\left","").replace("\\right","").replace("\\dfrac","\\frac").replace("\\displaystyle","")
def strip_signs(f): return re.sub(r"[-+]","",f)
def strip_exp(f): return re.sub(r"\^\{[^}]*\}|\^.","",f)
cross=[]
files={}
for s in S:
    for f in sorted((T/s).glob("*.txt")): files[f.stem]=(s,f.read_text("utf-8"))
for stem,(s,txt) in files.items():
    if "solution" in stem: continue
    sol=stem+"_solution" if stem+"_solution" in files else stem.replace("_session","_solution_session")
    if sol not in files: continue
    ex_f=set(norm(x) for x in re.findall(r"\$([^$]{6,120})\$",txt) if "=" in x)
    so_f=set(norm(x) for x in re.findall(r"\$([^$]{6,120})\$",files[sol][1]) if "=" in x)
    so_by_sign=defaultdict(set); so_by_exp=defaultdict(set)
    for x in so_f: so_by_sign[strip_signs(x)].add(x); so_by_exp[strip_exp(x)].add(x)
    for x in ex_f:
        if x in so_f: continue
        ks=strip_signs(x); ke=strip_exp(x)
        for y in so_by_sign.get(ks,()):
            if y!=x and len(x)>=12: cross.append({"exam":stem,"solution":sol,"exam_formula":x[:100],"solution_formula":y[:100],"differs_in":"sign"})
        for y in so_by_exp.get(ke,()):
            if y!=x and len(x)>=12 and strip_signs(y)!=ks: cross.append({"exam":stem,"solution":sol,"exam_formula":x[:100],"solution_formula":y[:100],"differs_in":"exponent"})

json.dump({"arith":arith,"cross":cross},open(P/"data/processed/math_consistency.json","w",encoding="utf-8"),indent=1,ensure_ascii=False)
print("A) arithmetic inconsistencies:", len(arith))
for a in arith[:40]: print("   ", a["key"][:45], "|", a["expr"][:70], "| computed", a["computed"], "stated", a["stated"])
print("\nB) exam<->solution formula variants (sign/exponent):", len(cross))
for c in cross[:30]: print("   ", c["exam"][:35], c["differs_in"], "|", c["exam_formula"][:60], " vs ", c["solution_formula"][:60])
