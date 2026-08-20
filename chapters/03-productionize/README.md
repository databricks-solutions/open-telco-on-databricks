# Chapter 3 — Productionize on Databricks

_Take the **exact** models from Chapters 0–1 and put them on the platform: log → govern →
serve → index. This is where the laptop demo becomes something a team can share and operate._

---

## Where this sits

Chapters 0–1 ran everything in-process on a CPU. That's perfect for *understanding* OTel, but
it doesn't scale, isn't governed, and can't be shared. This chapter moves the pipeline onto
Databricks primitives — **without changing what the models do**:

```
   HF model  ──►  MLflow log  ──►  Unity Catalog  ──►  Model Serving  ──►  Vector Search
  (Ch 0/1)        (flavor)         (governed model)     (REST endpoint)     (scaled index)
```

👉 **[`notebooks/03_productionize_on_databricks.ipynb`](../../notebooks/03_productionize_on_databricks.ipynb)**

This is a **Databricks notebook** — it needs a workspace, a Unity Catalog you can write to, a
Vector Search endpoint, and Model Serving entitlement. It **creates billable resources** (a
serving endpoint, a Vector Search index), so run it deliberately.

---

## What the notebook does

| Step | Primitive | What happens |
|---|---|---|
| **1. Log + register** | MLflow + Unity Catalog | Log `OTel-Embedding-335M` with `mlflow.sentence_transformers`, registered as a **governed, versioned** UC model `<catalog>.<schema>.otel_embedding_335m`. |
| **2. Serve** | Model Serving | Deploy a **CPU** serving endpoint from the UC model version (335M serves fine on CPU — no GPU needed), scale-to-zero on. Then call it over REST. |
| **3. Index** | Vector Search | Embed the telecom corpus, write it to a **CDF-enabled Delta table** with **L2-normalized** vectors (the Chapter 1 lesson — so Vector Search's L2/HNSW ranking equals cosine), and build a **Delta-Sync index**. |
| **4. Query** | Vector Search | Retrieve with a **normalized query vector** (the other half of the lesson). |

---

## The mapping (from the demo plan)

Each OTel model maps to one serving primitive. Chapter 3 proves the loop **once, on the
smallest model** — the embedder — because that same log → UC → serve loop is the template every
other OTel model follows:

| OTel model | MLflow flavor | Serving |
|---|---|---|
| Embedding (335M) | `mlflow.sentence_transformers` | **CPU** Model Serving (this chapter) |
| Reranker (0.6B, cross-encoder) | `mlflow.transformers` (`AutoModelForSequenceClassification`) | small **GPU** serving |
| LLM (e.g. 20B, `gpt-oss` base) | `mlflow.transformers` (`text-generation`) | **provisioned throughput** (base arch is supported) or custom GPU |

The reranker and LLM steps are sketched at the end of the notebook — same pattern, different
flavor and workload type. Remember the Chapter 1 reality check: **validate the reranker
discriminates** before wiring it in.

---

## What's deliberately *not* here

**Capture and governance-of-use** — inference tables, monitoring, cost economics — is
[Chapter 4](../04-govern-capture/). Serving a model is table stakes; *capturing every
inference* is the part most demos skip, and it's our differentiator.
