# Open Telco (OTel) on Databricks

```
A chapter-by-chapter, runnable guide to exploring the Open Telco (OTel) telecom-domain
models and building them into a governed, observable "self-healing network" assistant on
Databricks — from a laptop (CPU, no account) all the way to a live, governed deployment.
```

> **OTel here means _Open Telco_,** It is a family of telecom-domain
> fine-tuned models (embedding · reranker · LLM · safety) trained on 3GPP, GSMA, and O-RAN
> standards, published on
> [`HuggingFace`](https://huggingface.co/farbodtavakkoli).

## The vision, in one picture

```
   incident  ->  ReAct agent   ->  embed -> vector search -> rerank -> grounded LLM -> safety gate -> recommendation
   (app/app.py)  (Think->Act->        \_______________ Open Telco (OTel) models ______________/        (human-approved)
                  Observe->Reflect)         served + governed + captured on Databricks
```

[`app/app.py`](./app/app.py) is the **north star**: a ReAct + reflection agent that troubleshoots
a RAN/OSS-BSS incident, grounds its diagnosis in telecom standards, and recommends a
human-gated fix — every LLM and tool call captured as OpenTelemetry-style spans. It starts with
two stand-ins (a keyword retriever, a mock brain); the chapters progressively replace them with
the real Open Telco models on Databricks.

## Chapters

Each chapter is a **self-contained notebook** (its narrative is in the notebook itself). Climb
the ladder on your **laptop** first (Chapters 0–2, CPU-only, no account), then **productionize on
Databricks** (Chapters 3–4).

| # | Chapter (notebook) | Runs on | What you get |
|---|--------------------|---------|--------------|
| 0 | [Vision + Step 0](./notebooks/00_starter_load_and_inference.ipynb) | laptop (CPU) | Load & inference your first OTel model — "it's real" |
| 1 | [The OTel RAG pipeline](./notebooks/01_otel_rag_pipeline.ipynb) | laptop (CPU) | embed → retrieve → rerank → ground → **abstain**, with production lessons baked in |
| 2 | [The self-healing agent loop](./notebooks/02_self_healing_agent_loop.ipynb) | laptop (CPU) | A ReAct agent grounded in OTel retrieval, ending in a **human-gated** recommendation |
| 3 | [Productionize on Databricks](./notebooks/03_productionize_on_databricks.ipynb) | Databricks | Log → Unity Catalog → Model Serving → Vector Search |
| 4 | [Govern & capture](./notebooks/04_govern_and_capture.ipynb) | Databricks | **Inference tables** + monitoring + cost-economics ledger |

## Make it real (end to end)

[`deploy/`](./deploy/) codifies the **entire live stack** — governed Unity Catalog data, a served
OTel embedding model + Vector Search index, a served OTel LLM, inference-table capture, service-
principal grants, and the animated app — reproducible with one command:

```bash
./deploy/deploy.sh <your-databricks-cli-profile>
```

See [`deploy/README.md`](./deploy/README.md) for the details.

## Video Overview

![OTel self-healing demo — the live ReAct loop grounding, reasoning, and recommending](docs/Overview.gif)

_A short capture of the app: pick a scenario and watch the ReAct loop (Think -> Act -> Observe -> Reflect) call the OTel tools, ground in Vector Search, reason with the served OTel LLM, and end in a human-gated recommendation._

## Installation

**Chapters 0–2 (laptop, CPU — no Databricks account required):**

```bash
pip install -r requirements.txt
jupyter lab notebooks/00_starter_load_and_inference.ipynb
```

First run downloads the model weights (embedding ~335M, reranker ~0.6B) from HuggingFace and
caches them. CPU is fine for the small demo corpus.

**Chapters 3–4 (Databricks):** import the notebooks and run on serverless or a cluster (UC write
access, Model Serving entitlement, and a Vector Search endpoint required). On serverless /
standard clusters run the first `%pip install` cell (it restarts Python); the ML runtime already
ships `torch`/`transformers`. These chapters create billable resources — each notebook has a
cleanup cell.

**Full live deployment:** `./deploy/deploy.sh <profile>` (see above).

## How to get help

Databricks support doesn't cover this content. For questions or bugs, please open a GitHub
issue and the team will help on a best effort basis.

## License

&copy; 2025 Databricks, Inc. All rights reserved. The source in this notebook is provided
subject to the Databricks License [https://databricks.com/db-license-source]. All included or
referenced third party libraries are subject to the licenses set forth below.

| library | description | license | source |
|---------|-------------|---------|--------|
| sentence-transformers | Sentence & text embeddings | Apache-2.0 | https://github.com/UKPLab/sentence-transformers |
| transformers | Model loading / inference | Apache-2.0 | https://github.com/huggingface/transformers |
| torch | Tensor / DL runtime | BSD-3-Clause | https://github.com/pytorch/pytorch |
| numpy | Numerical arrays | BSD-3-Clause | https://github.com/numpy/numpy |
| mlflow | Model logging & registry | Apache-2.0 | https://github.com/mlflow/mlflow |
| databricks-sdk | Databricks SDK for Python | Apache-2.0 | https://github.com/databricks/databricks-sdk-py |
| databricks-vectorsearch | Vector Search client | Apache-2.0 | https://pypi.org/project/databricks-vectorsearch/ |
| Open Telco (OTel) models | Telecom-domain fine-tunes | inherit base-checkpoint terms (datasets Apache-2.0) | https://huggingface.co/farbodtavakkoli |
