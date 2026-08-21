# Databricks notebook source
# MAGIC %md
# MAGIC # 03 · Govern & capture — inference tables on the endpoints
# MAGIC
# MAGIC Turns on AI Gateway request/response logging + usage tracking so every inference on the
# MAGIC embedding and LLM endpoints lands in a governed Unity Catalog Delta table. This is the
# MAGIC "capture" layer most demos skip.

# COMMAND ----------
# MAGIC %pip install -q databricks-sdk
# COMMAND ----------
dbutils.library.restartPython()

# COMMAND ----------
dbutils.widgets.text("catalog", "cmegdemos_catalog")
dbutils.widgets.text("schema", "otel_selfhealing")
dbutils.widgets.text("emb_endpoint", "otel-selfhealing-embedding")
dbutils.widgets.text("llm_endpoint", "otel-selfhealing-llm")
g = dbutils.widgets.get
CATALOG, SCHEMA = g("catalog"), g("schema")
ENDPOINTS = {g("emb_endpoint"): "emb_payload", g("llm_endpoint"): "llm_payload"}

# COMMAND ----------
from databricks.sdk import WorkspaceClient
w = WorkspaceClient()
live = {e.name for e in w.serving_endpoints.list()}
# Use the REST API directly (robust across SDK versions in the job runtime).
for name, prefix in ENDPOINTS.items():
    if name not in live:
        print("skip (not deployed yet):", name); continue
    body = {"inference_table_config": {"enabled": True, "catalog_name": CATALOG,
                                        "schema_name": SCHEMA, "table_name_prefix": prefix},
            "usage_tracking_config": {"enabled": True}}
    try:
        w.api_client.do("PUT", f"/api/2.0/serving-endpoints/{name}/ai-gateway", body=body)
        print("capture enabled on", name, "->", f"{CATALOG}.{SCHEMA}.{prefix}_payload")
    except Exception as e:
        print("capture note for", name, "->", str(e)[:160])

# COMMAND ----------
print("Captured payloads (async — appear shortly after traffic):")
display(spark.sql(f"SHOW TABLES IN {CATALOG}.{SCHEMA} LIKE '*payload*'"))
