"""
Downstream-goal-oriented checks on the CURRENT corpus:
 1. Year metadata: filename year vs years mentioned in page-1 header (forecasting depends on year)
 2. Subject metadata: filename subject vs subject named in header
 3. Exam <-> solution structural alignment: exercise numbers/counts present in exam vs solution of same stem
 4. Truncation: does the last page of each file carry a footer / end marker; does any page end mid-sentence
 5. Point totals: exercise point declarations in exams sum to 20 (per سujet); flags wrong-digit headers
 6. Question-number gaps inside exam pages (e.g. 1,2,4 with 3 missing)
"""
import re, json
from pathlib import Path
from collections import Counter, defaultdict
P=Path("C:/Users/samsung/Desktop/bac-genius"); T=P/"data/processed/texts"
S=["arabe","english","francais","islamic","math","physic","svt"]
SUBJ_AR={"arabe":["اللغة العربية","العربية"],"english":["الإنجليزية","الانجليزية","English","الإنكليزية"],"francais":["الفرنسية","Français","francais","français"],
 "islamic":["العلوم الإسلامية","الاسلامية","الإسلامية"],"math":["الرياضيات"],"physic":["العلوم الفيزيائية","الفيزيائية","فيزيائية"],"svt":["علوم الطبيعة","الطبيعة والحياة","الطبيعة و الحياة"]}
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

files={}
for s in S:
    for f in sorted((T/s).glob("*.txt")):
        files[f.stem]=(s,parse_pages(f.read_text("utf-8")))

# 1+2 metadata
year_issues=[]; subj_issues=[]
for stem,(s,pages) in files.items():
    m=re.search(r"_(\d{4})_",stem); fy=int(m.group(1)) if m else None
    head="\n".join(pages[p][:600] for p in sorted(pages)[:2])
    years=set(int(y) for y in re.findall(r"(?<!\d)(20[0-3]\d)(?!\d)",head))
    # remove years that are clearly page-numbering like "2 من 4" etc. (4-digit only so fine)
    if fy and years and fy not in years:
        # tolerate session2 files whose paper says previous year? no — flag all
        year_issues.append({"stem":stem,"file_year":fy,"header_years":sorted(years),"snippet":head[:120].replace("\n"," ")})
    if fy and not years:
        year_issues.append({"stem":stem,"file_year":fy,"header_years":[],"snippet":head[:120].replace("\n"," ")})
    ok=any(k in head for k in SUBJ_AR[s])
    if not ok: subj_issues.append({"stem":stem,"subject":s,"snippet":head[:120].replace("\n"," ")})

# 3 exam<->solution structure
EX=re.compile(r"التمرين\s+(?:الأول|الثاني|الثالث|الرابع|الخامس|[1-5])|Exercice\s*\d|EXERCICE|Part\s+(?:One|Two|Three)|PART\s+(?:ONE|TWO|THREE)|الموضوع\s+(?:الأول|الثاني)",re.I)
pair_issues=[]
for stem,(s,pages) in files.items():
    if "solution" in stem: continue
    sol=stem.replace("_session1","").replace("_session2","")
    cands=[k for k in files if k.startswith(stem.split("_session")[0]) and "solution" in k]
    # exact stem+_solution or with session suffix
    exact=[k for k in cands if k==stem+"_solution" or k==stem.replace("_session","_solution_session")]
    if not exact: continue
    ex_txt="\n".join(pages.values()); so_txt="\n".join(files[exact[0]][1].values())
    ex_ex=set(m.group(0).strip() for m in EX.finditer(ex_txt)); so_ex=set(m.group(0).strip() for m in EX.finditer(so_txt))
    ex_n=len(set(re.findall(r"التمرين\s+(?:الأول|الثاني|الثالث|الرابع|الخامس)",ex_txt)))
    so_n=len(set(re.findall(r"التمرين\s+(?:الأول|الثاني|الثالث|الرابع|الخامس)",so_txt)))
    if ex_n and so_n and abs(ex_n-so_n)>=2:
        pair_issues.append({"exam":stem,"solution":exact[0],"exam_exercises":ex_n,"solution_exercises":so_n})

# 4 truncation: last page lacks footer/end marker AND ends without terminal punctuation
trunc=[]
END=re.compile(r"(صفحة\s*\d+\s*(?:من|/)\s*\d+|انتهى الموضوع|Page\s*\d+\s*(?:sur|/|of)\s*\d+|FIN DU SUJET|END OF|Fin du sujet)",re.I)
for stem,(s,pages) in files.items():
    last=pages[max(pages)]
    tail=last[-300:]
    if not END.search(tail):
        lastline=last.strip().splitlines()[-1].strip() if last.strip() else ""
        if lastline and not re.search(r"[.!?؟:،)\]\}]$|\$$",lastline) and len(lastline)<120:
            trunc.append({"stem":stem,"page":max(pages),"last_line":lastline[:90]})

# 5 point totals in exams
pts_issues=[]
for stem,(s,pages) in files.items():
    if "solution" in stem: continue
    txt="\n".join(pages.values())
    # per sujet: split on الموضوع الثاني
    parts=re.split(r"الموضوع\s+الثاني",txt)
    for i,part in enumerate(parts[:2]):
        pts=[float(x.replace(",",".")) for x in re.findall(r"\(\s*(\d{1,2}(?:[.,]\d+)?)\s*(?:نقاط|نقطة|ن\.?|points?|pts)\s*\)",part)]
        pts=[p for p in pts if 0<p<=20]
        if len(pts)>=2 and abs(sum(pts)-20)>0.01 and s in("math","physic","svt","islamic","arabe"):
            pts_issues.append({"stem":stem,"sujet":i+1,"points":pts,"sum":sum(pts)})

# 6 numbering gaps in exam pages: sequences like 1) 2) 4)
gap_issues=[]
for stem,(s,pages) in files.items():
    if "solution" in stem: continue
    for pn,t in pages.items():
        nums=[int(x) for x in re.findall(r"(?:^|\n)\s*(?:\*\*)?\s*(\d{1,2})\s*[)\-–]\s",t)]
        # find runs
        seq=[];
        for n in nums:
            if seq and n==seq[-1]+2: gap_issues.append({"stem":stem,"page":pn,"seq":seq[-3:]+[n]})
            seq.append(n)

out={"year_issues":year_issues,"subject_issues":subj_issues,"pair_issues":pair_issues,"truncation":trunc,"points_issues":pts_issues,"numbering_gaps":gap_issues[:200]}
json.dump(out,open(P/"data/processed/downstream_checks.json","w",encoding="utf-8"),indent=1,ensure_ascii=False)
print("1. year mismatches (file vs header):", len(year_issues))
for y in year_issues[:15]: print("   ", y["stem"], y["file_year"], "->", y["header_years"], "|", y["snippet"][:70])
print("2. subject mismatches:", len(subj_issues))
for x in subj_issues[:8]: print("   ", x["stem"], "|", x["snippet"][:80])
print("3. exam/solution exercise-count mismatch (>=2):", len(pair_issues))
for x in pair_issues[:10]: print("   ", x)
print("4. possible truncation (no footer, ends mid-line):", len(trunc))
for x in trunc[:12]: print("   ", x["stem"], "p"+str(x["page"]), "|", x["last_line"])
print("5. exam point totals != 20:", len(pts_issues))
for x in pts_issues[:12]: print("   ", x["stem"], "sujet", x["sujet"], x["points"], "=", x["sum"])
print("6. numbering gaps in exam pages:", len(gap_issues))
for x in gap_issues[:10]: print("   ", x)
