# Chapter 1 — The OTel RAG pipeline

_How Open Telco models become the **retrieval brain** of a self-healing network — the
full grounding pipeline, running on your laptop._

---

## Where this sits

In [Chapter 0](../00-vision/) you loaded one OTel model and proved it does real telecom
semantic search. That was one component. **This chapter assembles the whole pipeline** —
the actual pattern a production Databricks self-healing NOC uses to ground its answers in
standards and runbooks:

```
   incident / question
        │
        ▼
   ┌──────────┐   ┌──────────────┐   ┌───────────┐   ┌─────────────┐   ┌──────────┐
   │  EMBED   │──►│   RETRIEVE   │──►│  RERANK   │──►│   GROUND    │──►│ ABSTAIN? │
   │ OTel-Emb │   │ vector search│   │ OTel-Rerk │   │ cite top-K  │   │  gate    │
   └──────────┘   └──────────────┘   └───────────┘   └─────────────┘   └──────────┘
     335M / CPU     cosine (norm!)      0.6B / CPU      answer+sources    safety
```

Everything runs on **CPU, no Databricks account required** — so a customer can explore the
mechanics before committing to serving infrastructure (that's Chapters 3–4).

👉 **[`notebooks/01_otel_rag_pipeline.ipynb`](../../notebooks/01_otel_rag_pipeline.ipynb)**

---

## What we isolated from a production demo — and the lessons baked in

This pipeline mirrors how a mature Databricks self-healing NOC demo wires the OTel models
together. Rather than leave you to rediscover its hard-won lessons, they're taught here as
first-class content:

| Stage | OTel model | The lesson (learned the hard way in production) |
|---|---|---|
| **Embed** | `OTel-Embedding-335M` | The embedder returns raw vectors; **you must L2-normalize** both corpus and query. Databricks Vector Search ranks by **L2 distance only** — normalizing is what makes L2 ranking equal cosine ranking. Get this wrong and every score/threshold is off. |
| **Retrieve** | (vector index) | Use **raw query text, no prompt prefix** for this family of fine-tunes — it's prefix-insensitive. Normalize the **query** vector too. |
| **Rerank** | `OTel-Reranker-0.6B` | A reranker is only worth adding if it **discriminates**. In production this exact reranker sometimes returned near-constant scores and had to be disabled. So we **validate it before trusting it** — a dedicated cell checks the score spread and warns if it's flat. |
| **Ground + abstain** | (assembly + gate) | Don't answer from weak evidence. If the top relevance is below threshold, **abstain** ("insufficient grounded context") rather than hallucinate. This is the safety gate a self-healing loop needs before it recommends touching a live network. |

---

## Why this matters for a self-healing network

A self-healing loop can only act as well as it can *reason*, and it can only reason as well
as it can *ground*. This pipeline is the grounding layer: given a live symptom ("cells show
low throughput at low load"), it retrieves the right 3GPP/O-RAN clause and hands the agent a
**cited, trustworthy** basis for its diagnosis — or honestly abstains.

In [Chapter 2](../02-agent-loop/) this pipeline becomes the `retrieve_standards` step of the
autonomous ReAct agent in [`app/app.py`](../../app/app.py), replacing its placeholder keyword match.
That's the moment the north-star loop starts running on real OTel intelligence.

---

## Run it

```bash
pip install -r ../../requirements.txt
jupyter lab ../../notebooks/01_otel_rag_pipeline.ipynb
```

First run downloads the embedding (~335M) and reranker (~0.6B) weights and caches them. The
reranker needs `trust_remote_code=True` (its Qwen3-based architecture ships custom code).
CPU is fine for the small demo corpus; expect the reranker to take a few seconds per query.
