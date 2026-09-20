"""Remove ERROR entries from fix log and image-source checkpoint so re-running the scripts retries them."""
import json, sys
from pathlib import Path
P = Path("C:/Users/samsung/Desktop/bac-genius/data/processed")

fl = P/"fix_corrupted_log.json"
d = json.loads(fl.read_text("utf-8"))
before = len(d)
d = {k:v for k,v in d.items() if v.get("status") != "ERROR"}
fl.write_text(json.dumps(d, indent=1, ensure_ascii=False), "utf-8")
print("fix_corrupted_log: removed {0} ERROR entries".format(before-len(d)))

ck = P/"verify_images_source_checkpoint.json"
if ck.exists():
    c = json.loads(ck.read_text("utf-8"))
    b = len(c["results"])
    c["results"] = [r for r in c["results"] if r.get("iverdict") != "ERROR"]
    ck.write_text(json.dumps(c, indent=0, ensure_ascii=False), "utf-8")
    print("verify_images_source_checkpoint: removed {0} ERROR entries".format(b-len(c["results"])))
