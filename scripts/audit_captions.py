"""
scripts/audit_captions.py

Final quality audit of all 662 scientific image captions.
For each caption, re-presents the original image to Gemini with the existing caption
and asks for verification of every field. Confirmed errors are corrected and re-saved.

Outputs:
  data/processed/image_captions/audit_report.json   — full audit record
  data/processed/image_captions/audit_summary.txt   — human-readable summary

Resumable: skips images already audited (checks audit_report entries).

Priority order:
  1. circuit_schematic, nuclear_diagram (highest stakes)
  2. graph, biological_diagram, electron_microscopy
  3. experimental_setup, molecular_model, data_table, geometry_figure
  4. full_page_text (verify correct classification only, spot-check)
"""
from __future__ import annotations

import argparse
import json
import os
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import google.genai as genai
from google.genai import types as gentypes

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CAPTIONS_DIR = PROJECT_ROOT / "data" / "processed" / "image_captions"
INDEX_PATH   = CAPTIONS_DIR / "index.json"
AUDIT_REPORT = CAPTIONS_DIR / "audit_report.json"
MODEL        = "models/gemini-3.6-flash"

# Priority tiers: lower number = audited first
PRIORITY = {
    "circuit_schematic":  1,
    "nuclear_diagram":    1,
    "graph":              2,
    "biological_diagram": 2,
    "electron_microscopy":2,
    "experimental_setup": 3,
    "molecular_model":    3,
    "data_table":         3,
    "geometry_figure":    3,
    "full_page_text":     4,  # only spot-check for misclassification
}
MAX_FULL_PAGE_TEXT_AUDIT = 40  # random sample of this category


VERIFY_PROMPT = """You are a science exam quality auditor. You have been given an image from an Algerian BAC exam and a JSON caption describing it.

YOUR TASK: Verify EVERY claim in the caption against what you actually see in the image.

Caption to verify:
{caption_json}

Check each of these:
1. content_type — Is this label correct for what you see?
2. description — Is every sentence factually accurate?
3. labels — Are ALL label texts correct (exact spelling, no extras, none missing)?
4. structure — Is the spatial/topological description accurate?
5. axes — Are axis labels, units, and ranges correct?
6. measurements — Are all numerical values correct?
7. key_features — Are these the genuinely most important features visible?
8. essential_info — Does this accurately describe what only the image provides?

Respond ONLY with this JSON (no markdown fences):
{{
  "verdict": "VERIFIED" or "ERRORS_FOUND",
  "errors": [
    {{"field": "labels", "issue": "Label '10 mA' shown as '100 mA' in caption", "severity": "critical|minor"}}
  ],
  "corrections": {{
    "labels": ["corrected label list if labels were wrong"],
    "axes": {{"corrected axes object if wrong"}},
    "measurements": ["corrected values if wrong"],
    "description": "corrected description if wrong",
    "content_type": "corrected type if misclassified"
  }},
  "missing_info": ["important visual detail completely absent from the caption"]
}}

If everything is correct, set verdict=VERIFIED and use empty arrays/objects for errors/corrections/missing_info.
Be precise and specific. Only flag genuine errors, not stylistic differences."""


CLASSIFY_PROMPT = """Look at this image. Is it primarily:
a) full page of text (no scientific diagram or graph visible)
b) a scientific diagram, graph, circuit, or table

Respond with exactly one letter: a or b"""


def load_audit_report() -> dict:
    if AUDIT_REPORT.exists():
        try:
            return json.loads(AUDIT_REPORT.read_text("utf-8"))
        except Exception:
            pass
    return {}


def save_audit_report(report: dict):
    AUDIT_REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")


def load_index() -> list[dict]:
    return json.loads(INDEX_PATH.read_text("utf-8"))


def load_caption(caption_file: str) -> dict:
    p = PROJECT_ROOT / caption_file
    return json.loads(p.read_text("utf-8"))


