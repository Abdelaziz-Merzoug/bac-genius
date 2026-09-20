"""
scripts/caption_images.py

Generate structured Gemini captions for embedded scientific images in SVT, Physics, and Math.
Captions are stored in data/processed/image_captions/{subject}/{image_stem}.json

Resumable: skips images that already have a caption file.
Run with --dry-run to count targets without making API calls.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from PIL import Image

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import google.genai as genai
from google.genai import types as gentypes

PROJECT_ROOT   = Path(__file__).resolve().parent.parent
IMGS_DIR       = PROJECT_ROOT / "data" / "processed" / "images"
CAPTIONS_DIR   = PROJECT_ROOT / "data" / "processed" / "image_captions"
TEXTS_DIR      = PROJECT_ROOT / "data" / "processed" / "texts"

SCIENCE_SUBJECTS = {"svt", "physic", "math"}
MODEL = "models/gemini-3.6-flash"

# Minimum pixel count to consider an image meaningful
MIN_PX = 10_000

# Images larger than this AND with portrait A4 ratio are full-page scans
# (Gemini already processed the full page text — don't re-caption)
FULL_PAGE_PX = 2_000_000
A4_RATIO_RANGE = (0.55, 0.85)   # w/h for portrait A4/Letter scan


def _is_full_page_scan(img_path: Path) -> bool:
    try:
        with Image.open(img_path) as im:
            w, h = im.size
            px = w * h
            ratio = w / h if h else 0
            return px > FULL_PAGE_PX and A4_RATIO_RANGE[0] < ratio < A4_RATIO_RANGE[1]
    except Exception:
        return False


def _pixel_count(img_path: Path) -> int:
    try:
        with Image.open(img_path) as im:
            return im.size[0] * im.size[1]
    except Exception:
        return 0


def _parse_image_stem(img_name: str) -> dict:
    """Parse bac_{subj}_{year}_..._page{N}_img{M} filename."""
    stem = Path(img_name).stem   # e.g. bac_svt_2009_sujet1_page3_img2
    parts = stem.rsplit("_page", 1)
    file_stem = parts[0]         # bac_svt_2009_sujet1
    page_img = parts[1] if len(parts) > 1 else "1_img1"
    pi_parts = page_img.rsplit("_img", 1)
    page_num = int(pi_parts[0]) if pi_parts[0].isdigit() else 1
    img_idx  = int(pi_parts[1]) if len(pi_parts) > 1 and pi_parts[1].isdigit() else 1

    seg = file_stem.split("_")
    subject = seg[1] if len(seg) > 1 else "unknown"
    year    = int(seg[2]) if len(seg) > 2 and seg[2].isdigit() else None

    return {
        "stem": file_stem,
        "subject": subject,
        "year": year,
        "page_num": page_num,
        "img_index": img_idx,
    }


def _page_text_excerpt(stem: str, subject: str, page_num: int, chars: int = 1500) -> str:
    p = TEXTS_DIR / subject / f"{stem}.txt"
    if not p.exists():
        return ""
    import re
    txt = p.read_text("utf-8")
    parts = re.split(r"\[PAGE \d+\]", txt)
    if page_num <= len(parts) - 1:
        return parts[page_num].strip()[:chars]
    return txt[:chars]


_PROMPT_TEMPLATE = """You are analyzing an image from an Algerian BAC (baccalauréat) high school exam.

The surrounding page text (for context only):
---
{page_text}
---

Analyze the IMAGE carefully and produce a structured JSON response with these exact fields:

{{
  "content_type": one of: biological_diagram | graph | circuit_schematic | geometry_figure | nuclear_diagram | experimental_setup | data_table | electron_microscopy | molecular_model | decorative | full_page_text,
  "is_decorative": true/false (true if logo, header, seal, or blank space with no exam content),
  "description": "2-4 sentence description of what the image shows",
  "labels": ["exact text of every label, arrow annotation, or callout visible in the image"],
  "structure": "spatial arrangement and relationships between elements (topology of circuit, connections between neurons, etc.)",
  "axes": {{"x_label": "...", "x_range": "...", "y_label": "...", "y_range": "..."}} or null if not a graph,
  "measurements": ["list every numerical value, scale bar, ratio, or measurement visible"],
  "key_features": ["the 3-5 most important visual details a student must observe to answer the question"],
  "essential_info": "2-3 sentences stating exactly what information is ONLY available from this image and cannot be derived from the text alone"
}}

