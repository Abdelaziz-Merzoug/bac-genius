"""Append [SCORES — read from source image] blocks from data/processed/score_reads.json (my own visual reads).
Only appends; never alters existing text. Skips pages that already hold a [SCORES block, and NO_SCORES/RECHECK entries."""
import re, json, sys
from pathlib import Path
P=Path("C:/Users/samsung/Desktop/bac-genius"); T=P/"data/processed/texts"
reads=json.loads((P/"data/processed/score_reads.json").read_text("utf-8"))
LOG=P/"data/processed/recover_scores_visual_log.json"
log=json.loads(LOG.read_text("utf-8")) if LOG.exists() else []
done_keys={l["key"] for l in log}

def parse(c):
    pages={}; cur=0; lines=[]
    for line in c.splitlines():
        m=re.match(r"^\[PAGE\s+(\d+)\]\s*$", line.strip())
        if m:
            if cur>0: pages[cur]="\n".join(lines)
            cur=int(m.group(1)); lines=[]
        else:
            if cur>0: lines.append(line)
    if cur>0: pages[cur]="\n".join(lines)
    return pages

def append(stem, pn, block):
    subj=stem.split("_")[1]; f=T/subj/(stem+".txt"); c=f.read_text("utf-8")
    out=[]; cur=0; done=False
    for ln in c.split("\n"):
        m=re.match(r"^\[PAGE\s+(\d+)\]\s*$", ln.strip())
        if m:
            if cur==pn and not done:
                while out and out[-1].strip()=="": out.pop()
                out.append(""); out.append(block); out.append(""); done=True
            cur=int(m.group(1))
        out.append(ln)
    if cur==pn and not done:
        while out and out[-1].strip()=="": out.pop()
        out.append(""); out.append(block); out.append(""); done=True
    f.write_text("\n".join(out),"utf-8"); return done

n_ok=n_skip=0
for key,val in reads.items():
    if key in done_keys: continue
    stem,pn=key.rsplit("__p",1); pn=int(pn); subj=stem.split("_")[1]
    if val.startswith("NO_SCORES") or val.startswith("RECHECK") or val.startswith("SCORES_ALREADY_IN_TEXT"):
        log.append({"key":key,"status":"SKIP","reason":val}); n_skip+=1; continue
    cur=parse((T/subj/(stem+".txt")).read_text("utf-8")).get(pn,"")
    if "[SCORES" in cur:
        log.append({"key":key,"status":"SKIP","reason":"already has [SCORES block"}); n_skip+=1; continue
    block="[SCORES — read from source image, top→bottom: {0}]".format(val)
    ok=append(stem,pn,block)
    log.append({"key":key,"status":"APPENDED" if ok else "FAIL","block":block}); n_ok+=1
    print("+", key)
LOG.write_text(json.dumps(log,indent=1,ensure_ascii=False),"utf-8")
print("appended:",n_ok,"| skipped:",n_skip,"| log total:",len(log))
