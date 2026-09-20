# bac-genius

**Official project title:** *A Hybrid NLP, Time-Series Forecasting and Generative AI
Framework for Algerian Baccalaureate Exam Preparation (Experimental Sciences Stream)*

**Author:** Abdelaziz Merzoug — abdelaziz_merzoug@etu.univ-blida.dz
**Supervisors:** Dr. N. Lahiani, Dr. M. Mezzi — Université Saad Dahlab Blida 1

## Scope

Single stream: **Experimental Sciences** (شعبة علوم تجريبية) · Years **2008–2026** · 2026 sealed.

| Subject | Code | Coeff | Hours | Pipeline |
|---------|------|-------|-------|----------|
| Sciences de la Vie et de la Terre | `svt` | 6 | 4.5 | full |
| Sciences Physiques | `physic` | 5 | 3.5 | full |
| Mathématiques | `math` | 5 | 3.5 | full |
| Langue et Littérature Arabes | `arabe` | 3 | 2.5 | rag_only |
| Sciences Islamiques | `islamic` | 2 | 2.5 | rag_only |
| Langue Française | `francais` | 2 | 2.5 | rag_only |
| Langue Anglaise | `english` | 2 | 2.5 | rag_only |

**Full pipeline** (SVT, Physics, Math): topic modelling → forecasting → grounded generation → XAI → evaluation.
**RAG only** (language subjects): ingested for retrieval Q&A; no forecasting or generation.

## Four-era regime model

| Era | Years | Completion | Censored |
|-----|-------|-----------|----------|
| `early_reform` | 2008–2014 | 65–93 % | ✅ (عتبة الدروس) |
| `stable` | 2015–2019 | 95–100 % | — |
| `covid` | 2020–2022 | 65–80 % | ✅ (pandemic) |
| `modern` | 2023–2026 | 100 % | — (2026 sealed) |

2016 and 2017 each have two exam sittings (`session1` / `session2`).
See [`config/threshold_cuts.py`](config/threshold_cuts.py) for full year-by-year metadata.

## Architecture

```
config/        Runtime settings, scope declaration, historical year metadata
data/          raw | processed | kg | series | features | forecast | generated
ingestion/     Manifest builder, OCR+cleaning, segmentation, Qdrant ingest
nlp/           Topic modelling (BERTopic), NER, difficulty/style pipelines
forecasting/   Time-series models (Prophet, Darts, statsmodels)
llm/           LLM provider abstraction (OpenAI / Gemini / Ollama)
rag/           Retrieval-augmented generation over KG + corpus
genmedia/      Generative media (diagrams, figures, documents)
validation/    Curriculum & factual validation
xai/           Explainability tooling
eval/          Automated + human evaluation
api/           FastAPI backend
frontend/      Streamlit UI
scripts/       Operational / one-off scripts
```

## Getting started

```bash
python -m venv .venv
.venv\Scripts\activate      # Windows
pip install -r requirements.txt
copy .env.example .env      # fill in credentials
```

## Requirements

- Python 3.10
- See [`requirements.txt`](requirements.txt) for pinned dependencies.
- See [`config/settings.py`](config/settings.py) for runtime configuration.
- See [`config/streams.py`](config/streams.py) for scope and syllabus maps.
