"""Re-rank Claude/Gemini disagreements by atoms genuinely missing from the page text."""
import json, re, unicodedata
from pathlib import Path
from collections import Counter
P = Path("C:/Users/samsung/Desktop/bac-genius"); T = P/"data/processed/texts"
flag = json.loads((P/"data/processed/claude_disagreements.json").read_text("utf-8"))

SUP = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻₀₁₂₃₄₅₆₇₈₉", "0123456789+-0123456789")
def atoms(s):
    s = unicodedata.normalize("NFKC", s).translate(SUP)
    s = re.sub(r"\\(?:text|mathrm|mathbf|mathbb|vec|overrightarrow|overline|bar|hat|dfrac|frac|sqrt|left|right|cdot|times|approx|simeq|ell|quad|,|;|!)\b", " ", s)
    s = s.replace(",", ".")
    toks = re.findall(r"[A-Za-z]{2,}|\d+(?:\.\d+)?|[A-Za-z]\d+", s)
    # drop LaTeX keywords / units / generic words
    drop = {"mol","min","mL","mL","MeV","mV","ms","cm","kg","km","nm","mm","sin","cos","tan","ln","log","lim","exp","dx","dt","et","ou","de","la","le","des","les","and","the","of"}
    return set(t for t in toks if t not in drop and not re.fullmatch(r"\d", t))
def page_text(key):
    stem,pn = key.rsplit("__p",1); subj = stem.split("_")[1]
    c = (T/subj/(stem+".txt")).read_text("utf-8"); pages={}; cur=0; lines=[]
    for line in c.splitlines():
        m = re.match(r"^\[PAGE\s+(\d+)\]\s*$", line.strip())
        if m:
            if cur>0: pages[cur]="\n".join(lines)
            cur=int(m.group(1)); lines=[]
        else:
            if cur>0: lines.append(line)
    if cur>0: pages[cur]="\n".join(lines)
    return pages.get(int(pn),"")

ranked=[]
for f in flag:
    txt = unicodedata.normalize("NFKC", page_text(f["key"])).translate(SUP).replace(",",".")
    page_atoms = set(re.findall(r"[A-Za-z]{2,}|\d+(?:\.\d+)?|[A-Za-z]\d+", txt))
    page_flat = re.sub(r"[\s{}\\$_^]", "", txt)
    real=[]
    for u in f["unmatched"]:
        a = atoms(u["claude"])
        if not a: continue
        missing = sorted(t for t in a if t not in page_atoms and t not in page_flat)
        if missing:
            # numeric-only missing atoms that look like graph axis ticks (all in -100..100 step 10/20) are low priority
            real.append({"claude":u["claude"][:120],"missing":missing})
    if real:
        nums_only = all(all(re.fullmatch(r"\d+(?:\.\d+)?",m) for m in r["missing"]) for r in real)
        ranked.append({"key":f["key"],"subject":f["subject"],"n_real":len(real),"n_items":f["n_items"],"numeric_only":nums_only,"items":real[:12]})
ranked.sort(key=lambda x:(-x["n_real"]))
print("Pages with atoms genuinely absent from text:", len(ranked), "/", len(flag))
print("By subject:", dict(Counter(r["subject"] for r in ranked)))
print("numeric-only (likely axis ticks/figure labels):", sum(1 for r in ranked if r["numeric_only"]), "| with alpha atoms missing:", sum(1 for r in ranked if not r["numeric_only"]))
print()
for r in [x for x in ranked if not x["numeric_only"]][:20]:
    print("--", r["key"], "|", r["n_real"], "items with missing atoms")
    for it in r["items"][:3]: print("     ", it["claude"][:70], "| missing:", it["missing"][:6])
json.dump(ranked, open(P/"data/processed/claude_disagreements_ranked.json","w",encoding="utf-8"), indent=1, ensure_ascii=False)
