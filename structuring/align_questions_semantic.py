"""Stage 1d — MEANING-based question<->answer alignment (no API; local multilingual embeddings).

For every exam unit (exercise/section) and its paired answer-key unit:
  1. candidate answer blocks = the answer key cut at every numbered marker (any nesting) or, when it
     carries no numbering, at paragraph boundaries;
  2. score(question, block) = 0.55 * embedding cosine (paraphrase-multilingual-MiniLM-L12-v2)
                            + 0.30 * lexical overlap of anchor tokens (LaTeX symbols, numbers, keywords)
                            + 0.15 * numbering agreement;
  3. monotonic alignment (answers follow question order) by dynamic programming, each question may stay
     unmatched; a match is kept only above a confidence threshold.
Numbering is therefore evidence, not the decision. Every record carries the evidence
(emb, lex, label_agree, score) and a match class: strong | good | label_only | none.
Output: data/structured/{subject}_questions.jsonl (overwrites the label-only version), stats in dataset_summary.json,
        data/structured/alignment_review_sample.jsonl (random sample per class for human review).
usage: align_questions_semantic.py [subjects...]"""
import json, re, sys, random, hashlib
import numpy as np
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from segment_exams import virtual_lines, item_label, TASHKEEL_RX, CELL_NOISE_RX, PAGE_NOISE_RX, HEAD_RX, norm_head

def clean(text):
    """Text used for SCORING only: drop page footers/headers, exercise headings, score cells, [FIGURE] tags."""
    keep = []
    for l in text.splitlines():
        t = CELL_NOISE_RX.sub("", l).strip()
        if not t or PAGE_NOISE_RX.match(t) or HEAD_RX.match(norm_head(t)) or re.fullmatch(r"[\d.,\s×x+()]+", t): continue
        keep.append(t)
    return "\n".join(keep)

OUT = Path("C:/Users/samsung/Desktop/bac-genius/data/structured")
CACHE = OUT/"_emb_cache.npz"
SUBJECTS = ["physic", "math", "svt", "arabe", "islamic", "francais", "english"]
W_EMB, W_LEX, W_LAB = 0.55, 0.30, 0.15
T_STRONG, T_GOOD, MIN_EMB, T_CONTRA, T_LABEL = 0.60, 0.40, 0.25, 0.50, 0.30   # semantic support required, numbering only helps
MIN_EMB_LABEL, REUSE_PENALTY = 0.12, 0.10   # "a) T b) F"-style answers share no words with the question

def variants(label):
    """Hierarchical labels come out RTL-reversed from the text layer of the answer keys (2.1 -> 1.2),
    so a label is compared in both orientations."""
    return {label, ".".join(reversed(label.split(".")))}

def label_agree(q, b):
    """1 = same label (either orientation); 0.5 = one is a prefix of the other (2 vs 2.2); 0 otherwise."""
    if not q or not b: return 0.0
    Q, B = variants(q), variants(b)
    if Q & B: return 1.0
    return 0.5 if any(x.startswith(y + ".") or y.startswith(x + ".") for x in Q for y in B) else 0.0

STOP = set("""في من على إلى عن أن إن ما لا لم لن هذا هذه ذلك تلك التي الذي الذين ثم أو و كما كل بين حتى إذا كان كانت هو هي هل بم ماذا لماذا كيف أي مع عند قد لكن غير
the of a an to and or in on for is are be by with that this it as at from des les une un le la et en du de que qui dans pour sur est sont au aux ce cette ces
""".split())
TOK_RX = re.compile(r"\$[^$]+\$|[A-Za-z_]\w*|\d+(?:[.,]\d+)?|[\u0621-\u064A]{3,}")

def anchors(text):
    """Anchor tokens: LaTeX macro/identifier tokens, numbers, words >=3 letters minus stopwords."""
    t = TASHKEEL_RX.sub("", CELL_NOISE_RX.sub("", text))
    out = set()
    for tok in TOK_RX.findall(t):
        if tok.startswith("$"):
            for s in re.findall(r"\\[a-zA-Z]+|[A-Za-z]\w*|\d+(?:[.,]\d+)?", tok):
                if s not in ("\\text", "\\left", "\\right", "\\,", "\\;"): out.add(s)
        else:
            w = tok.lower()
            if w not in STOP and len(w) >= 2: out.add(w)
    return out

