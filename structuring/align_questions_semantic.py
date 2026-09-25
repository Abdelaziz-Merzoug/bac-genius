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
import json, re, sys, random, hashlib, os
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
        if not t or PAGE_NOISE_RX.match(t) or re.fullmatch(r"[\d.,\s×x+()]+", t): continue
        # HEAD_RX.match() only needs to match a PREFIX: a heading glued to the first answer on the same
        # source line ("الجزء الأول: 1) lim h(x)=... 0,5") would otherwise match on the heading alone and
        # drop the whole line — including the real answer — leaving the block's clean text empty and the
        # block silently filtered out of blocks_of() entirely (found via bac_math_2009_sujet2__ex4__q1).
        hm = HEAD_RX.match(norm_head(t))
        if hm and len(t) - hm.end() <= 15: continue
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

def canonicalize(items):
    """Hierarchical labels are RTL-flipped in many 2018+ files (2.1, 2.2, 2.3 read as 1.2, 2.2, 3.2).
    Decide per unit: if consecutive multi-part labels change mostly in their FIRST component, the
    orientation is flipped -> reverse every multi-part label. Returns a new list of dicts."""
    multi = [it["label"] for it in items if it["label"] and "." in it["label"]]
    first, last = 0, 0
    for a, b in zip(multi, multi[1:]):
        pa, pb = a.split("."), b.split(".")
        if len(pa) == len(pb):
            first += pa[0] != pb[0]; last += pa[-1] != pb[-1]
    flip = first > last
    out = []
    for it in items:
        lab = ".".join(reversed(it["label"].split("."))) if flip and it["label"] and "." in it["label"] else it["label"]
        out.append({**it, "label": lab, "label_raw": it["label"]})
    return out

QWORD_RX = re.compile(
    r"\?|؟|\b(?:ما|ماذا|لماذا|كيف|هل|أي|أين|متى|بم|بماذا|فيم|علام|اذكر|أذكر|حدد|حدّد|حلل|حلّل|فسر|فسّر|بين|بيّن|استنتج|قارن|اكتب|أكتب|أعط|اعط"
    r"|أنجز|انجز|مثل|مثّل|ارسم|أرسم|وضح|وضّح|اشرح|قدم|قدّم|سم|سمّ|تعرف|تعرّف|عين|عيّن|احسب|أحسب|برهن|أثبت|اثبت|تحقق|ادرس|استخرج|لخص|لخّص|اقترح|صنف|صنّف"
    r"|علل|علّل|ناقش|أكمل|اكمل|ضع|انقل|أنقل|عرف|عرّف|قارن|جد|حل|حلّ|رتب|أعد|اعد|ماهي|ما هي|ما هو|قيم|قيّم|اختر|أجب"
    r"|calcule[zr]?|détermine[zr]?|montre[zr]?|expliqu|justifi|relev|donne[zr]?|cite[zr]?|complét|réponde|identifi|répond|proposez|rédige"
    r"|write|answer|give|choose|find|say|classify|reorder|complete|fill|ask|match|divide|rewrite|circle|identify|what|which|who|why|how)\b", re.I)
def is_question(text):
    t = TASHKEEL_RX.sub("", clean(text))
    return len(t) >= 60 or bool(QWORD_RX.search(t)) or bool(re.search(r"(?:^|[\s.])(?:[ab]\)|أ\)|ب\)|أ-|ب-)", t))

def legend_runs(items):
    """Indices of items that are document legends (numbered labels of a figure/table) rather than
    questions: a numbering run in which most items are not question-like AND which is followed by
    another run (real questions restart the numbering after the document)."""
    runs, cur = [], []
    for i, it in enumerate(items):
        n = int(it["label"].split(".")[0])
        if cur and n <= int(items[cur[-1]]["label"].split(".")[0]) and "." not in it["label"]: runs.append(cur); cur = []
        cur.append(i)
    if cur: runs.append(cur)
    out = set()
    for r in runs[:-1]:
        if any("." in items[i]["label"] for i in r): continue        # hierarchical numbering = real questions
        if sum(not is_question(items[i]["text"]) for i in r) >= 0.6 * len(r): out |= set(r)
    return out

