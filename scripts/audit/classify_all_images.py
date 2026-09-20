"""
Classify EVERY image >=50px in either dimension via Gemini.
Category + meaningful flag + brief description. Checkpointed, parallel.
"""
import json, os, sys, time, threading
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.stdout.reconfigure(line_buffering=True)

PROJECT = Path("C:/Users/samsung/Desktop/bac-genius")
IMAGES = PROJECT / "data/processed/images"
CHECKPOINT = PROJECT / "data/processed/classify_images_checkpoint.json"
WORKERS = 4

for line in (PROJECT / ".env").read_text("utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

from google import genai
from google.genai import types
from google.genai.types import Part

client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
MODEL = "models/gemini-3.6-flash"

inventory = json.loads((PROJECT / "data/processed/image_inventory.json").read_text("utf-8"))
targets = [r for r in inventory if max(r["w"], r["h"]) >= 50]
print("Images >=50px to classify: {0} / {1}".format(len(targets), len(inventory)))

completed = {}
if CHECKPOINT.exists():
    try:
        completed = {r["file"]: r for r in json.loads(CHECKPOINT.read_text("utf-8")).get("results", [])}
    except: pass
remaining = [r for r in targets if r["file"] not in completed]
print("Done: {0} | Remaining: {1}".format(len(completed), len(remaining)))

PROMPT = """Classify this image extracted from an Algerian BAC exam PDF.

First line must be exactly one of:
CATEGORY: DECORATIVE
CATEGORY: TEXTUAL
CATEGORY: EQUATION
CATEGORY: GRAPH
CATEGORY: DIAGRAM
CATEGORY: TABLE
CATEGORY: FIGURE
CATEGORY: LOGO
CATEGORY: BLANK

Definitions:
- DECORATIVE: lines, borders, bullets, ornaments, separators, checkboxes
- LOGO: ministry seal, institutional emblem, flag
- BLANK: empty/white/uniform with no content
- TEXTUAL: a scanned block of ordinary text (Arabic/French/English prose)
- EQUATION: a mathematical formula or expression rendered as an image
- GRAPH: a plotted curve, chart, axes
- DIAGRAM: scientific schematic (circuit, biological structure, geometry, apparatus)
- TABLE: a data table
- FIGURE: any other exam-relevant illustration

Second line:
MEANINGFUL: YES or NO   (YES = carries exam content a student needs; NO = decorative/logo/blank)

Third line:
DESC: one short sentence describing the content."""

lock = threading.Lock()
results = list(completed.values())
n_done = [0]
t0 = time.time()

def save():
    tmp = CHECKPOINT.with_suffix(".tmp")
    tmp.write_text(json.dumps({"results": results, "timestamp": datetime.now(timezone.utc).isoformat()},
                              indent=0, ensure_ascii=False), "utf-8")
    tmp.replace(CHECKPOINT)

def classify(rec):
    p = IMAGES / rec["subject"] / rec["file"]
    try:
        data = p.read_bytes()
    except Exception as e:
        return dict(rec, category="ERROR", meaningful=None, desc=str(e)[:100])
    for attempt in range(4):
        try:
            resp = client.models.generate_content(
                model=MODEL,
                contents=[Part.from_bytes(data=data, mime_type="image/png"), PROMPT],
                config=types.GenerateContentConfig(temperature=0.0, max_output_tokens=200),
            )
            rt = (resp.text or "").strip()
            up = rt.upper()
            cat = "UNCLEAR"
            for c in ["DECORATIVE","TEXTUAL","EQUATION","GRAPH","DIAGRAM","TABLE","FIGURE","LOGO","BLANK"]:
                if "CATEGORY: " + c in up or "CATEGORY:" + c in up:
                    cat = c; break
            meaningful = None
            if "MEANINGFUL: YES" in up or "MEANINGFUL:YES" in up: meaningful = True
            elif "MEANINGFUL: NO" in up or "MEANINGFUL:NO" in up: meaningful = False
            desc = ""
            for ln in rt.splitlines():
                if ln.upper().startswith("DESC:"):
                    desc = ln[5:].strip(); break
            return dict(rec, category=cat, meaningful=meaningful, desc=desc[:200])
        except Exception as e:
            err = str(e)
            if "429" in err or "RESOURCE_EXHAUSTED" in err: time.sleep(20 + attempt*15)
            elif "503" in err or "500" in err: time.sleep(10)
            else: return dict(rec, category="ERROR", meaningful=None, desc=err[:100])
    return dict(rec, category="ERROR", meaningful=None, desc="max retries")

with ThreadPoolExecutor(max_workers=WORKERS) as ex:
    futs = [ex.submit(classify, r) for r in remaining]
    for f in as_completed(futs):
        r = f.result()
        with lock:
            results.append(r); completed[r["file"]] = r; n_done[0] += 1
            if n_done[0] % 50 == 0:
                save()
                el = time.time() - t0; rate = n_done[0]/el
                eta = (len(remaining)-n_done[0])/rate/60 if rate else 0
                from collections import Counter
                cc = Counter(x["category"] for x in results)
                print("  {0}/{1} | {2} | {3:.1f}/s ETA {4:.0f}min".format(
                    len(completed), len(targets), dict(cc), rate, eta))
save()

from collections import Counter
cc = Counter(x["category"] for x in results)
mm = Counter(x["meaningful"] for x in results)
print("\nDONE {0}/{1}".format(len(completed), len(targets)))
print("Categories:", dict(cc))
print("Meaningful:", dict(mm))
(PROJECT / "data/processed/image_classification.json").write_text(
    json.dumps({"total_classified": len(completed), "categories": dict(cc),
                "meaningful": {str(k): v for k, v in mm.items()}, "results": results},
               indent=0, ensure_ascii=False), "utf-8")