def lexical(q, a):
    A, B = anchors(q), anchors(a)
    if not A or not B: return 0.0
    inter = len(A & B)
    return inter / (len(A) ** 0.5 * len(B) ** 0.5)   # cosine on binary bags (less biased by long answers)

def blocks_of(solution):
    """Answer blocks with (label|None, text). Cut at every numbered marker; fall back to paragraphs."""
    lines = list(virtual_lines(solution["text"].splitlines()))
    blocks, cur = [], None
    for l in lines:
        lab = item_label(l)
        if lab is not None:
            if cur: blocks.append(cur)
            cur = {"label": lab, "text": l}
        elif cur: cur["text"] += "\n" + l
        else: cur = {"label": None, "text": l}
    if cur: blocks.append(cur)
    if sum(b["label"] is not None for b in blocks) == 0:   # unnumbered key -> paragraphs
        paras, cur = [], []
        for l in lines:
            if not l.strip():
                if cur: paras.append({"label": None, "text": "\n".join(cur)}); cur = []
            else: cur.append(l)
        if cur: paras.append({"label": None, "text": "\n".join(cur)})
        blocks = paras
    for b in blocks: b["clean"] = clean(b["text"])
    return [b for b in blocks if len(b["clean"]) >= 6]      # header-only / score-only blocks carry no answer

class Embedder:
    def __init__(self):
        from sentence_transformers import SentenceTransformer
        self.m = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
        self.cache = {}
        if CACHE.exists():
            z = np.load(CACHE, allow_pickle=True); self.cache = dict(zip(z["keys"], z["vecs"]))
    def key(self, t): return hashlib.md5(t.encode("utf-8")).hexdigest()
    def encode(self, texts):
        todo = [t for t in dict.fromkeys(texts) if self.key(t) not in self.cache]
        if todo:
            vecs = self.m.encode([t[:1500] for t in todo], normalize_embeddings=True, batch_size=64, show_progress_bar=False)
            for t, v in zip(todo, vecs): self.cache[self.key(t)] = v
        return np.stack([self.cache[self.key(t)] for t in texts])
    def save(self):
        np.savez(CACHE, keys=np.array(list(self.cache)), vecs=np.stack(list(self.cache.values())))

def align_unit(questions, blocks, E):
    """Monotonic DP: maximise sum of scores, each question matched to a later block than the previous one
    or left unmatched (score 0). Returns list of (block_idx|None, evidence)."""
    if not questions or not blocks: return [(None, None)] * len(questions)
    qc = [clean(q["text"]) or q["text"] for q in questions]
    qv = E.encode(qc); bv = E.encode([b["clean"] for b in blocks])
    emb = qv @ bv.T
    n, m = len(questions), len(blocks)
    S = np.zeros((n, m)); EV = {}
    for i, q in enumerate(questions):
        for j, b in enumerate(blocks):
            lex = lexical(qc[i], b["clean"]); lab = label_agree(q["label"], b["label"])
            s = W_EMB * max(emb[i, j], 0) + W_LEX * lex + W_LAB * lab
            # below threshold = "no match"; a match that contradicts the numbering needs stronger evidence
            ok = s >= T_GOOD and emb[i, j] >= MIN_EMB and (lab > 0 or (s >= T_CONTRA and lex >= 0.25))
            # exact numbering + monotonic position + weak-but-positive semantics (drawings, tables, one-word answers)
            ok = ok or (lab == 1.0 and s >= T_LABEL and emb[i, j] >= MIN_EMB_LABEL)
            S[i, j] = s if ok else 0.0
            EV[(i, j)] = {"emb": round(float(emb[i, j]), 3), "lex": round(lex, 3), "label_agree": lab, "score": round(float(s), 3)}
    # dp[i][j]: best total for questions[:i] using blocks with index <= j (non-decreasing: a key block that
    # holds two consecutive answers — e.g. a table for Q2 glued under Q1 — may serve both questions)
    dp = np.zeros((n + 1, m + 1)); choice = {}
    for i in range(1, n + 1):
        for j in range(0, m + 1):
            best, arg = dp[i - 1][j], None                       # question i-1 unmatched
            for k in range(j):                                   # matched to block k, previous ones <= k
                v = dp[i - 1][k + 1] + S[i - 1, k] - REUSE_PENALTY * (choice.get((i - 1, k + 1)) == k)
                if S[i - 1, k] > 0 and v > best: best, arg = v, k
            dp[i][j] = best; choice[(i, j)] = arg
    out, j = [None] * n, m
    for i in range(n, 0, -1):
        k = choice[(i, j)]
        if k is not None: out[i - 1] = k; j = k + 1
    return [(k, EV[(i, k)] if k is not None else None) for i, k in enumerate(out)]

