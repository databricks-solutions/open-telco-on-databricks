# Chapter 4 — Govern & Capture

_Serving a model is table stakes. **Capturing every inference**, monitoring it, and knowing
what it costs is the part most demos skip — and it's what makes a self-healing system
**operable and trustworthy**. This is our differentiator._

---

## Where this sits

[Chapter 3](../03-productionize/) governed and served the model. But a self-healing loop that
touches a live network needs more than a working endpoint — it needs an **audit trail** of
every decision, a way to **detect drift**, and an honest view of **cost**. Chapter 4 adds that
governance-of-use layer.

```
   Serving endpoint ──► Inference table ──► Monitoring ──► Cost ledger
   (Ch 3)              every request/resp    drift/quality   $ per decision
                       in a UC Delta table   dashboards      (open-source vs frontier)
```

👉 **[`notebooks/04_govern_and_capture.ipynb`](../../notebooks/04_govern_and_capture.ipynb)**

Runs against the serving endpoint from Chapter 3.

---

## What the notebook does

| Step | Primitive | What happens |
|---|---|---|
| **1. Capture** | **Inference tables** (AI Gateway) | Turn on request/response logging on the serving endpoint → every inference lands in a **UC Delta table**. This is the "capture model serving" deliverable. |
| **2. Inspect** | Delta / SQL | Send traffic, then read the captured payloads back out of the table. |
| **3. Monitor** | Lakehouse Monitoring | Attach a monitor to the inference table for drift / volume / quality dashboards. |
| **4. Cost** | Delta ledger | Record a **cost-economics ledger** row per decision: open-source in-zone (~$0 marginal) vs. a frontier per-token model — the sovereignty + economics story. |

---

## Why this is the differentiator

A mature production version of this demo serves the OTel models beautifully — but leaves the
embedding/reranker endpoints **un-governed and un-captured** (no UC registration, no inference
tables). That's the common shape: teams get to "it works" and stop.

For a **self-healing network**, that's not enough. Before an agent recommends touching a live
network, you need to answer:

- **What did the model actually see and say?** → inference tables (audit trail)
- **Is it still behaving?** → Lakehouse Monitoring (drift/quality)
- **What is each decision costing, and is the sovereign option cheaper?** → cost ledger

This chapter is what turns the pipeline from a demo into something an operator can **trust,
audit, and run**.

---

## Notes & caveats

- **API surfaces evolve.** The notebook uses the Databricks SDK (`WorkspaceClient`) and AI
  Gateway config objects; method/field names shift across SDK versions — the notebook flags
  where to check if a call signature has changed.
- **Inference tables are asynchronous.** Captured payloads appear a short delay after traffic;
  the exact payload-table name (`<prefix>` vs `<prefix>_payload`) depends on your workspace —
  the notebook shows how to discover it with `SHOW TABLES`.
- **Monitoring is schema-specific.** The monitor step is written for the payload schema and
  kept optional, since the right monitor profile depends on what you capture.