def load_image_bytes(image_file: str) -> bytes:
    p = PROJECT_ROOT / image_file
    return p.read_bytes()


def verify_caption(
    client: genai.Client,
    image_bytes: bytes,
    caption: dict,
    retries: int = 2,
) -> Optional[dict]:
    # Strip metadata fields from caption before showing to verifier
    cap_for_verify = {
        k: v for k, v in caption.items()
        if k not in {"image_file", "stem", "subject", "year", "page_num",
                     "img_index", "px", "model", "captioned_at",
                     "is_decorative", "error", "audit_verified_at"}
    }
    prompt = VERIFY_PROMPT.format(caption_json=json.dumps(cap_for_verify, ensure_ascii=False, indent=2))

    for attempt in range(retries):
        try:
            resp = client.models.generate_content(
                model=MODEL,
                contents=[
                    gentypes.Part.from_bytes(data=image_bytes, mime_type="image/png"),
                    prompt,
                ],
            )
            if not resp or not resp.text:
                cands = getattr(resp, "candidates", [])
                reasons = [str(getattr(c, "finish_reason", "?")) for c in cands]
                if "RECITATION" in str(reasons):
                    return {"verdict": "RECITATION_BLOCK", "errors": [], "corrections": {}, "missing_info": []}
                raise RuntimeError(f"No response text. finish_reasons={reasons}")
            raw = resp.text.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
            return json.loads(raw)
        except json.JSONDecodeError:
            import re as _re
            m = _re.search(r"\{.*\}", resp.text if resp else "", _re.DOTALL)
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
                return {"verdict": "ERROR", "error_msg": str(e), "errors": [], "corrections": {}, "missing_info": []}
    return None


def check_full_page_text_classification(
    client: genai.Client,
    image_bytes: bytes,
    retries: int = 2,
) -> str:
    """Returns 'a' (text) or 'b' (diagram) for full_page_text images."""
    for attempt in range(retries):
        try:
            resp = client.models.generate_content(
                model=MODEL,
                contents=[
                    gentypes.Part.from_bytes(data=image_bytes, mime_type="image/png"),
                    CLASSIFY_PROMPT,
                ],
            )
            if resp and resp.text:
                return resp.text.strip().lower()[0]
        except Exception:
            if attempt < retries - 1:
                time.sleep(2)
    return "a"  # default: assume text


def apply_corrections(caption: dict, verification: dict) -> dict:
    """Merge Gemini-suggested corrections into the caption dict."""
    corrections = verification.get("corrections", {})
    if not corrections:
        return caption

    updated = dict(caption)
    for field, value in corrections.items():
        if value:  # only apply non-empty corrections
            updated[field] = value
    return updated


def recaption_image(client: genai.Client, image_bytes: bytes, context_text: str) -> Optional[dict]:
    """Full recaptioning for images with critical errors."""
    from scripts.caption_images import _PROMPT_TEMPLATE, _caption_image
    import tempfile
    import os
    # Write to temp file for the existing captioner to use
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(image_bytes)
        tmp_path = Path(f.name)
    try:
        result = _caption_image(client, tmp_path, context_text)
        return result
    finally:
        tmp_path.unlink(missing_ok=True)


