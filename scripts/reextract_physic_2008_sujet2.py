"""
scripts/reextract_physic_2008_sujet2.py

Re-extracts page 3 of bac_physic_2008_sujet2 using Gemini Vision with an explicit
RTL correction prompt to fix the confirmed character-level Arabic garbling.
Updates the existing .txt file in-place.
"""
from __future__ import annotations
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import google.genai as genai
from google.genai import types as gentypes

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODEL = "models/gemini-3.6-flash"

TARGET_STEM = "bac_physic_2008_sujet2"
TARGET_PAGE = 3


def find_pdf() -> Path:
    for d in (
        PROJECT_ROOT / "data" / "raw" / "exams",
        PROJECT_ROOT / "data" / "raw",
    ):
        for p in d.rglob("*.pdf"):
            if TARGET_STEM in p.stem.lower() or TARGET_STEM.replace("_", "") in p.stem.lower().replace("_", ""):
                return p
    raise FileNotFoundError(f"Cannot find PDF for {TARGET_STEM}")


def render_pdf_page(pdf_path: Path, page_num: int) -> bytes:
    """Render a single PDF page to PNG bytes using pdfplumber → PIL."""
    import io
    import pdfplumber
    with pdfplumber.open(str(pdf_path)) as pdf:
        page = pdf.pages[page_num - 1]   # 0-indexed
        try:
            pil_img = page.to_image(resolution=200).original
            buf = io.BytesIO()
            pil_img.save(buf, format="PNG")
            return buf.getvalue()
        except Exception as e:
            # Fallback: send PDF bytes directly and let Gemini handle page selection
            raise RuntimeError(
                f"pdfplumber.to_image() failed: {e}. "
                "Try installing poppler or use the PDF direct upload fallback."
            )


def get_pdf_bytes_for_gemini(pdf_path: Path) -> bytes:
    """Return raw PDF bytes for direct Gemini upload as file."""
    return pdf_path.read_bytes()


PROMPT = (
    "This image contains Arabic text from a 2008 Algerian BAC chemistry exam (physique/chimie). "
    "The text has been garbled by a software bug that reversed characters. "
    "List every chemical formula, equation, numerical value (concentrations, volumes, masses, pH values, "
    "temperatures), and experimental setup description that you can see in the image. "
    "Also note the structure of the exercise (question numbers, sub-parts). "
    "Use bullet points under clear section headings. Focus only on scientific/mathematical content."
)


def reextract_page(client: genai.Client, pdf_path: Path) -> str:
    try:
        page_bytes = render_pdf_page(pdf_path, TARGET_PAGE)
        part = gentypes.Part.from_bytes(data=page_bytes, mime_type="image/png")
    except RuntimeError as e:
        print(f"  render failed: {e}")
        print("  → Falling back to PDF direct upload to Gemini")
        pdf_bytes = get_pdf_bytes_for_gemini(pdf_path)
        part = gentypes.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")

    response = client.models.generate_content(
        model=MODEL,
        contents=[part, PROMPT],
    )
    if response is None:
        raise RuntimeError("Gemini returned None response")
    if response.text is None:
        # Inspect finish_reason / safety
        cands = getattr(response, "candidates", [])
        reasons = [getattr(c, "finish_reason", "?") for c in cands]
        safety = [getattr(c, "safety_ratings", []) for c in cands]
        raise RuntimeError(f"response.text is None. finish_reasons={reasons} safety={safety}")
    return response.text.strip()


def update_txt_file(txt_path: Path, new_page_text: str, page_num: int):
    """Replace the [PAGE N] section in the txt file with corrected text."""
    content = txt_path.read_text("utf-8")
    parts = re.split(r"(\[PAGE \d+\])", content)
    # parts = ['before', '[PAGE 1]', 'page1text', '[PAGE 2]', 'page2text', ...]
    page_marker = f"[PAGE {page_num}]"

    new_parts = []
    i = 0
    replaced = False
    while i < len(parts):
        if parts[i] == page_marker and not replaced:
            new_parts.append(parts[i])
            if i + 1 < len(parts) and not parts[i + 1].startswith("[PAGE "):
                new_parts.append("\n" + new_page_text + "\n")
                i += 2
                replaced = True
            else:
                new_parts.append("\n" + new_page_text + "\n")
                i += 1
                replaced = True
        else:
            new_parts.append(parts[i])
            i += 1

    if not replaced:
        raise ValueError(f"Page marker {page_marker} not found in {txt_path}")

    txt_path.write_text("".join(new_parts), encoding="utf-8")
    return replaced


def main():
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not set")
    client = genai.Client(api_key=api_key)

    pdf_path = find_pdf()
    print(f"PDF: {pdf_path}")

    txt_path = PROJECT_ROOT / "data" / "processed" / "texts" / "physic" / f"{TARGET_STEM}.txt"
    if not txt_path.exists():
        raise FileNotFoundError(f"Text file not found: {txt_path}")

    # Show current page 3 text
    current = txt_path.read_text("utf-8")
    parts = re.split(r"\[PAGE \d+\]", current)
    current_p3 = parts[TARGET_PAGE].strip() if TARGET_PAGE < len(parts) else "(not found)"
    print(f"\n--- CURRENT page {TARGET_PAGE} text (first 300 chars) ---")
    print(current_p3[:300])
    print("---\n")

    print(f"Re-extracting page {TARGET_PAGE} with Gemini Vision...")
    new_text = reextract_page(client, pdf_path)
    print(f"\n--- NEW page {TARGET_PAGE} text (first 300 chars) ---")
    print(new_text[:300])
    print("---\n")

    # Save backup
    backup = txt_path.with_suffix(".txt.bak_p3_reextract")
    backup.write_text(current, "utf-8")
    print(f"Backup saved: {backup}")

    update_txt_file(txt_path, new_text, TARGET_PAGE)
    print(f"Updated: {txt_path}")

    # Log the correction
    log = {
        "stem": TARGET_STEM,
        "subject": "physic",
        "page": TARGET_PAGE,
        "action": "gemini_reextract_rtl_corrected",
        "model": MODEL,
        "corrected_at": datetime.now(timezone.utc).isoformat(),
        "old_text_excerpt": current_p3[:200],
        "new_text_excerpt": new_text[:200],
    }
    log_path = PROJECT_ROOT / "data" / "processed" / "quality_reports" / "physic" / f"{TARGET_STEM}_p3_reextract.json"
    log_path.write_text(json.dumps(log, ensure_ascii=False, indent=2), "utf-8")
    print(f"Log: {log_path}")


if __name__ == "__main__":
    main()
