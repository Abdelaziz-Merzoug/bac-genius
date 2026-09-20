"""Verify ALL 853 captions against their images. Checkpointed, parallel."""
import json, os, sys, time, threading
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter

sys.stdout.reconfigure(line_buffering=True)

PROJECT = Path("C:/Users/samsung/Desktop/bac-genius")
CAPTIONS = PROJECT / "data/processed/image_captions"
CHECKPOINT = PROJECT / "data/processed/verify_captions_checkpoint.json"
SUBJECTS = ["arabe", "english", "francais", "islamic", "math", "physic", "svt"]
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

caps = []
for s in SUBJECTS:
    d = CAPTIONS / s
    if not d.exists(): continue
    for cf in sorted(d.glob("*.json")):
        try:
            data = json.loads(cf.read_text("utf-8"))
        except Exception as e:
            caps.append({"cap_file": str(cf.relative_to(PROJECT)), "error": "invalid json"}); continue
        caps.append({
            "cap_file": str(cf.relative_to(PROJECT)).replace("\\", "/"),
            "image_file": data.get("image_file", ""),
            "subject": s,
            "description": data.get("description", ""),
            "labels": data.get("labels", []),
            "measurements": data.get("measurements", []),
            "content_type": data.get("content_type", ""),
            "is_decorative": data.get("is_decorative"),
        })
print("Captions to verify: {0}".format(len(caps)))

completed = {}
if CHECKPOINT.exists():
    try: completed = {r["cap_file"]: r for r in json.loads(CHECKPOINT.read_text("utf-8")).get("results", [])}
    except: pass
remaining = [c for c in caps if c["cap_file"] not in completed]
print("Done: {0} | Remaining: {1}".format(len(completed), len(remaining)))

PROMPT = """You are verifying whether a caption faithfully describes an image from an Algerian BAC exam.

First line must be exactly:
CAPTION_VERDICT: ACCURATE
or
CAPTION_VERDICT: INACCURATE

A caption is ACCURATE if it correctly identifies what the image shows and does not invent, misidentify, or misstate any labels, numbers, axes, or scientific content. Being brief or omitting minor details is fine.

A caption is INACCURATE if it: describes the wrong kind of object; states labels/numbers/text that are not in the image; misidentifies the subject (e.g. calls a circuit a graph); or omits something essential that changes the meaning.

Second line: REASON: one sentence.

CAPTION TO VERIFY:
Description: {desc}
Labels: {labels}
Measurements: {meas}
Content type: {ctype}"""

lock = threading.Lock()
results = list(completed.values())
n = [0]; t0 = time.time()

def save():
    tmp = CHECKPOINT.with_suffix(".tmp")
    tmp.write_text(json.dumps({"results": results, "timestamp": datetime.now(timezone.utc).isoformat()},
                              indent=0, ensure_ascii=False), "utf-8")
    tmp.replace(CHECKPOINT)

def verify(c):
    if "error" in c:
        return dict(c, verdict="ERROR", reason=c["error"])
    ip = PROJECT / c["image_file"]
    try: data = ip.read_bytes()
    except Exception as e: return dict(c, verdict="ERROR", reason="image read: " + str(e)[:80])
    prompt = PROMPT.format(desc=c["description"][:800], labels=json.dumps(c["labels"], ensure_ascii=False)[:400],
                           meas=json.dumps(c["measurements"], ensure_ascii=False)[:300], ctype=c["content_type"])
    for attempt in range(4):
        try:
            resp = client.models.generate_content(
                model=MODEL,
                contents=[Part.from_bytes(data=data, mime_type="image/png"), prompt],
                config=types.GenerateContentConfig(temperature=0.0, max_output_tokens=1500,
                    thinking_config=types.ThinkingConfig(thinking_budget=800)),
            )
            rt = (resp.text or "").strip(); up = rt[:120].upper()
            if "CAPTION_VERDICT: ACCURATE" in up or "CAPTION_VERDICT:ACCURATE" in up: v = "ACCURATE"
            elif "CAPTION_VERDICT: INACCURATE" in up or "CAPTION_VERDICT:INACCURATE" in up: v = "INACCURATE"
            elif "INACCURATE" in up: v = "INACCURATE"
            elif "ACCURATE" in up: v = "ACCURATE"
            else: v = "UNCLEAR"
            reason = ""
            for ln in rt.splitlines():
                if ln.upper().startswith("REASON:"): reason = ln[7:].strip(); break
            return dict(c, verdict=v, reason=reason[:300])
        except Exception as e:
            err = str(e)
            if "429" in err or "RESOURCE_EXHAUSTED" in err: time.sleep(20 + attempt*15)
            elif "503" in err or "500" in err: time.sleep(10)
            else: return dict(c, verdict="ERROR", reason=err[:100])
    return dict(c, verdict="ERROR", reason="max retries")

with ThreadPoolExecutor(max_workers=WORKERS) as ex:
    futs = [ex.submit(verify, c) for c in remaining]
    for f in as_completed(futs):
        r = f.result()
        with lock:
            results.append(r); completed[r["cap_file"]] = r; n[0] += 1
            if n[0] % 50 == 0:
                save()
                cc = Counter(x["verdict"] for x in results)
                el = time.time()-t0; rate = n[0]/el
                print("  {0}/{1} | {2} | ETA {3:.0f}min".format(len(completed), len(caps), dict(cc),
                      (len(remaining)-n[0])/rate/60 if rate else 0))
save()
cc = Counter(x["verdict"] for x in results)
print("\nDONE {0}/{1}: {2}".format(len(completed), len(caps), dict(cc)))
(PROJECT / "data/processed/verify_all_captions.json").write_text(
    json.dumps({"total": len(caps), "verdicts": dict(cc), "results": results}, indent=0, ensure_ascii=False), "utf-8")
