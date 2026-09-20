import json, re
from pathlib import Path
from collections import Counter
P = Path("C:/Users/samsung/Desktop/bac-genius")
d = json.loads((P/"data/processed/claude_second_extract_checkpoint.json").read_text("utf-8"))
rs = [r for r in d["results"] if r["status"] == "OK"]

def is_noise(s):
    c = s.strip().strip("`").strip()
    if len(c) <= 2: return True
    if c.startswith("```") or c in ("$", "$$", "---", "***"): return True
    if re.fullmatch(r"\\?(?:begin|end)\{[^}]*\}", c): return True
    if re.fullmatch(r"[\-\*\u2022\u2013\s]+", c): return True
    if re.fullmatch(r"\$?\(?\\?[A-Za-z]\)?\$?", c): return True            # (C), (T), $g$
    if re.fullmatch(r"\$?\(?\\[A-Za-z]+\)?\$?", c): return True             # (\Delta), (\Gamma)
    if re.fullmatch(r"\$?\(?[A-Za-z]_\{?[A-Za-z0-9]\}?\)?\$?", c): return True  # (C_f), z_A
    if re.fullmatch(r"\$?\\?(?:mathbb\{[A-Z]\}|[A-Z])\$?", c): return True  # \mathbb{R}
    return False

flag = []
for r in rs:
    ru = [u for u in r["unmatched"] if not is_noise(u["claude"])]
    if ru: flag.append({"key": r["key"], "subject": r["subject"], "n_unmatched": len(ru), "n_items": r["n_items"], "unmatched": ru})
print("Pages with REAL unmatched items:", len(flag), "/", len(rs))
print("By subject:", dict(Counter(f["subject"] for f in flag)))
hi = [f for f in flag if f["n_unmatched"] >= 3]; mid = [f for f in flag if f["n_unmatched"] == 2]; lo = [f for f in flag if f["n_unmatched"] == 1]
print(">=3 unmatched:", len(hi), "| 2:", len(mid), "| 1:", len(lo))
print()
for f in sorted(flag, key=lambda x: -x["n_unmatched"])[:14]:
    print("--", f["key"], "|", f["n_unmatched"], "/", f["n_items"])
    for u in f["unmatched"][:4]: print("     ", u["claude"][:85], "| best", u["best"])
json.dump(flag, open(P/"data/processed/claude_disagreements.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