def is_parent(i, labels):
    """A parent stub is immediately followed by its own children (1. … then 1.1, 1.2 …)."""
    return i + 1 < len(labels) and labels[i + 1].startswith(labels[i] + ".")

MARK_RX_CACHE = {}
def block_mentions(label, text):
    """Does the block carry a marker for this label somewhere inside (e.g. '5. -' glued under 4.)?"""
    rx = MARK_RX_CACHE.get(label)
    if rx is None:
        alts = "|".join(re.escape(v) for v in variants(label))
        # only a marker that opens a line/cell counts ("الوثيقة (1)" inside a sentence does not)
        rx = MARK_RX_CACHE[label] = re.compile(r"(?:^|\n|\|)\s*\**\(?\s*(?:" + alts + r")\s*[\.\)\-–/:]")
    body = text.split("\n", 1)[1] if "\n" in text else ""      # skip the block's own opening marker
    return bool(rx.search(body))

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
    """Answer blocks with (label|None, text). Cut at every numbered marker; fall back to paragraphs.
    NOTE: a container-aware version of this (only opening a new block when the label plausibly continues
    or genuinely restarts the top-level sequence) was tried and reverted — it fixed real cases of a
    numbered sub-list inside one answer being mistaken for new top-level questions, but the restart/part
    markers that legitimately DO start a new top-level sequence ("ثانيا:", "الجزء الثاني", "(II", label+
    embedded-roman-numeral, ...) turned out to have too many different shapes across the corpus to detect
    reliably; the resulting false negatives (content silently dropping to "none") outnumbered the fixes by
    roughly 6:1 in a full-corpus regression check. Recorded here so the attempt isn't silently re-tried:
    the sub-enumeration fragmentation bug is instead handled case-by-case via human overrides (see
    structuring/check_missing.py and alignment_overrides.json)."""
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
    qlabels = [q["label"] for q in questions]
    qlabel_variants = set().union(*(variants(l) for l in qlabels))
    qc = [clean(q["text"]) or q["text"] for q in questions]
    qv = E.encode(qc); bv = E.encode([b["clean"] for b in blocks])
    emb = qv @ bv.T
    n, m = len(questions), len(blocks)
    S = np.zeros((n, m)); EV = {}; REUSABLE = np.zeros((n, m), dtype=bool)
    LEX = np.array([[lexical(qc[i], b["clean"]) for b in blocks] for i in range(n)])
    LAB = np.array([[label_agree(q["label"], b["label"]) for b in blocks] for q in questions])
    SEM = W_EMB * np.maximum(emb, 0) + W_LEX * LEX          # meaning only (no numbering)
    # MEANING FIRST. Numbering is trusted for a question only when its label-agreeing block is also among
    # the top-2 blocks by meaning; otherwise the key is mis-numbered here and the label weight is discounted.
    # a block is "owned" by the question whose label it carries only if the meaning supports that pairing
    owner_sem = {}
    for j, b in enumerate(blocks):
        if not b["label"]: continue
        for i in range(n):
            if LAB[i, j] == 1.0 and SEM[i, j] >= 0.20: owner_sem[j] = max(owner_sem.get(j, 0), SEM[i, j])
    trust = np.ones(n)
    for i in range(n):
        agree = [j for j in range(m) if LAB[i, j] == 1.0]
        if not agree: continue
        best_lab = max(SEM[i, j] for j in agree)
        # a clearly better block by meaning that nobody else owns => the numbering is unreliable for this question
        rivals = [SEM[i, j] for j in range(m) if LAB[i, j] < 1.0 and not (j in owner_sem and owner_sem[j] >= SEM[i, j])]
        if rivals and max(rivals) - best_lab >= 0.15 and max(rivals) >= 0.40: trust[i] = 0.3
    for i, q in enumerate(questions):
        for j, b in enumerate(blocks):
            lex, lab = LEX[i, j], LAB[i, j]
            s = SEM[i, j] + W_LAB * lab * trust[i]
            # below threshold = "no match"; a match that contradicts the numbering needs stronger evidence,
            # and may not take a block that meaning-and-number both assign to another question
            contra_ok = s >= T_CONTRA and lex >= 0.25 and not (j in owner_sem and owner_sem[j] + 0.15 >= SEM[i, j])
            ok = s >= T_GOOD and emb[i, j] >= MIN_EMB and (lab > 0 or contra_ok)
            # exact numbering + monotonic position + weak-but-positive semantics (drawings, tables, one-word answers)
            # exact numbering + weak-but-positive semantics (drawings, tables, one-word answers); when the
            # numbering is distrusted the pair keeps a low score and the unit-level optimum decides
            ok = ok or (lab == 1.0 and s >= T_LABEL * (1 if trust[i] == 1.0 else 0.8) and emb[i, j] >= MIN_EMB_LABEL)
            # symbolic answers ("2. a) T b) F c) T", "4. In § 3", "1. c") carry no measurable meaning: exact numbering
            # + monotonic position (the DP) is the only evidence, and it is accepted for short blocks
            ok = ok or (lab == 1.0 and len(b["clean"].split()) <= 12)
            S[i, j] = s if ok else 0.0
            REUSABLE[i, j] = block_mentions(q["label"], b["text"])   # the block visibly holds this question's answer too
            EV[(i, j)] = {"emb": round(float(emb[i, j]), 3), "lex": round(float(lex), 3), "label_agree": float(lab),
                          "label_trust": float(trust[i]), "score": round(float(s), 3)}
    # dp[i][j]: best total for questions[:i] using blocks with index <= j. A block may serve two consecutive
    # questions only when it visibly carries the second question's marker (answer glued under the previous one).
    dp = np.zeros((n + 1, m + 1)); choice = {}
    for i in range(1, n + 1):
        for j in range(0, m + 1):
            best, arg = dp[i - 1][j], None                       # question i-1 unmatched
            for k in range(j):                                   # matched to block k, previous ones <= k
                reused = choice.get((i - 1, k + 1)) == k
                if reused and not REUSABLE[i - 1, k]: continue
                v = dp[i - 1][k + 1] + S[i - 1, k] - REUSE_PENALTY * reused
                if S[i - 1, k] > 0 and v > best: best, arg = v, k
            dp[i][j] = best; choice[(i, j)] = arg
    out, j = [None] * n, m
    for i in range(n, 0, -1):
        k = choice[(i, j)]
        if k is not None: out[i - 1] = k; j = k + 1
    # exact reuse guard: a block already taken by an earlier question stays with it unless it visibly
    # carries the later question's marker too
    taken = {}
    for i, k in enumerate(out):
        if k is None: continue
        if k in taken and not REUSABLE[i, k]: out[i] = None
        else: taken.setdefault(k, i)
    return [(k, EV[(i, k)] if k is not None else None) for i, k in enumerate(out)]

