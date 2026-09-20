"""Verify the Anthropic key and measure exact per-page cost of a formula-only extraction with Claude."""
import os, sys, json, base64, io, time
from pathlib import Path
import anthropic, pymupdf

P = Path("C:/Users/samsung/Desktop/bac-genius")
for line in (P/".env").read_text("utf-8").splitlines():
    line=line.strip()
    if line and not line.startswith("#") and "=" in line:
        k,_,v=line.partition("="); os.environ.setdefault(k.strip(), v.strip())
client = anthropic.Anthropic()

MODEL = sys.argv[1] if len(sys.argv)>1 else "claude-opus-5"
PRICE = {"claude-opus-5":(5,25),"claude-sonnet-5":(2,10),"claude-haiku-4-5":(1,5)}[MODEL]

manifest=json.loads((P/"data/raw/manifest.json").read_text("utf-8")); ocr=json.loads((P/"data/processed/ocr_manifest.json").read_text("utf-8"))
pdf={Path(r["path"]).stem:P/r["path"] for r in manifest if not r.get("duplicate") and r["path"].lower().endswith(".pdf")}
stem, pn = "bac_math_2013_sujet1_solution", 3   # a dense, already-known page
pp=ocr.get(stem,{}).get("pdf_pages",[]); idx=(pp[pn-1]-1) if (pp and len(pp)>=pn) else pn-1
doc=pymupdf.open(str(pdf[stem])); pix=doc[idx].get_pixmap(dpi=150); png=pix.tobytes("png"); doc.close()
b64=base64.standard_b64encode(png).decode()

PROMPT = """This is a page from an Algerian BAC exam or its official answer key.
Transcribe EVERY mathematical/scientific expression and every number that appears on the page, as LaTeX, one per line, in reading order.
Include: equations, inequalities, limits, fractions, exponents, roots, vectors, intervals, numeric values with units, scoring marks (0.25, 0.5, 2×0.25 ...), isotope notation, chemical equations.
Exclude: prose, headers, page numbers. Do not explain. Do not correct anything — transcribe exactly what is printed, even if it looks mathematically wrong.
Output only the list."""

t0=time.time()
resp = client.messages.create(
    model=MODEL, max_tokens=4000,
    thinking={"type":"adaptive"} if MODEL!="claude-haiku-4-5" else anthropic.NOT_GIVEN,
    output_config={"effort":"low"} if MODEL!="claude-haiku-4-5" else anthropic.NOT_GIVEN,
    messages=[{"role":"user","content":[{"type":"image","source":{"type":"base64","media_type":"image/png","data":b64}},{"type":"text","text":PROMPT}]}],
)
dt=time.time()-t0
text="".join(b.text for b in resp.content if b.type=="text")
u=resp.usage
cost=u.input_tokens*PRICE[0]/1e6 + u.output_tokens*PRICE[1]/1e6
print("MODEL", MODEL, "| stop", resp.stop_reason, "| {:.1f}s".format(dt))
print("tokens in={} out={} | cost ${:.4f}/page".format(u.input_tokens, u.output_tokens, cost))
print("--- first 25 lines ---"); print("\n".join(text.splitlines()[:25]))