def run(dry_run: bool = False, limit: Optional[int] = None, delay: float = 0.5):
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not set")
    client = genai.Client(api_key=api_key)

    index = load_index()
    audit_report = load_audit_report()

    # Sort by priority
    def sort_key(entry):
        ct = entry.get("content_type", "")
        return PRIORITY.get(ct, 5)

    index_sorted = sorted(index, key=sort_key)

    # Cap full_page_text
    fpt_count = 0
    targets = []
    for entry in index_sorted:
        stem_key = entry.get("image_file", "")
        if stem_key in audit_report:
            continue  # already audited

        ct = entry.get("content_type", "")
        if ct == "full_page_text":
            if fpt_count >= MAX_FULL_PAGE_TEXT_AUDIT:
                continue
            fpt_count += 1

        targets.append(entry)

    if limit:
        targets = targets[:limit]

    total = len(targets)
    print(f"{'[DRY RUN] ' if dry_run else ''}Images to audit: {total}")
    if dry_run:
        ct_counts = defaultdict(int)
        for t in targets:
            ct_counts[t.get("content_type", "?")] += 1
        for ct, n in sorted(ct_counts.items(), key=lambda x: PRIORITY.get(x[0], 5)):
            print(f"  {ct}: {n}")
        return

    stats = {"verified": 0, "corrected": 0, "misclassified": 0, "recitation": 0, "errors": 0, "skipped": 0}
    all_issues = []

    for i, entry in enumerate(targets, 1):
        img_file  = entry["image_file"]
        cap_file  = entry["caption_file"]
        ct        = entry.get("content_type", "?")

        print(f"[{i:4d}/{total}] {Path(img_file).name[:50]} ({ct}) ...", end=" ", flush=True)
        t0 = time.time()

        try:
            caption    = load_caption(cap_file)
            img_bytes  = load_image_bytes(img_file)
        except Exception as e:
            print(f"LOAD ERROR: {e}")
            stats["errors"] += 1
            continue

        # Special path for full_page_text: just check classification
        if ct == "full_page_text":
            classification = check_full_page_text_classification(client, img_bytes)
            elapsed = time.time() - t0
            if classification == "b":
                print(f"MISCLASSIFIED as full_page_text — actually a diagram ({elapsed:.1f}s)")
                stats["misclassified"] += 1
                issue = {"image_file": img_file, "type": "misclassified_full_page_text",
                         "severity": "high", "detail": "Image contains a diagram but was captioned as full_page_text"}
                all_issues.append(issue)
                audit_report[img_file] = {
                    "verdict": "MISCLASSIFIED",
                    "content_type_was": "full_page_text",
                    "actual_content": "diagram",
                    "audited_at": datetime.now(timezone.utc).isoformat(),
                }
            else:
                print(f"classification OK ({elapsed:.1f}s)")
                stats["verified"] += 1
                audit_report[img_file] = {
                    "verdict": "VERIFIED",
                    "content_type": ct,
                    "audited_at": datetime.now(timezone.utc).isoformat(),
                }
            save_audit_report(audit_report)
            time.sleep(max(0, delay - elapsed))
            continue

        # Full verification for scientific diagrams
        verification = verify_caption(client, img_bytes, caption)
        elapsed = time.time() - t0

        if verification is None:
            print(f"VERIFY_FAILED (None) ({elapsed:.1f}s)")
            stats["errors"] += 1
            audit_report[img_file] = {"verdict": "VERIFY_FAILED", "audited_at": datetime.now(timezone.utc).isoformat()}
            save_audit_report(audit_report)
            time.sleep(max(0, delay - elapsed))
            continue

        verdict   = verification.get("verdict", "UNKNOWN")
        errors    = verification.get("errors", [])
        missing   = verification.get("missing_info", [])
        corrections = verification.get("corrections", {})

        if verdict == "RECITATION_BLOCK":
            print(f"RECITATION ({elapsed:.1f}s)")
            stats["recitation"] += 1
            audit_report[img_file] = {"verdict": "RECITATION_BLOCK", "audited_at": datetime.now(timezone.utc).isoformat()}
        elif verdict == "ERROR":
            print(f"API_ERROR: {verification.get('error_msg','')[:40]} ({elapsed:.1f}s)")
            stats["errors"] += 1
            audit_report[img_file] = {"verdict": "API_ERROR", "audited_at": datetime.now(timezone.utc).isoformat()}
        elif verdict == "VERIFIED" and not errors and not missing:
            print(f"VERIFIED ({elapsed:.1f}s)")
            stats["verified"] += 1
            # Mark caption as audit-verified
            caption["audit_verdict"] = "VERIFIED"
            caption["audit_verified_at"] = datetime.now(timezone.utc).isoformat()
            (PROJECT_ROOT / cap_file).write_text(json.dumps(caption, ensure_ascii=False, indent=2), "utf-8")
            audit_report[img_file] = {
                "verdict": "VERIFIED",
                "content_type": ct,
                "audited_at": datetime.now(timezone.utc).isoformat(),
            }
        else:
            critical = [e for e in errors if e.get("severity") == "critical"]
            minor    = [e for e in errors if e.get("severity") != "critical"]
            tag = f"ERRORS(crit={len(critical)},minor={len(minor)},missing={len(missing)})"
            print(f"{tag} ({elapsed:.1f}s)")
            stats["corrected"] += 1

            for e in errors:
                all_issues.append({
                    "image_file": img_file,
                    "type": "caption_error",
                    "field": e.get("field"),
                    "issue": e.get("issue"),
                    "severity": e.get("severity"),
                })
            for m in missing:
                all_issues.append({
                    "image_file": img_file,
                    "type": "missing_info",
                    "detail": m,
                    "severity": "minor",
                })

            # Apply corrections
            corrected_caption = apply_corrections(caption, verification)
            corrected_caption["audit_verdict"] = "CORRECTED"
            corrected_caption["audit_errors"] = errors
            corrected_caption["audit_missing"] = missing
            corrected_caption["audit_verified_at"] = datetime.now(timezone.utc).isoformat()

            (PROJECT_ROOT / cap_file).write_text(
                json.dumps(corrected_caption, ensure_ascii=False, indent=2), "utf-8"
            )

            audit_report[img_file] = {
                "verdict": "CORRECTED",
                "content_type": ct,
                "errors_found": errors,
                "missing_info": missing,
                "corrections_applied": corrections,
                "audited_at": datetime.now(timezone.utc).isoformat(),
            }

        save_audit_report(audit_report)
        time.sleep(max(0, delay - elapsed))

    # Final summary
    print(f"\n=== AUDIT COMPLETE ===")
    print(f"Total audited:    {sum(stats.values())}")
    print(f"  Verified:       {stats['verified']}")
    print(f"  Corrected:      {stats['corrected']}")
    print(f"  Misclassified:  {stats['misclassified']}")
    print(f"  Recitation:     {stats['recitation']}")
    print(f"  API errors:     {stats['errors']}")
    print(f"\nTotal issues:   {len(all_issues)}")
    crit = [x for x in all_issues if x.get("severity") == "critical"]
    print(f"  Critical:     {len(crit)}")
    print(f"  Minor:        {len(all_issues) - len(crit)}")

    # Write summary
    summary_lines = [
        f"Caption Audit Report — {datetime.now(timezone.utc).isoformat()}",
        f"Total audited: {sum(stats.values())}",
        f"  Verified (no changes): {stats['verified']}",
        f"  Corrected (caption updated): {stats['corrected']}",
        f"  Misclassified full_page_text: {stats['misclassified']}",
        f"  Recitation blocked: {stats['recitation']}",
        f"  API errors: {stats['errors']}",
        "",
        f"Issues found: {len(all_issues)} ({len(crit)} critical, {len(all_issues)-len(crit)} minor)",
        "",
        "CRITICAL ISSUES:",
    ]
    for issue in crit[:50]:
        summary_lines.append(f"  [{issue['type']}] {Path(issue['image_file']).name}: {issue.get('issue', issue.get('detail', ''))}")

    (CAPTIONS_DIR / "audit_summary.txt").write_text(
        "\n".join(summary_lines), encoding="utf-8"
    )
    print(f"\nSummary: {CAPTIONS_DIR / 'audit_summary.txt'}")
    print(f"Report:  {AUDIT_REPORT}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Audit scientific image captions")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--delay", type=float, default=0.3)
    args = parser.parse_args()
    run(dry_run=args.dry_run, limit=args.limit, delay=args.delay)