def classify(ev):
    if ev is None: return "none"
    if ev["score"] >= T_STRONG: return "strong"
    if ev["score"] >= T_GOOD: return "good"
    return "label_supported"   # numbering agrees, semantics weak but positive

def main(subjects):
    E = Embedder(); random.seed(7)
    ov_path = OUT/"alignment_overrides.json"
    # NO_OVERRIDES=1 -> pure automatic alignment written to {subj}_questions_auto.jsonl (baseline for the audit log)
    auto_only = os.environ.get("NO_OVERRIDES") == "1"
    overrides = {} if auto_only else (json.loads(ov_path.read_text("utf-8")) if ov_path.exists() else {})
    suffix = "_questions_auto.jsonl" if auto_only else "_questions.jsonl"
    # solutions of every unit, for overrides that point at ANOTHER unit's answer key ("from_unit"):
    # e.g. French keys often hold subject 2's comprehension answers inside subject 1's file
    all_solutions = {}
    for sj in SUBJECTS:
        for l in open(OUT/f"{sj}_pairs.jsonl", encoding="utf-8"):
            pp = json.loads(l)
            if pp["solution"]: all_solutions[pp["exam"]["id"]] = pp["solution"]
    blocks_cache = {}
    def blocks_for(unit_id):
        if unit_id not in blocks_cache: blocks_cache[unit_id] = canonicalize(blocks_of(all_solutions[unit_id]))
        return blocks_cache[unit_id]
    summary = json.loads((OUT/"dataset_summary.json").read_text("utf-8"))
    review = []
    for subj in subjects:
        stats = Counter(); n_units = 0; recs = []
        for l in open(OUT/f"{subj}_pairs.jsonl", encoding="utf-8"):
            p = json.loads(l); e, s = p["exam"], p["solution"]
            if p.get("solution_match") in ("none_expected", "solution_is_exam_copy"): continue
            n_units += 1
            if not e["items"]: stats["units_without_numbered_questions"] += 1; continue
            blocks = canonicalize(blocks_of(s)) if s else []
            items = canonicalize(e["items"])
            labels = [it["label"] for it in items]
            # a parent stub ("2. اعتمادا على الشكل:") is context: its answers live in its children 2.1, 2.2 …
            parents = {i for i in range(len(items)) if is_parent(i, labels)}
            legends = legend_runs(items) - parents
            skip = parents | legends
            res = align_unit([it for i, it in enumerate(items) if i not in skip], blocks, E)
            res_iter = iter(res)
            unit_label = e.get("exercise_label") or e.get("section_label")
            seen_labels = Counter()
            for i, it in enumerate(items):
                k, ev = (None, None) if i in skip else next(res_iter)
                cls = "parent_stub" if i in parents else ("legend" if i in legends else classify(ev)); stats["questions"] += 1
                seen_labels[it["label"]] += 1
                qid = f"{e['id']}__q{it['label']}" + (f"#{seen_labels[it['label']]}" if seen_labels[it["label"]] > 1 else "")
                human_answer = None
                if qid in overrides:                       # human correction wins over everything
                    ob = overrides[qid]["block"]; src = overrides[qid].get("from_unit")
                    src_blocks = blocks_for(src) if src else blocks
                    idxs = [i for i in (ob if isinstance(ob, list) else [ob]) if i is not None and i < len(src_blocks)]
                    k = idxs[0] if (idxs and not src) else None
                    human_answer = "\n".join(src_blocks[i]["text"] for i in idxs) if idxs else None
                    cls = "human" if idxs else "solution_missing"   # human-verified: official key has no answer
                    ev = {"human_note": overrides[qid]["note"], "blocks": idxs, "from_unit": src}
                stats[cls] += 1
                if ev and ev.get("label_agree") == 0: stats["matched_despite_label_mismatch"] += 1
                if ev and ev.get("label_agree") == 1: stats["matched_with_label_agreement"] += 1
                rec = {"qid": qid, "subject": subj, "year": e["year"], "session": e["session"],
                       "sujet": e["sujet"], "unit_id": e["id"], "unit_label": unit_label, "points": e["points"],
                       "label": it["label"], "label_raw": it["label_raw"], "question": it["text"],
                       "answer": human_answer if human_answer is not None else (blocks[k]["text"] if k is not None else None),
                       "answer_label": blocks[k]["label"] if k is not None else ("x" if human_answer else None),
                       "match": cls, "evidence": ev, "solution_match": p["solution_match"]}
                recs.append(rec)
        with open(OUT/f"{subj}{suffix}", "w", encoding="utf-8") as fo:
            for r in recs: fo.write(json.dumps(r, ensure_ascii=False) + "\n")
        for cls in ("strong", "good", "label_supported", "none"):
            pool = [r for r in recs if r["match"] == cls]
            review += random.sample(pool, min(3, len(pool)))
        answered = stats["strong"] + stats["good"] + stats["label_supported"] + stats["human"]
        answerable = stats["questions"] - stats["parent_stub"] - stats["legend"] - stats["solution_missing"]
        st = {"units": n_units, **stats, "answered": answered, "answered_pct": round(100 * answered / max(answerable, 1), 1)}
        summary[subj]["question_alignment"] = st
        print(subj, json.dumps(st, ensure_ascii=False))
        E.save()
    with open(OUT/"alignment_review_sample.jsonl", "w", encoding="utf-8") as fo:
        for r in review: fo.write(json.dumps(r, ensure_ascii=False) + "\n")
    (OUT/"dataset_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), "utf-8")

if __name__ == "__main__":
    main(sys.argv[1:] or SUBJECTS)