def classify(ev):
    if ev is None: return "none"
    if ev["score"] >= T_STRONG: return "strong"
    if ev["score"] >= T_GOOD: return "good"
    return "label_supported"   # numbering agrees, semantics weak but positive

def main(subjects):
    E = Embedder(); random.seed(7)
    summary = json.loads((OUT/"dataset_summary.json").read_text("utf-8"))
    review = []
    for subj in subjects:
        stats = Counter(); n_units = 0; recs = []
        for l in open(OUT/f"{subj}_pairs.jsonl", encoding="utf-8"):
            p = json.loads(l); e, s = p["exam"], p["solution"]
            if p.get("solution_match") == "none_expected": continue
            n_units += 1
            if not e["items"]: stats["units_without_numbered_questions"] += 1; continue
            blocks = blocks_of(s) if s else []
            res = align_unit(e["items"], blocks, E)
            unit_label = e.get("exercise_label") or e.get("section_label")
            labels = [it["label"] for it in e["items"]]
            for it, (k, ev) in zip(e["items"], res):
                cls = classify(ev); stats["questions"] += 1
                # a parent stub ("2. اعتمادا على الشكل:") whose answers live in its children 2.1, 2.2 …
                if cls == "none" and any(l.startswith(it["label"] + ".") for l in labels if l != it["label"]):
                    cls = "parent_stub"
                stats[cls] += 1
                if ev and ev["label_agree"] == 0: stats["matched_despite_label_mismatch"] += 1
                if ev and ev["label_agree"] == 1: stats["matched_with_label_agreement"] += 1
                rec = {"qid": f"{e['id']}__q{it['label']}", "subject": subj, "year": e["year"], "session": e["session"],
                       "sujet": e["sujet"], "unit_id": e["id"], "unit_label": unit_label, "points": e["points"],
                       "label": it["label"], "question": it["text"], "answer": blocks[k]["text"] if k is not None else None,
                       "answer_label": blocks[k]["label"] if k is not None else None,
                       "match": cls, "evidence": ev, "solution_match": p["solution_match"]}
                recs.append(rec)
        with open(OUT/f"{subj}_questions.jsonl", "w", encoding="utf-8") as fo:
            for r in recs: fo.write(json.dumps(r, ensure_ascii=False) + "\n")
        for cls in ("strong", "good", "label_supported", "none"):
            pool = [r for r in recs if r["match"] == cls]
            review += random.sample(pool, min(3, len(pool)))
        answered = stats["strong"] + stats["good"] + stats["label_supported"]; answerable = stats["questions"] - stats["parent_stub"]
        st = {"units": n_units, **stats, "answered": answered, "answered_pct": round(100 * answered / max(answerable, 1), 1)}
        summary[subj]["question_alignment"] = st
        print(subj, json.dumps(st, ensure_ascii=False))
        E.save()
    with open(OUT/"alignment_review_sample.jsonl", "w", encoding="utf-8") as fo:
        for r in review: fo.write(json.dumps(r, ensure_ascii=False) + "\n")
    (OUT/"dataset_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), "utf-8")

if __name__ == "__main__":
    main(sys.argv[1:] or SUBJECTS)
