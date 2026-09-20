"""log_visual_fix.py <file-rel-to-texts> <old> <new> <note>  — append an entry to visual_fixes_log.json (avoids shell escaping issues)."""
import json, sys, datetime
from pathlib import Path
L = Path("C:/Users/samsung/Desktop/bac-genius/data/processed/visual_fixes_log.json")
log = json.loads(L.read_text("utf-8"))
f, old, new, note = sys.argv[1], sys.argv[2], sys.argv[3], " ".join(sys.argv[4:])
log.append({"file": f, "status": "OK", "n": 1, "old": old, "new": new, "note": note, "ts": datetime.datetime.now().isoformat(timespec="minutes")})
L.write_text(json.dumps(log, indent=1, ensure_ascii=False), "utf-8")
print("visual_fixes_log:", len(log))
