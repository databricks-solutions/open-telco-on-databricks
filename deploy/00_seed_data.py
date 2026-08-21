# Databricks notebook source
# MAGIC %md
# MAGIC # 00 · Seed data (Unity Catalog)
# MAGIC
# MAGIC Creates the governed schema and Delta tables the self-healing app reads from:
# MAGIC standards corpus (for RAG grounding) + synthetic OSS/BSS telemetry (the agent's tools).
# MAGIC Idempotent — safe to re-run. Everything is codified here so the repo stands up standalone.

# COMMAND ----------
dbutils.widgets.text("catalog", "cmegdemos_catalog")
dbutils.widgets.text("schema", "otel_selfhealing")
CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA}")
print("schema:", f"{CATALOG}.{SCHEMA}")

# COMMAND ----------
# MAGIC %md ## Standards corpus (grounding source for Vector Search)

# COMMAND ----------
STANDARDS = [
    ("d0", "3GPP TS 38.214 5.2", "Low SINR/CQI forces a lower MCS, reducing per-UE throughput even at moderate PRB. Low throughput with LOW PRB load indicates a radio-quality problem, not congestion."),
    ("d1", "3GPP TS 36.213 7.2", "LTE downlink throughput saturates as PRB utilization approaches 100%. Sustained PRB above 90% across neighboring cells in the busy hour is the signature of CONGESTION."),
    ("d2", "O-RAN WG1 UC", "Congestion remediation order: load-balance to under-utilized neighbors, enable carrier aggregation, add carrier/spectrum, then cell split or new site."),
    ("d3", "3GPP TS 36.331 8.1", "PCI collision between neighbor cells corrupts measurement reports and handovers, degrading SINR. Resolve PCI conflicts before RF optimization."),
    ("d4", "RF Ops Playbook", "Correlate recurring EXTERNAL_INTERFERENCE_UL alarms with low-SINR cells before adjusting antenna tilt or transmit power."),
    ("d5", "O-RAN F1", "The F1 interface connects the O-RAN Distributed Unit (O-DU) to the O-RAN Central Unit (O-CU), carrying F1-C and F1-U traffic."),
    ("d6", "CPRI/eCPRI Ops", "Loss of the CPRI/eCPRI fronthaul link between radio unit and baseband unit takes the cell off the air; dispatch a technician to inspect the fiber path."),
    ("d7", "TM Forum Open API", "Standardized management interfaces enable vendor-agnostic data collection across Huawei/Ericsson/Nokia OSS/BSS for closed-loop automation."),
]
df = spark.createDataFrame(STANDARDS, "doc_id string, cite string, content string")
(df.write.mode("overwrite").option("delta.enableChangeDataFeed", "true")
   .saveAsTable(f"{CATALOG}.{SCHEMA}.standards_corpus"))
spark.sql(f"ALTER TABLE {CATALOG}.{SCHEMA}.standards_corpus SET TBLPROPERTIES (delta.enableChangeDataFeed = true)")
print("standards_corpus:", df.count(), "rows")

# COMMAND ----------
# MAGIC %md ## OSS telemetry — network KPIs, alarms, cell config (the agent's read tools)

# COMMAND ----------
# schema: cell_id, region, tech, rsrp, sinr, cqi, prb, dl_mbps, ues, drop_pct, pci, alarm
KPIS = [
    ("gNB-4471_cell0", "Riverside", "5G-NR", -79, 18.2, 12.9, 41, 210, 32, 0.2, 118, None),
    ("gNB-4471_cell1", "Riverside", "5G-NR", -88, 4.1, 6.2, 44, 38, 41, 0.9, 311, "EXTERNAL_INTERFERENCE_UL"),
    ("gNB-4472_cell0", "Riverside", "5G-NR", -91, 3.4, 5.8, 39, 33, 37, 1.0, 311, "EXTERNAL_INTERFERENCE_UL"),
    ("eNB-12_cellA", "Metro", "4G-LTE", -84, 9.0, 8.0, 97, 6, 210, 0.6, 41, None),
    ("eNB-13_cellA", "Metro", "4G-LTE", -86, 8.4, 8.0, 99, 4, 240, 0.7, 52, None),
    ("eNB-14_cellA", "Metro", "4G-LTE", -83, 9.2, 8.0, 96, 8, 205, 0.5, 63, None),
    ("eNB-16_cellA", "Metro", "4G-LTE", -87, 8.1, 7.0, 98, 5, 231, 0.8, 85, None),
]
kdf = spark.createDataFrame(KPIS, "cell_id string, region string, tech string, rsrp int, sinr double, cqi double, prb int, dl_mbps int, ues int, drop_pct double, pci int, alarm string")
kdf.write.mode("overwrite").saveAsTable(f"{CATALOG}.{SCHEMA}.network_kpis")
print("network_kpis:", kdf.count(), "rows")

# COMMAND ----------
# MAGIC %md ## BSS impact (the agent's business-impact tool)

# COMMAND ----------
BSS = [
    ("Riverside", 5400, 63, 41.0, 12),
    ("Metro", 28800, 214, 33.0, 47),
]
bdf = spark.createDataFrame(BSS, "region string, affected_subscribers int, complaints_24h int, arpu double, vip_lines int")
bdf.write.mode("overwrite").saveAsTable(f"{CATALOG}.{SCHEMA}.bss_impact")
print("bss_impact:", bdf.count(), "rows")

# COMMAND ----------
print("SEED COMPLETE ->", f"{CATALOG}.{SCHEMA}")
for t in ["standards_corpus", "network_kpis", "bss_impact"]:
    print(" ", t, spark.table(f"{CATALOG}.{SCHEMA}.{t}").count(), "rows")
