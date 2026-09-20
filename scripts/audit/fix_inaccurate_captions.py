"""Regenerate the 15 INACCURATE captions, then re-verify each. Keep original if re-verify fails."""
import json, os, re, sys, time
from pathlib import Path
from datetime import datetime, timezone

sys.stdout.reconfigure(line_buffering=True)
PROJECT = Path("C:/Users/samsung/Desktop/bac-genius")
for line in (PROJECT / ".env").read_text("utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k,_,v = line.partition("="); os.environ.setdefault(k.strip(), v.strip())
from google import genai
from google.genai import types
from google.genai.types import Part
client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
MODEL = "models/gemini-3.6-flash"

vc = json.loads((PROJECT/"data/processed/verify_all_captions.json").read_text("utf-8"))
bad = [r for r in vc["results"] if r["verdict"]=="INACCURATE"]
print("Captions to regenerate: {0}".format(len(bad)))

GEN = """Describe this image from an Algerian BAC exam (Experimental Sciences stream) with STRICT factual accuracy.

Return ONLY a JSON object (no markdown fences) with these keys:
"content_type": one of "graph","biological_diagram","physics_circuit","chemistry_schematic","geometric_figure","table","equation_snippet","text_snippet","electron_microscopy","logo","decorative","other"
"is_decorative": true/false
"description": 1-3 sentences describing exactly what is shown. Do NOT invent labels, numbers, units, or structures that are not visible.
"labels": list of text labels/annotations actually visible in the image (exact transcription; empty list if none)
"structure": one sentence on layout/composition
"axes": null, or {{"x": "...", "y": "..."}} with axis names/units EXACTLY as shown (null if not a graph or if axes unlabeled)
"measurements": list of numeric values/units actually visible (empty if none)
"key_features": list of 1-4 salient features
"essential_meaning": one sentence: what a student must take from this image

Rules: transcribe Arabic/French exactly; if a sign, exponent, or symbol is visible, copy it exactly; never guess."""

VER = """First line exactly: CAPTION_VERDICT: ACCURATE or CAPTION_VERDICT: INACCURATE
Second line: REASON: one sentence.
A caption is INACCURATE if it invents, misidentifies, or misstates labels, numbers, signs, axes, or scientific content.

CAPTION: {desc}
Labels: {labels}
Content type: {ctype}"""

def call(contents, max_tokens, budget):
    for a in range(4):
        try:
            r = client.models.generate_content(model=MODEL, contents=contents,
                config=types.GenerateContentConfig(temperature=0.0, max_output_tokens=max_tokens,
                    thinking_config=types.ThinkingConfig(thinking_budget=budget)))
            return (r.text or "").strip()
        except Exception as e:
            s=str(e)
            if "429" in s or "RESOURCE_EXHAUSTED" in s: time.sleep(20+a*15)
            elif "503" in s or "500" in s: time.sleep(10)
            else: raise
    raise RuntimeError("max retries")

log = []
for r in bad:
    cf = PROJECT / r["cap_file"]
    orig = json.loads(cf.read_text("utf-8"))
    img = (PROJECT / orig["image_file"]).read_bytes()
    entry = {"cap_file": r["cap_file"], "orig_reason": r["reason"]}
    ok = False
    for attempt in range(2):
        try:
            raw = call([Part.from_bytes(data=img, mime_type="image/png"), GEN], 2000, 1000)
        except Exception as e:
            entry["status"]="ERROR"; entry["note"]="gen: "+str(e)[:100]; break
        raw = re.sub(r"^```(?:json)?\s*", "", raw).strip(); raw = re.sub(r"\s*```$", "", raw).strip()
        try:
            newcap = json.loads(raw)
        except Exception:
            m = re.search(r"\{.*\}", raw, re.S)
            try: newcap = json.loads(m.group(0)) if m else None
            except Exception: newcap = None
        if not newcap or "description" not in newcap:
            entry.setdefault("attempts",[]).append("parse_fail"); continue
        try:
            vr = call([Part.from_bytes(data=img, mime_type="image/png"),
                       VER.format(desc=newcap.get("description","")[:800],
                                  labels=json.dumps(newcap.get("labels",[]),ensure_ascii=False)[:400],
                                  ctype=newcap.get("content_type",""))], 1500, 800)
        except Exception as e:
            entry["status"]="ERROR"; entry["note"]="verify: "+str(e)[:100]; break
        v = "ACCURATE" if ("CAPTION_VERDICT: ACCURATE" in vr.upper()[:80] or "CAPTION_VERDICT:ACCURATE" in vr.upper()[:80]) else ("INACCURATE" if "INACCURATE" in vr.upper()[:80] else "UNCLEAR")
        entry.setdefault("attempts",[]).append({"verdict":v, "reason":vr[:200]})
        if v=="ACCURATE":
            merged = dict(orig)
            for k in ["content_type","is_decorative","description","labels","structure","axes","measurements","key_features","essential_meaning"]:
                if k in newcap: merged[k]=newcap[k]
            merged["captioned_at"]=datetime.now(timezone.utc).isoformat()
            merged["recaptioned_reason"]=r["reason"][:200]
            cf.write_text(json.dumps(merged, indent=2, ensure_ascii=False), "utf-8")
            entry["status"]="FIXED_VERIFIED"; ok=True; break
    if not ok and "status" not in entry:
        entry["status"]="UNRESOLVED"
    log.append(entry)
    print("  {0}: {1}".format(cf.name, entry["status"]))
    time.sleep(1)

from collections import Counter
print("\nRESULT:", dict(Counter(e["status"] for e in log)))
(PROJECT/"data/processed/fix_captions_log.json").write_text(json.dumps(log, indent=1, ensure_ascii=False), "utf-8")
