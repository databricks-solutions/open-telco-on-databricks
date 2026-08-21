# Databricks notebook source
# MAGIC %md
# MAGIC # 02 · Serve the OTel reasoning LLM
# MAGIC
# MAGIC Codifies serving the Open Telco reasoning LLM standalone: download from HuggingFace ->
# MAGIC log with `mlflow.transformers` (`task="llm/v1/chat"`) -> register to Unity Catalog ->
# MAGIC GPU Model Serving endpoint (OpenAI-chat contract).
# MAGIC
# MAGIC **Default:** `farbodtavakkoli/OTel-LLM-1.2B-IT` — a 1.2B instruction-tuned model that serves on
# MAGIC **GPU_SMALL** (scale-to-zero), the cheap/feasible path.
# MAGIC
# MAGIC **Full model:** set `llm_hf_id=farbodtavakkoli/OTel-2.0-LLM-31B-IT` and use `GPU_LARGE`
# MAGIC (its base arch is provisioned-throughput-eligible; switch to a provisioned-throughput
# MAGIC endpoint for production latency/cost). Requires GPU serving capacity in the workspace.

# COMMAND ----------
# MAGIC %pip install -q "mlflow>=2.13" "transformers>=4.40.0" torch torchvision accelerate sentencepiece einops databricks-sdk
# COMMAND ----------
dbutils.library.restartPython()

# COMMAND ----------
dbutils.widgets.text("catalog", "cmegdemos_catalog")
dbutils.widgets.text("schema", "otel_selfhealing")
dbutils.widgets.text("llm_hf_id", "farbodtavakkoli/OTel-LLM-1.2B-IT")
dbutils.widgets.text("llm_endpoint", "otel-selfhealing-llm")
dbutils.widgets.text("workload_type", "GPU_SMALL")   # GPU_LARGE for the 31B
g = dbutils.widgets.get
CATALOG, SCHEMA = g("catalog"), g("schema")
LLM_HF_ID, LLM_ENDPOINT, WORKLOAD = g("llm_hf_id"), g("llm_endpoint"), g("workload_type")
LLM_UC_MODEL = f"{CATALOG}.{SCHEMA}.{LLM_HF_ID.split('/')[-1].replace('.', '_').replace('-', '_').lower()}"

# COMMAND ----------
# MAGIC %md ## Download + log the model to Unity Catalog (chat task)

# COMMAND ----------
import mlflow
from transformers import AutoModelForCausalLM, AutoTokenizer
mlflow.set_registry_uri("databricks-uc")

tok = AutoTokenizer.from_pretrained(LLM_HF_ID, trust_remote_code=True)
mdl = AutoModelForCausalLM.from_pretrained(LLM_HF_ID, trust_remote_code=True)

with mlflow.start_run(run_name=f"log-{LLM_HF_ID.split('/')[-1]}"):
    info = mlflow.transformers.log_model(
        transformers_model={"model": mdl, "tokenizer": tok},
        artifact_path="model",
        task="llm/v1/chat",                       # exposes the OpenAI-chat contract
        registered_model_name=LLM_UC_MODEL,
        metadata={"source": LLM_HF_ID},
    )
print("registered:", LLM_UC_MODEL)

from mlflow.tracking import MlflowClient
c = MlflowClient(registry_uri="databricks-uc")
LLM_VERSION = max(int(mv.version) for mv in c.search_model_versions(f"name='{LLM_UC_MODEL}'"))
print("version:", LLM_VERSION)

# COMMAND ----------
# MAGIC %md ## Serve on GPU (scale-to-zero)

# COMMAND ----------
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import EndpointCoreConfigInput, ServedEntityInput
w = WorkspaceClient()
served = [ServedEntityInput(entity_name=LLM_UC_MODEL, entity_version=str(LLM_VERSION),
                            scale_to_zero_enabled=True, workload_size="Small", workload_type=WORKLOAD)]
# Non-blocking create/update — GPU endpoints can take 15-25 min to provision.
existing = [e.name for e in w.serving_endpoints.list()]
try:
    if LLM_ENDPOINT in existing:
        w.serving_endpoints.update_config(name=LLM_ENDPOINT, served_entities=served)
        print("updating endpoint (provisioning in background):", LLM_ENDPOINT)
    else:
        w.serving_endpoints.create(name=LLM_ENDPOINT, config=EndpointCoreConfigInput(served_entities=served))
        print("creating endpoint (provisioning in background):", LLM_ENDPOINT)
except Exception as e:
    print("serving create/update note:", str(e)[:160])

# COMMAND ----------
# MAGIC %md ## Wait for READY, then smoke test the OpenAI-chat contract

# COMMAND ----------
import time
for _ in range(90):  # up to ~30 min for GPU provisioning
    st = w.serving_endpoints.get(LLM_ENDPOINT).state
    if getattr(st, "ready", None) and str(st.ready) == "READY":
        break
    print("endpoint:", getattr(st, "config_update", None), getattr(st, "ready", None)); time.sleep(20)
try:
    resp = w.serving_endpoints.query(
        name=LLM_ENDPOINT,
        messages=[{"role": "user", "content": "One sentence: what causes low 5G throughput at low PRB load?"}],
        max_tokens=80)
    print(resp.as_dict() if hasattr(resp, "as_dict") else resp)
    print("LLM ENDPOINT READY:", LLM_ENDPOINT)
except Exception as e:
    print("endpoint still provisioning; smoke test deferred:", str(e)[:160])
