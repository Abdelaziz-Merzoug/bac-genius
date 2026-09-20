"""
Post-process extracted arabe text files:
- Detect pages with garbled sidebar content (>70% short isolated Arabic tokens)
- Replace garbled pages with [PAGE REPROCESS NEEDED] marker
- Keep good pages untouched
- Write a report of files that need Gemini re-processing
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _is_arabic_char(c: str) -> bool:
    cp = ord(c)
    return (
        0x0600 <= cp <= 0x06FF
        or 0x0750 <= cp <= 0x077F
        or 0x08A0 <= cp <= 0x08FF
        or 0xFB50 <= cp <= 0xFDFF
        or 0xFE70 <= cp <= 0xFEFF
    )


def _suspicious_ratio(page_text: str) -> float:
    """Fraction of non-empty lines that look like garbled sidebar tokens."""
    lines = [l.strip() for l in page_text.split("\n") if l.strip()]
    if not lines:
        return 0.0
    suspicious = 0
    for line in lines:
        ar_chars = sum(1 for c in line if _is_arabic_char(c))
        if ar_chars == 0:
            continue
        tokens = line.split()
        if not tokens:
            continue
        avg_tok_len = sum(len(t) for t in tokens) / len(tokens)
        non_space = line.replace(" ", "")
        ar_density = ar_chars / max(len(non_space), 1)
        # Suspicious: mostly Arabic + very short tokens (avg ≤ 4 chars)
        if avg_tok_len <= 4 and ar_density > 0.6:
            suspicious += 1
    return suspicious / len(lines)


def _has_reversed_bkalia(text: str) -> bool:
    return "ايرولاكب" in text


def cleanup_file(path: Path, dry_run: bool = False) -> dict:
    text = path.read_text(encoding="utf-8")
    # Split on [PAGE N] markers, preserving them
    parts = re.split(r"(\[PAGE \d+\])", text)

    new_parts = []
    garbled_pages = []
    has_reversed = _has_reversed_bkalia(text)

    i = 0
    while i < len(parts):
        part = parts[i]
        if re.match(r"\[PAGE \d+\]", part):
            marker = part
            page_content = parts[i + 1] if i + 1 < len(parts) else ""
            ratio = _suspicious_ratio(page_content)
            page_num = int(re.search(r"\d+", marker).group())

            if ratio > 0.60:
                garbled_pages.append((page_num, f"{ratio:.0%}"))
                new_parts.append(marker)
                new_parts.append(
                    "\n[PAGE REPROCESS NEEDED - vertical sidebar garble detected]\n\n"
                )
                i += 2
            else:
                new_parts.append(marker)
                if i + 1 < len(parts):
                    new_parts.append(parts[i + 1])
                    i += 2
                else:
                    i += 1
        else:
            new_parts.append(part)
            i += 1

    new_text = "".join(new_parts)
    changed = new_text != text

    if changed and not dry_run:
        path.write_text(new_text, encoding="utf-8")

    return {
        "file": path.name,
        "garbled_pages": garbled_pages,
        "has_reversed_bkalia": has_reversed,
        "changed": changed,
    }


def main():
    dry_run = "--dry-run" in sys.argv
    subject = "arabe"
    text_dir = ROOT / "data" / "processed" / "texts" / subject

    if not text_dir.exists():
        print(f"Directory not found: {text_dir}")
        sys.exit(1)

    files = sorted(text_dir.glob("*.txt"))
    print(f"Processing {len(files)} {subject} text files" + (" (dry run)" if dry_run else ""))
    print()

    reprocess_needed = []
    for f in files:
        result = cleanup_file(f, dry_run=dry_run)
        if result["garbled_pages"] or result["has_reversed_bkalia"]:
            status = "CLEANED" if result["changed"] else "FLAGGED"
            print(f"  [{status}] {result['file']}")
            if result["garbled_pages"]:
                print(f"           garbled pages: {result['garbled_pages']}")
            if result["has_reversed_bkalia"]:
                print(f"           has reversed 'بكالوريا' (sidebar in header)")
            reprocess_needed.append(result["file"])

    print()
    print(f"Files needing Gemini re-processing: {len(reprocess_needed)}")
    # Write reprocess list
    reprocess_file = ROOT / "data" / "processed" / "texts" / "arabe_reprocess_needed.txt"
    if not dry_run:
        reprocess_file.write_text("\n".join(reprocess_needed), encoding="utf-8")
        print(f"List written to: {reprocess_file}")
    print()
    print("Next steps:")
    print("  1. Enable billing on Google AI Studio")
    print("  2. Revoke and replace the exposed API key in .env")
    print("  3. Run: python ingestion/ocr_clean.py --force --subjects arabe")


if __name__ == "__main__":
    main()
