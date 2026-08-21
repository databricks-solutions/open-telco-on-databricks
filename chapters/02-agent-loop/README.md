# Chapter 2 — The self-healing agent loop

_Drop the OTel grounding pipeline into an autonomous **ReAct** loop, so the agent's every step
is grounded in real telecom standards — the north-star experience, now running on real OTel
intelligence. Still on your laptop._

---

## Where this sits

[Chapter 1](../01-rag-pipeline/) built the grounding pipeline as a standalone function.
[`app/app.py`](../../app/app.py) (the repo's north-star demo) is an autonomous **ReAct + reflection**
agent — Think → Act → Observe → Reflect — that troubleshoots a network fault by calling
OSS/BSS/KPI tools and a `retrieve_standards` tool.

But in `app/app.py` that `retrieve_standards` tool is a **keyword match** over a handful of
hard-coded snippets. **This chapter swaps it for the OTel pipeline from Chapter 1** — so when
the agent reaches for standards to ground its diagnosis, it does *real semantic retrieval*.

```
   THINK ─► ACT ─► OBSERVE ─► REFLECT ─┐
     ▲         │                        │
     └─────────┴────────────────────────┘   (max N rounds)
               │
               ├─ get_network_kpis   (OSS)
               ├─ get_alarms         (OSS)
               ├─ get_bss_data       (BSS)
               └─ retrieve_standards ─► ★ OTel embedding pipeline (was: keyword match)
```

👉 **[`notebooks/02_self_healing_agent_loop.ipynb`](../../notebooks/02_self_healing_agent_loop.ipynb)** — CPU, no Databricks account needed.

---

## What the notebook does

1. Rebuilds the **OTel grounding** function from Chapter 1 (embed → retrieve → abstain).
2. Defines a tiny **synthetic network** (KPIs, alarms, BSS impact) and the agent's tools.
3. Runs a compact **ReAct loop** that plans tool calls, grounds its hypothesis via OTel
   retrieval, quantifies business impact, and concludes with a **cited, human-gated**
   recommendation.
4. Shows the **before/after** that matters: a paraphrased incident where the old keyword match
   misses the right standard and OTel semantic retrieval nails it.

---

## Why this is the turning point

This is the moment the pieces become a *system*. The agent doesn't just retrieve — it
**reasons over grounded evidence** and stops at a recommendation a human signs off on. That's
the shape of a self-healing loop you can actually trust near a live network.

The full [`app/app.py`](../../app/app.py) adds a browser UI, OpenTelemetry-style span tracing, and a
pluggable reasoning brain (mock → Claude → an OTel LLM). This chapter keeps it CPU-simple and
focuses on the one swap that makes it real: **OTel as the grounding brain.**

**Next:** [Chapter 3](../03-productionize/) and [Chapter 4](../04-govern-capture/) take this
exact pipeline to Databricks — governed serving, Vector Search, and full inference capture.