Rules:
- Transcribe labels exactly as they appear (Arabic or Latin script).
- If the image is decorative/irrelevant, set is_decorative=true and use minimal other fields.
- Never invent information not visible in the image.
- For graphs: read off axis scale values, curve shapes, inflection points, asymptotic behaviour.
- For circuits: describe every component and how they connect (series/parallel, switch positions).
- For biological diagrams: name every labeled structure and describe spatial relationships.
- Respond with valid JSON only, no markdown fences."""


def _caption_image(
    client: genai.Client,
    img_path: Path,
    page_text: str,
    retries: int = 3,
) -> Optional[dict]:
    with open(img_path, "rb") as f:
        img_bytes = f.read()

    prompt = _PROMPT_TEMPLATE.format(page_text=page_text[:1500] if page_text else "(none)")

    for attempt in range(retries):
        try:
            response = client.models.generate_content(
                model=MODEL,
                contents=[
                    gentypes.Part.from_bytes(data=img_bytes, mime_type="image/png"),
                    prompt,
                ],
            )
            raw = response.text.strip()
            # Strip markdown fences if model added them
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
            return json.loads(raw)
        except json.JSONDecodeError:
            # Try to extract JSON block
            import re as _re
            m = _re.search(r"\{.*\}", response.text, _re.DOTALL)
            if m:
                try:
                    return json.loads(m.group())
                except Exception:
                    pass
            if attempt < retries - 1:
                time.sleep(2)
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(3)
            else:
                return {"error": str(e), "content_type": "error"}
    return None


def collect_targets(dry_run: bool = False) -> list[dict]:
    targets = []
    for subj in SCIENCE_SUBJECTS:
        subj_dir = IMGS_DIR / subj
        if not subj_dir.exists():
            continue
        for img_path in sorted(subj_dir.glob("*.png")):
            px = _pixel_count(img_path)
            if px < MIN_PX:
                continue
            if _is_full_page_scan(img_path):
                continue
            # Already captioned?
            info = _parse_image_stem(img_path.name)
            cap_path = CAPTIONS_DIR / subj / f"{img_path.stem}.json"
            if cap_path.exists():
                continue
            targets.append({
                "img_path": img_path,
                "cap_path": cap_path,
                "px": px,
                **info,
            })
    return targets


def run(dry_run: bool = False, limit: Optional[int] = None, delay: float = 1.0):
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not set in .env")
    client = genai.Client(api_key=api_key)

    CAPTIONS_DIR.mkdir(parents=True, exist_ok=True)
    for subj in SCIENCE_SUBJECTS:
        (CAPTIONS_DIR / subj).mkdir(exist_ok=True)

    targets = collect_targets(dry_run)
    # Sort: largest (most complex) diagrams first
    targets.sort(key=lambda t: t["px"], reverse=True)
    if limit:
        targets = targets[:limit]

    total = len(targets)
    print(f"{'[DRY RUN] ' if dry_run else ''}Targets: {total} images to caption")

    if dry_run:
        by_subj = {}
        for t in targets:
            by_subj.setdefault(t["subject"], 0)
            by_subj[t["subject"]] += 1
        for subj, cnt in sorted(by_subj.items()):
            print(f"  {subj}: {cnt}")
        return

    ok = 0
    skipped = 0
    errors = 0

    for i, t in enumerate(targets, 1):
        img_path: Path = t["img_path"]
        cap_path: Path = t["cap_path"]

        page_text = _page_text_excerpt(t["stem"], t["subject"], t["page_num"])

        print(f"[{i:4d}/{total}] {img_path.name} ({t['px']//1000}K px) ...", end=" ", flush=True)
        t0 = time.time()

        result = _caption_image(client, img_path, page_text)
        elapsed = time.time() - t0

        if result is None:
            print(f"ERROR (None) ({elapsed:.1f}s)")
            errors += 1
            continue

        if result.get("error"):
            print(f"ERROR: {result['error'][:60]} ({elapsed:.1f}s)")
            errors += 1
        elif result.get("is_decorative"):
            print(f"decorative — skip ({elapsed:.1f}s)")
            skipped += 1
        else:
            print(f"{result.get('content_type','?')} ({elapsed:.1f}s)")
            ok += 1

        # Always save (including decorative flag and errors)
        record = {
            "image_file": img_path.relative_to(PROJECT_ROOT).as_posix(),
            "stem": t["stem"],
            "subject": t["subject"],
            "year": t["year"],
            "page_num": t["page_num"],
            "img_index": t["img_index"],
            "px": t["px"],
            "model": MODEL,
            "captioned_at": datetime.now(timezone.utc).isoformat(),
            **result,
        }
        cap_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

        # Rate limiting
        time.sleep(max(0, delay - elapsed))

    print(f"\nDone: {ok} captioned, {skipped} decorative/skipped, {errors} errors")
    print(f"Captions at: {CAPTIONS_DIR}")

    # Write index
    _write_index()


def _write_index():
    index = []
    for cap_path in sorted(CAPTIONS_DIR.rglob("*.json")):
        if cap_path.name == "index.json":
            continue
        try:
            data = json.loads(cap_path.read_text("utf-8"))
            if data.get("is_decorative"):
                continue
            index.append({
                "caption_file": cap_path.relative_to(PROJECT_ROOT).as_posix(),
                "image_file": data.get("image_file"),
                "stem": data.get("stem"),
                "subject": data.get("subject"),
                "year": data.get("year"),
                "page_num": data.get("page_num"),
                "content_type": data.get("content_type"),
            })
        except Exception:
            pass
    idx_path = CAPTIONS_DIR / "index.json"
    idx_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Index: {len(index)} scientific image captions → {idx_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Caption scientific images with Gemini")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None, help="Max images to process")
    parser.add_argument("--delay", type=float, default=0.5, help="Min seconds between API calls")
    args = parser.parse_args()
    run(dry_run=args.dry_run, limit=args.limit, delay=args.delay)
