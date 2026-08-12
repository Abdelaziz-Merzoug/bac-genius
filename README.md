# bac-genius

**Official project title:** *A Hybrid NLP, Time-Series Forecasting and Generative AI
Framework for Algerian Baccalaureate Exam Preparation (Experimental Sciences Stream)*

**Supervisors:** Dr. N. Lahiani, Dr. M. Mezzi — Université Saad Dahlab Blida 1

## Scope

This is the master-thesis reference implementation of the project's proposal. It
targets a single Baccalaureate stream — `experimental_sciences` — across three
subjects: SVT (coeff. 6), Physics (coeff. 5) and Math (coeff. 5). See
[`config/streams.py`](config/streams.py) for the authoritative scope declaration and
curriculum validation reference, and [`config/settings.py`](config/settings.py) for
runtime configuration.

## Architecture

```
config/        Runtime settings & curriculum/scope reference
data/          raw | processed | kg | series | features | forecast | generated
scraper/       Source acquisition
ingestion/     Cleaning, normalization, loading into storage layers
nlp/           Topic modeling (BERTopic), NLP pipelines
forecasting/   Time-series models (Prophet, Darts, statsmodels)
llm/           LLM provider abstraction (OpenAI / Gemini / Ollama)
rag/           Retrieval-augmented generation over the knowledge graph & corpus
genmedia/      Generative media (diagrams, figures, documents)
validation/    Curriculum & factual validation
xai/           Explainability tooling
eval/          Automated + human evaluation (see eval/human_eval)
api/           FastAPI application (see api/routers)
frontend/      Streamlit UI
scripts/       Operational / one-off scripts
```

## Getting started

```bash
python -m venv .venv
.venv\Scripts\activate      # Windows
pip install -r requirements.txt
copy .env.example .env      # then fill in credentials
```

## Requirements

- Python 3.10
- See `requirements.txt` for pinned dependencies.
