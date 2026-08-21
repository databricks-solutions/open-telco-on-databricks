# Databricks notebook source
# MAGIC %md
# MAGIC # 01 · Serve the OTel embedding model + build the Vector Search index
# MAGIC
# MAGIC Codifies the full grounding-retrieval stack, standalone:
# MAGIC register `OTel-Embedding-335M` to Unity Catalog -> CPU Model Serving endpoint ->
# MAGIC embed the standards corpus (L2-normalized) -> self-managed Delta-Sync Vector Search index.

# COMMAND ----------
# MAGIC %pip install -q "sentence-transformers>=3.0.0" "mlflow>=2.13" databricks-vectorsearch databricks-sdk
# COMMAND ----------
dbutils.library.restartPython()

# COMMAND ----------
dbutils.widgets.text("catalog", "cmegdemos_catalog")
dbutils.widgets.text("schema", "otel_selfhealing")
dbutils.widgets.text("emb_hf_id", "farbodtavakkoli/OTel-Embedding-335M")
dbutils.widgets.text("emb_endpoint", "otel-selfhealing-embedding")
dbutils.widgets.text("vs_endpoint", "otel_selfhealing_vs")
g = dbutils.widgets.get
CATALOG, SCHEMA = g("catalog"), g("schema")
EMB_HF_ID, EMB_ENDPOINT, VS_ENDPOINT = g("emb_hf_id"), g("emb_endpoint"), g("vs_endpoint")
EMB_UC_MODEL = f"{CATALOG}.{SCHEMA}.otel_embedding_335m"
SRC_TABLE = f"{CATALOG}.{SCHEMA}.standards_corpus"
EMB_TABLE = f"{CATALOG}.{SCHEMA}.standards_corpus_emb"
INDEX_NAME = f"{CATALOG}.{SCHEMA}.standards_index"
EMB_DIM = 1024  # BGE-large

# COMMAND ----------
# MAGIC %md ## Register the embedding model to Unity Catalog

# COMMAND ----------
import mlflow, numpy as np
from sentence_transformers import SentenceTransformer
from mlflow.models.signature import infer_signature
mlflow.set_registry_uri("databricks-uc")

model = SentenceTransformer(EMB_HF_ID)
example = ["low 5G downlink throughput at low PRB load"]
sig = infer_signature(example, model.encode(example, normalize_embeddings=True))
with mlflow.start_run(run_name="log-otel-embedding-335m"):
    info = mlflow.sentence_transformers.log_model(
        model, artifact_path="model", signature=sig, input_example=example,
        registered_model_name=EMB_UC_MODEL)
print("registered:", EMB_UC_MODEL)

from mlflow.tracking import MlflowClient
c = MlflowClient(registry_uri="databricks-uc")
EMB_VERSION = max(int(mv.version) for mv in c.search_model_versions(f"name='{EMB_UC_MODEL}'"))
print("version:", EMB_VERSION)

# COMMAND ----------
# MAGIC %md ## Serve a CPU endpoint (335M runs fine on CPU; scale-to-zero)

# COMMAND ----------
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import EndpointCoreConfigInput, ServedEntityInput
w = WorkspaceClient()
served = [ServedEntityInput(entity_name=EMB_UC_MODEL, entity_version=str(EMB_VERSION),
                            scale_to_zero_enabled=True, workload_size="Small", workload_type="CPU")]
# Non-blocking: kick off provisioning and move on. The index build below embeds with the
# local model, so it does not depend on the endpoint being READY (endpoints can take 10-20 min).
existing = [e.name for e in w.serving_endpoints.list()]
try:
    if EMB_ENDPOINT in existing:
        w.serving_endpoints.update_config(name=EMB_ENDPOINT, served_entities=served)
        print("updating endpoint (provisioning in background):", EMB_ENDPOINT)
    else:
        w.serving_endpoints.create(name=EMB_ENDPOINT, config=EndpointCoreConfigInput(served_entities=served))
        print("creating endpoint (provisioning in background):", EMB_ENDPOINT)
except Exception as e:
    print("serving create/update note:", str(e)[:160])

# COMMAND ----------
# MAGIC %md ## Embed the corpus (L2-normalized) and write the index source table
# MAGIC Normalizing makes Vector Search's L2/HNSW ranking equal cosine ranking.

# COMMAND ----------
rows = spark.table(SRC_TABLE).select("doc_id", "cite", "content").collect()
texts = [r["content"] for r in rows]
vecs = model.encode(texts, normalize_embeddings=True)
import pandas as pd
pdf = pd.DataFrame({"doc_id": [r["doc_id"] for r in rows], "cite": [r["cite"] for r in rows],
                    "content": texts, "embedding": [v.tolist() for v in vecs]})
(spark.createDataFrame(pdf).write.mode("overwrite")
   .option("delta.enableChangeDataFeed", "true").saveAsTable(EMB_TABLE))
spark.sql(f"ALTER TABLE {EMB_TABLE} SET TBLPROPERTIES (delta.enableChangeDataFeed = true)")
print("wrote", EMB_TABLE, len(texts), "rows")

# COMMAND ----------
# MAGIC %md ## Build the self-managed Delta-Sync Vector Search index

# COMMAND ----------
import time
from databricks.vector_search.client import VectorSearchClient
vsc = VectorSearchClient(disable_notice=True)
try:
    vsc.get_endpoint(VS_ENDPOINT)
except Exception:
    vsc.create_endpoint(VS_ENDPOINT, endpoint_type="STANDARD")
for _ in range(60):  # wait until ONLINE (fresh endpoints take several minutes)
    st = (vsc.get_endpoint(VS_ENDPOINT).get("endpoint_status") or {}).get("state")
    if st == "ONLINE":
        break
    print("VS endpoint state:", st, "… waiting"); time.sleep(20)
print("VS endpoint ONLINE:", VS_ENDPOINT)

# COMMAND ----------
try:
    vsc.get_index(VS_ENDPOINT, INDEX_NAME).sync()
    print("re-synced existing index:", INDEX_NAME)
except Exception:
    vsc.create_delta_sync_index(
        endpoint_name=VS_ENDPOINT, index_name=INDEX_NAME, source_table_name=EMB_TABLE,
        pipeline_type="TRIGGERED", primary_key="doc_id",
        embedding_dimension=EMB_DIM, embedding_vector_column="embedding")
    print("creating index:", INDEX_NAME)
for _ in range(90):  # wait until the index has synced and is queryable
    try:
        s = vsc.get_index(VS_ENDPOINT, INDEX_NAME).describe().get("status", {})
        if s.get("ready"):
            print("index ready:", s.get("indexed_row_count"), "rows"); break
        print("index:", s.get("detailed_state"))
    except Exception as e:
        print("index poll:", str(e)[:80])
    time.sleep(20)

# COMMAND ----------
# MAGIC %md ## Smoke test — retrieve with a normalized query vector

# COMMAND ----------
q = model.encode("two adjacent cells share the same PCI", normalize_embeddings=True).tolist()
res = vsc.get_index(VS_ENDPOINT, INDEX_NAME).similarity_search(
    query_vector=q, columns=["cite", "content"], num_results=3)
for row in res["result"]["data_array"]:
    print(row)
print("EMBEDDING + INDEX READY")
