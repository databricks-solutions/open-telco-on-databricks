# deploy/ — make it real, end to end

Codifies the **entire** live stack so the repo stands up standalone in any Databricks
workspace — data, served models, index, capture, governance, and the animated app. No manual
clicks; everything here is reproducible.

## One command

```bash
./deploy/deploy.sh <your-databricks-cli-profile>      # e.g. fevm-cmegdemos
```

That runs, in order:

| Step | Notebook | Creates |
|------|----------|---------|
| 0 | `00_seed_data.py` | UC schema + `standards_corpus`, `network_kpis`, `bss_impact` (governed Delta) |
| 1 | `01_serve_embedding.py` | `OTel-Embedding-335M` → UC model → **CPU** serving endpoint → **Vector Search** index |
| 2 | `02_serve_llm.py` | An OTel LLM (default `OTel-LLM-1.2B-IT`) → UC model → **GPU** serving endpoint (chat) |
| 3 | `03_govern_capture.py` | **Inference tables** (AI Gateway) on both endpoints |
| 4 | `04_grant_app.py` | UC + endpoint + warehouse grants to the app's service principal |
| — | (deploy.sh) | Creates/deploys the `otel-vision` **app** wired to all of the above |

## What the app then does (real, not mock)

- **Grounding** (`retrieve_standards`) → embeds the query on the OTel embedding endpoint, L2-normalizes it, and queries the Vector Search index.
- **Reasoning brain** → a served **OTel LLM** (OpenAI-chat contract) drives the ReAct loop.
- **KPI / alarm / config / BSS tools** → read the governed Unity Catalog tables via SQL.
- **Capture** → every embedding/LLM inference lands in a UC inference table.

## Serving your own LLM vs. reusing one

`02_serve_llm.py` codifies standing up your **own** governed OTel LLM endpoint from HuggingFace.
By default `deploy.sh` also points the app at the reasoning endpoint via `OTEL_LLM_ENDPOINT`
(default `otel-llm-1b-it` to reuse an already-governed endpoint and avoid a duplicate GPU).
To use the one you just served, set `OTEL_LLM_ENDPOINT=otel-selfhealing-llm` before deploying.

- **Cheap/feasible:** `OTel-LLM-1.2B-IT` on `GPU_SMALL` (default).
- **Full model:** `llm_hf_id=farbodtavakkoli/OTel-2.0-LLM-31B-IT`, `workload_type=GPU_LARGE`
  (base arch is provisioned-throughput-eligible; needs GPU serving capacity).

## Config (env overrides, all optional)

`OTEL_CATALOG`, `OTEL_SCHEMA`, `OTEL_APP`, `OTEL_WAREHOUSE_ID`, `OTEL_LLM_ENDPOINT` — see the
top of `deploy.sh`. The app reads the matching `OTEL_*` values from `app/app.yaml`.

> Creates billable resources (serving endpoints, a Vector Search index). Endpoints use
> scale-to-zero; delete with `databricks apps delete` / `serving-endpoints delete` /
> `vector-search-indexes delete-index` when done.
