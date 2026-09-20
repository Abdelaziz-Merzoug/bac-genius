"""adj_log.py <key> <verdict: OK|GAP_FIXED|GAP_OPEN> <note>"""
import json, sys, datetime
from pathlib import Path
LOG=Path("C:/Users/samsung/Desktop/bac-genius/data/processed/adjudication_visual_log.json")
log=json.loads(LOG.read_text("utf-8")) if LOG.exists() else []
key,verdict,note=sys.argv[1],sys.argv[2]," ".join(sys.argv[3:])
log=[l for l in log if l["key"]!=key]
log.append({"key":key,"verdict":verdict,"note":note,"method":"my own visual read of the 100-DPI page render","ts":datetime.datetime.now().isoformat(timespec="minutes")})
LOG.write_text(json.dumps(log,indent=1,ensure_ascii=False),"utf-8")
from collections import Counter
print(len(log),"logged |",dict(Counter(l["verdict"] for l in log)))
