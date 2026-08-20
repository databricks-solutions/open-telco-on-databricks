# Chapter 0 — Vision

_Where we're going, why, and the smallest first step that makes it real._

---

## 1. The north star

Imagine a telecom network operations engineer facing a live incident:

> _"Subscribers report slow 5G data in the Riverside neighborhood; several NR cells show
> low downlink throughput."_

Instead of manually pulling KPIs from the OSS, cross-checking alarms, remembering the right
3GPP clause, and estimating business impact from the BSS, they hand it to an **autonomous
agent** that does exactly that — transparently, and always ending in a recommendation a human
signs off on.

That agent already exists in this repo as a runnable demo: [`otel.py`](../../otel.py).

```bash
python3 otel.py            # then open http://127.0.0.1:8000
python3 otel.py --selftest # or watch the loop run in your terminal
```

It runs a generic **ReAct + reflection** loop:

```
        ┌──────────► THINK ──────────┐
        │        (plan next step)     ▼
     REFLECT                         ACT ──► get_network_kpis   ─► OSS / NMS
   (critique,                     (tool call) get_alarms        ─► OSS / NMS
    are we done?)                             get_cell_config   ─► OSS / NMS
        ▲                                     get_bss_data      ─► BSS / CRM
        │                                     retrieve_standards ─► Standards KB
        └──────── OBSERVE ◄───────────────────┘
                (tool result)
```

Every LLM decision and tool call is captured as **OpenTelemetry-style spans** — a full,
exportable trace of the agent's reasoning.

**This is the experience we are building toward.** But two pieces of `otel.py` are
deliberately fake, and the whole point of this repo is to make them real:

| Stand-in in `otel.py` | What it becomes |
|---|---|
| `MockLLM` reasoning brain | The **Open Telco LLM** (`OTel-2.0-LLM-*-IT`), served on Databricks |
| `retrieve_standards` — a keyword match over 6 hard-coded snippets | The **OTel Embedding + Reranker** models over a real telco corpus in **Vector Search** |

---

## 2. What "Open Telco (OTel) AI" actually is

A telecom-domain **RAG** stack — **not** OpenTelemetry. A set of fine-tuned models and
datasets for telecom retrieval-augmented generation, trained on 3GPP / GSMA / O-RAN
standards, RFCs, and academic papers (~1.1M raw → 326K refined examples), published on
HuggingFace under [`farbodtavakkoli`](https://huggingface.co/farbodtavakkoli).

**Four model families make up the pipeline:**

1. **Embedding** — retrieve relevant passages (`OTel-Embedding-22M` … `-8B`)
2. **Reranker** — cross-encoder re-scoring of query/passage pairs (`OTel-Reranker-0.6B` … `-8B`)
3. **LLM** — generate grounded answers (`OTel-2.0-LLM-31B-IT`, and smaller variants)
4. **Safety / abstention** — abstain when the retrieved context is insufficient

Licensing: datasets Apache-2.0; models inherit their upstream base-checkpoint terms
(verify per model before serving).

---

## 3. The platform: OTel models as native Databricks primitives

Each OTel model maps cleanly onto a Databricks serving primitive. Stitched together they
become one **governed, observable** telco RAG assistant.

| OTel component | Databricks primitive | Serving notes |
|---|---|---|
| Embedding | UC model → Model Serving endpoint feeding **Vector Search** | CPU or small GPU |
| Reranker (cross-encoder) | UC model → GPU Model Serving | small GPU workload |
| LLM | UC model → **GPU Model Serving** | provisioned throughput *if* base arch supported, else custom GPU |
| Safety / abstention | same pattern as LLM | gate / guardrail step |

Two properties make this a Databricks story and not just a HuggingFace one:

- **Governance** — every model is a versioned Unity Catalog asset.
- **Capture** — **inference tables** (AI Gateway) land every request/response in a UC Delta
  table, paired with **Lakehouse Monitoring** for drift and quality. This is what turns a
  demo into something operable.

The full engineering plan (MLflow flavors, provisioned-throughput decision, GPU capacity,
gotchas) lives in [`otel-databricks-demo-plan.md`](../../otel-databricks-demo-plan.md).

---

## 4. Step 0 — run your first OTel model (no GPU, no Databricks)

Before any of the platform work, we prove one thing: **the models are real, they load, and
they do something useful.** We pick the cheapest possible entry point — a small embedding
model that runs on a laptop CPU.

👉 **[`notebooks/00_starter_load_and_inference.ipynb`](../../notebooks/00_starter_load_and_inference.ipynb)**

It loads [`OTel-Embedding-335M`](https://huggingface.co/farbodtavakkoli/OTel-Embedding-335M)
(BGE-large based, ~335M params, CPU-fine) and uses it to run **real semantic retrieval** over
a tiny corpus of telecom-standards snippets — the very snippets the `otel.py` agent cites in
its `retrieve_standards` tool.

So Step 0 isn't a toy: it is the first genuine component of the north-star loop, swapping
`otel.py`'s keyword match for actual OTel embeddings.

```bash
pip install -r ../../requirements.txt
jupyter lab ../../notebooks/00_starter_load_and_inference.ipynb
```

---

## 5. Where Chapter 1 picks up

Step 0 was one model doing one thing. [**Chapter 1**](../01-rag-pipeline/) assembles the
**full grounding pipeline** — embed → retrieve → rerank → ground → **abstain** — still on your
laptop, still CPU-only. It's the pattern a production Databricks self-healing NOC uses to
ground its answers, isolated so you can see every moving part, with its hard-won lessons
(vector normalization, reranker validation, safe abstention) taught up front.

From there: **Chapter 2** wires that pipeline into the `otel.py` agent loop, and
**Chapters 3–4** take it to Databricks — Unity Catalog registration, Model Serving, Vector
Search, and (the part most demos skip) full inference capture with monitoring.
