# Open Telco (OTel) on Databricks

```
A chapter-by-chapter, runnable guide to exploring the Open Telco (OTel) family of
telecom-domain models and building them into a governed, observable "self-healing
network" assistant on Databricks.

Climb the ladder on your laptop first (Chapters 0-2, CPU-only, no account needed),
then productionize on Databricks (Chapters 3-4): Unity Catalog, Model Serving,
Vector Search, and full inference capture.
```

> **OTel here means _Open Telco_, not OpenTelemetry.** It is a family of telecom-domain
> fine-tuned models (embedding · reranker · LLM) trained on 3GPP, GSMA, and O-RAN standards,
> published on HuggingFace under [`farbodtavakkoli`](https://huggingface.co/farbodtavakkoli).

## What this is

A self-contained learning path that answers one question for a telecom customer: **how do the
Open Telco models become part of an autonomous, self-healing network on Databricks?** Each
chapter is a runnable notebook plus a short narrative guide.

| # | Chapter | Runs on | What you get |
|---|---------|---------|--------------|
| 0 | [Vision + Step 0](chapters/00-vision/) | laptop (CPU) | Load & inference your first OTel model — "it's real" |
| 1 | [The OTel RAG pipeline](chapters/01-rag-pipeline/) | laptop (CPU) | embed → retrieve → rerank → ground → **abstain**, with production lessons baked in |
| 2 | [The self-healing agent loop](chapters/02-agent-loop/) | laptop (CPU) | A ReAct agent grounded in OTel retrieval, ending in a **human-gated** recommendation |
| 3 | [Productionize on Databricks](chapters/03-productionize/) | Databricks | Log → Unity Catalog → Model Serving → Vector Search |
| 4 | [Govern & capture](chapters/04-govern-capture/) | Databricks | **Inference tables** + monitoring + cost-economics ledger |

The north-star experience is [`otel.py`](otel.py) — a self-contained ReAct + reflection agent
that troubleshoots a RAN/OSS-BSS incident, grounds its diagnosis in standards, and recommends
a human-gated fix with OpenTelemetry-style traces. The chapters progressively replace its
stand-ins (a keyword retriever, a mock brain) with the real Open Telco models on Databricks.

## Video Overview

_Coming soon._

## Installation

**Chapters 0-2 (laptop, CPU — no Databricks account required):**

```bash
pip install -r requirements.txt
jupyter lab notebooks/00_starter_load_and_inference.ipynb
```

First run downloads the model weights (embedding ~335M, reranker ~0.6B) from HuggingFace and
caches them. CPU is fine for the small demo corpus.

**Chapters 3-4 (Databricks):** import the notebooks into a Databricks workspace and run them
on serverless or a cluster. They require Unity Catalog write access, Model Serving entitlement,
and a Vector Search endpoint. On serverless / standard clusters, run the first `%pip install`
cell (it restarts Python); the ML runtime already ships `torch`/`transformers`. These chapters
create billable resources (a serving endpoint, a Vector Search index) — each notebook includes
a cleanup cell.

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
