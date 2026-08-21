# Open Telco (OTel) AI on Databricks

> A build-in-public, chapter-by-chapter guide to recreating the **Open Telco (OTel) AI**
> RAG stack as governed, observable, native **Databricks** primitives — and wiring it into
> an autonomous RAN / OSS-BSS troubleshooting agent.

**OTel here means _Open Telco_, not OpenTelemetry.** It's a family of telecom-domain
fine-tuned models (embedding · reranker · LLM · safety) trained on 3GPP, GSMA, O-RAN
standards, RFCs, and academic papers, published on HuggingFace under
[`farbodtavakkoli`](https://huggingface.co/farbodtavakkoli).

---

## The vision, in one picture

```
   incident  ─►  ReAct agent  ─►  embed ─► vector search ─► rerank ─► grounded LLM ─► safety gate ─► recommendation
   (app/app.py)     (Think→Act→        └──────────────── Open Telco (OTel) models ───────────────┘         (human-approved)
                  Observe→Reflect)          served + governed + captured on Databricks
```

The [`app/app.py`](./app/app.py) demo is the **north star** for the *experience*: a generic
ReAct + reflection loop that calls OSS/BSS/KPI tools, grounds a diagnosis in telecom
standards, and recommends a human-gated fix — every LLM and tool call captured as
OpenTelemetry-style spans. Today its reasoning brain is a mock (or Claude), and its
`retrieve_standards` tool is a keyword match. **This repo replaces those stand-ins, one
chapter at a time, with the real Open Telco models running on Databricks.**

The [`otel-databricks-demo-plan.md`](./otel-databricks-demo-plan.md) is the **engineering
plan** for the *platform*: log each OTel model to Unity Catalog, serve it, and capture
every inference.

---

## Chapters

A ladder you climb on your **laptop** first (Chapters 0–2, CPU-only, no account needed),
then **productionize on Databricks** (Chapters 3–4).

| # | Chapter | Runs on | Status | What you get |
|---|---------|---------|--------|--------------|
| **0** | [**Vision**](./chapters/00-vision/) | laptop | ✅ done | The north star + your first real OTel model running (CPU) |
| **1** | [**The OTel RAG pipeline**](./chapters/01-rag-pipeline/) | laptop | ✅ done | Full grounding pipeline: embed → retrieve → rerank → ground → **abstain** |
| **2** | [**The self-healing agent loop**](./chapters/02-agent-loop/) | laptop | ✅ done | Wire the pipeline into the [`app/app.py`](./app/app.py) ReAct loop — OTel replaces the keyword grounding |
| **3** | [**Productionize on Databricks**](./chapters/03-productionize/) | Databricks | ✅ done | Log → UC registration → Model Serving → Vector Search |
| **4** | [**Govern & capture**](./chapters/04-govern-capture/) | Databricks | ✅ done | **Inference tables** + monitoring + cost-economics ledger |

Each chapter is self-contained and builds on the last. Chapters 0–1 are runnable today.

---

## Quick start (Chapter 0 — Step 0)

Run your first Open Telco model on your laptop, CPU-only:

```bash
pip install -r requirements.txt
jupyter lab notebooks/00_starter_load_and_inference.ipynb
```

The notebook loads [`OTel-Embedding-335M`](https://huggingface.co/farbodtavakkoli/OTel-Embedding-335M)
(a ~335M-param BGE-based sentence embedder — small enough for CPU) and uses it to do real
semantic retrieval over a tiny telecom-standards corpus. That corpus is the same knowledge
the `app/app.py` agent cites — so Step 0 is literally the first real piece of the north-star loop.

Then [Chapter 1](./chapters/01-rag-pipeline/) assembles the full grounding pipeline
(`notebooks/01_otel_rag_pipeline.ipynb`) — adding the OTel reranker, a safety/abstain gate, and
the production lessons (vector normalization, reranker validation) that make it trustworthy.

See [`chapters/00-vision/README.md`](./chapters/00-vision/README.md) for the full narrative.
