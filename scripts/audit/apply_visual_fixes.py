"""Apply fixes confirmed by direct visual inspection of source PDFs (Claude, independent of Gemini)."""
import re, json
from pathlib import Path
P=Path("C:/Users/samsung/Desktop/bac-genius"); T=P/"data/processed/texts"
log=[]
def rep(rel, old, new, count=1, note=""):
    f=T/rel; t=f.read_text("utf-8"); n=t.count(old)
    if n==0: log.append({"file":rel,"status":"NOT_FOUND","old":old[:60],"note":note}); print("!! NOT FOUND", rel, old[:50]); return
    t=t.replace(old,new) if count=="all" else t.replace(old,new,count)
    f.write_text(t,"utf-8"); log.append({"file":rel,"status":"OK","n":n,"old":old[:60],"new":new[:60],"note":note}); print("OK", rel, "|", note)

# page 25: exam math_2017 session2 p2 — similarity angle is +2π/3 (zoom verified)
rep("math/bac_math_2017_sujet1_session2.txt", r"وزاويته $-\frac{2\pi}{3}$", r"وزاويته $\frac{2\pi}{3}$", note="angle sign: source has +2π/3")
# page 11: physic_2023 sol p2 — numerical application missing ×10
rep("physic/bac_physic_2023_sujet1_solution.txt", r"$\pi = 15.10^{-3} - 0,147$", r"$\pi = 15.10^{-3} \times 10 - 0,147$", note="restore ×10 (g) in π calculation")
# page 31: islamic_2024 sol p2 — العلة cell
rep("islamic/bac_islamic_2024_sujet2_solution.txt", "الثَّمنيّة والتَّذخيرة", "الثَّمنيّة والنَّقديّة", note="word substitution → source word")
# page 21: svt_2017 sol p1 — typo + synonym substitution
rep("svt/bac_svt_2017_sujet2_solution_session2.txt", "يلمخص انتقال", "يلخص انتقال", note="typo")
rep("svt/bac_svt_2017_sujet2_solution_session2.txt", "للعضلة المنقبضة ( الباسطة)", "للعضلة المتقلصة ( الباسطة)", note="synonym → printed word")
# page 27: physic_2016 exam p2 — typo
rep("physic/bac_physic_2016_sujet2_session2.txt", "اكتب عبارة النسبية $\\frac{A_0}{A(t)}$", "اكتب عبارة النسبة $\\frac{A_0}{A(t)}$", note="typo النسبية→النسبة")
# page 19: svt_2023 sol p3 — LLM preamble line
rep("svt/bac_svt_2023_sujet1_solution.txt", "أيضاً فيما يلي تفريغ شامل ودقيق للوثيقة:\n\n", "", note="strip LLM preamble")
# page 14: physic_2025 sol p3 — header year
rep("physic/bac_physic_2025_sujet2_solution.txt", "امتحان شهادة البكالوريا دورة 2023 / اختبار مادة: العلوم الفيزيائية", "امتحان شهادة البكالوريا دورة 2025 / اختبار مادة: العلوم الفيزيائية", note="header year 2023→2025 (image reads 2025)")
# page 06: math_2009 sol p1 — AC vector third component (zoom verified: (1;1;1))
rep("math/bac_math_2009_sujet1_solution.txt", r"\overrightarrow{AC}\begin{pmatrix}1\\1\\-1\end{pmatrix}", r"\overrightarrow{AC}\begin{pmatrix}1\\1\\1\end{pmatrix}", note="AC=(1;1;1) per source; AB·AC=0 consistent")

json.dump(log, open(P/"data/processed/visual_fixes_log.json","w",encoding="utf-8"), indent=1, ensure_ascii=False)
print("\n", sum(1 for l in log if l["status"]=="OK"), "applied,", sum(1 for l in log if l["status"]!="OK"), "not found")
