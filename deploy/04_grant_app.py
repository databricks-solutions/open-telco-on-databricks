# Databricks notebook source
# MAGIC %md
# MAGIC # 04 · Grant the app's service principal (Unity Catalog governance)
# MAGIC
# MAGIC The `otel-vision` Databricks App runs as a service principal. Everything it touches is
# MAGIC granted explicitly here — UC data (SELECT), the serving endpoints (CAN_QUERY), and the SQL
# MAGIC warehouse (CAN_USE) — so access is governed and auditable.

# COMMAND ----------
# MAGIC %pip install -q databricks-sdk
# COMMAND ----------
dbutils.library.restartPython()

# COMMAND ----------
dbutils.widgets.text("catalog", "cmegdemos_catalog")
dbutils.widgets.text("schema", "otel_selfhealing")
dbutils.widgets.text("app_sp", "")            # app service principal application (client) id
dbutils.widgets.text("emb_endpoint", "otel-selfhealing-embedding")
dbutils.widgets.text("llm_endpoint", "otel-llm-1b-it")   # the reasoning endpoint the app calls
dbutils.widgets.text("warehouse_id", "")
g = dbutils.widgets.get
CATALOG, SCHEMA, SP = g("catalog"), g("schema"), g("app_sp")
assert SP, "set app_sp to the app's service principal client id (databricks apps get otel-vision)"

# COMMAND ----------
# MAGIC %md ## UC data grants

# COMMAND ----------
spark.sql(f"GRANT USE CATALOG ON CATALOG {CATALOG} TO `{SP}`")
spark.sql(f"GRANT USE SCHEMA ON SCHEMA {CATALOG}.{SCHEMA} TO `{SP}`")
spark.sql(f"GRANT SELECT ON SCHEMA {CATALOG}.{SCHEMA} TO `{SP}`")
print("granted USE CATALOG/SCHEMA + SELECT on", f"{CATALOG}.{SCHEMA}", "to", SP)

# COMMAND ----------
# MAGIC %md ## Serving endpoint + warehouse grants (via permissions API)

# COMMAND ----------
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import ServingEndpointAccessControlRequest, ServingEndpointPermissionLevel
from databricks.sdk.service.sql import WarehouseAccessControlRequest, WarehousePermissionLevel
w = WorkspaceClient()

for ep in [g("emb_endpoint"), g("llm_endpoint")]:
    try:
        eid = w.serving_endpoints.get(ep).id
        w.serving_endpoints.update_permissions(serving_endpoint_id=eid, access_control_list=[
            ServingEndpointAccessControlRequest(service_principal_name=SP,
                permission_level=ServingEndpointPermissionLevel.CAN_QUERY)])
        print("CAN_QUERY granted on endpoint", ep)
    except Exception as e:
        print("skip endpoint", ep, "->", str(e)[:120])

wid = g("warehouse_id")
if wid:
    w.warehouses.update_permissions(warehouse_id=wid, access_control_list=[
        WarehouseAccessControlRequest(service_principal_name=SP,
            permission_level=WarehousePermissionLevel.CAN_USE)])
    print("CAN_USE granted on warehouse", wid)

# COMMAND ----------
print("GRANTS COMPLETE for app SP", SP)
