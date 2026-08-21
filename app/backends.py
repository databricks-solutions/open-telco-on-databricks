"""Real Databricks backends for the OTel self-healing app.

Activated when OTEL_MODE=real (see app.yaml env). Replaces the app's synthetic stand-ins with:
  * DatabricksLLM   — the reasoning brain, a served OTel LLM (OpenAI-chat contract)
  * retrieve_standards — OTel embedding endpoint + Vector Search index (real RAG grounding)
  * KPI / alarm / config / BSS tools — governed Unity Catalog Delta tables

Everything authenticates as the app's service principal via the Databricks SDK default auth
(the workspace injects credentials into the Apps runtime). Self-contained: no import from app.py.
"""
from __future__ import annotations
import json
import math
import os

# --- config from env (set in app.yaml) ---
CATALOG = os.environ.get("OTEL_CATALOG", "cmegdemos_catalog")
SCHEMA = os.environ.get("OTEL_SCHEMA", "otel_selfhealing")
WAREHOUSE_ID = os.environ.get("OTEL_WAREHOUSE_ID", "")
EMB_ENDPOINT = os.environ.get("OTEL_EMB_ENDPOINT", "otel-selfhealing-embedding")
VS_ENDPOINT = os.environ.get("OTEL_VS_ENDPOINT", "otel_selfhealing_vs")
INDEX_NAME = os.environ.get("OTEL_INDEX", f"{CATALOG}.{SCHEMA}.standards_index")
LLM_ENDPOINT = os.environ.get("OTEL_LLM_ENDPOINT", "")

_W = None
def _w():
    global _W
    if _W is None:
        from databricks.sdk import WorkspaceClient
        _W = WorkspaceClient()
    return _W


# ---------------------------------------------------------------- JSON helpers
def _extract_json(text):
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1].lstrip("json").strip()
    start = text.find("{")
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    return json.loads(text)


def _slim(scratchpad):
    out = []
    for s in scratchpad:
        row = {"thought": s.get("thought")}
        if s.get("action"):
            row["action"] = s["action"]
            row["observation"] = s["observation"]
        out.append(row)
    return out


# ---------------------------------------------------------------- LLM backend
class DatabricksLLM:
    """Routes the ReAct policy + reflection through a served OTel LLM (OpenAI-chat contract)."""
    name = f"OTel LLM (Databricks serving: {LLM_ENDPOINT})"

    def __init__(self, fallback=None):
        if not LLM_ENDPOINT:
            raise RuntimeError("OTEL_LLM_ENDPOINT not set")
        self.ep = LLM_ENDPOINT
        self.fallback = fallback     # a MockLLM-like planner used if the model returns bad JSON

    def _call(self, system, user, max_tokens=700):
        body = {"messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}], "max_tokens": max_tokens}
        resp = _w().api_client.do("POST", f"/serving-endpoints/{self.ep}/invocations", body=body)
        obj = resp[0] if isinstance(resp, list) and resp else resp
        content = ((obj.get("choices") or [{}])[0].get("message") or {}).get("content", "") if isinstance(obj, dict) else ""
        return _extract_json(content)

    def policy(self, goal, scratchpad, tools):
        toolspec = "\n".join(f"- {n}: {t['desc']}" for n, t in tools.items())
        system = (
            "You are an autonomous telecom RAN/OSS-BSS troubleshooting agent running a ReAct loop. "
            "Reason step by step. At each step choose ONE tool to call, or conclude. "
            "Respond with ONLY a JSON object, no prose. Schemas:\n"
            '  {"thought": "...", "action": {"tool": "<name>", "args": {...}}}\n'
            '  {"thought": "...", "final": {"hypothesis":"...","reasoning":"...","business_impact":"...",'
            '"citations":["..."],"actions":["..."],"confidence":0.0}}\n'
            f"Available tools:\n{toolspec}\n"
            "Prefer to gather KPIs, then alarms/config, ground in standards, quantify BSS impact, then conclude. "
            "Never recommend auto-executing changes; actions are recommendations for human approval.")
        user = json.dumps({"goal": goal, "scratchpad": _slim(scratchpad)}, indent=2)
        try:
            step = self._call(system, user)
            if isinstance(step, dict) and ("action" in step or "final" in step):
                return step
        except Exception as e:
            print("[otel] policy JSON fallback:", str(e)[:120])
        if self.fallback:
            return self.fallback.policy(goal, scratchpad, tools)
        raise RuntimeError("LLM returned unusable output and no fallback planner is set")

    def reflect(self, goal, scratchpad):
        # Heuristic (no extra LLM round-trip) — keeps latency inside the app proxy window.
        return {"reflection": "evidence gathered; proceeding", "done": len(scratchpad) >= 5}

    def _call_text(self, system, user, max_tokens=400):
        body = {"messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}], "max_tokens": max_tokens}
        resp = _w().api_client.do("POST", f"/serving-endpoints/{self.ep}/invocations", body=body)
        obj = resp[0] if isinstance(resp, list) and resp else resp
        return ((obj.get("choices") or [{}])[0].get("message") or {}).get("content", "") if isinstance(obj, dict) else ""

    def synthesize_final(self, goal, scratchpad):
        """The OTel LLM authors the diagnosis as free text grounded in the real retrieved
        standards (robust for a small model). Raises on empty output so the caller can fall back."""
        obs = {s["action"]["tool"]: s["observation"] for s in scratchpad if s.get("action")}
        refs = [r for r in (obs.get("retrieve_standards") or []) if isinstance(r, dict)]
        cites = [r.get("cite") for r in refs]
        std_txt = "\n".join(f"- [{r.get('cite')}] {r.get('text')}" for r in refs)
        bss = obs.get("get_bss_data") or {}
        system = ("You are a telecom RAN/OSS-BSS troubleshooting expert. Using ONLY the retrieved "
                  "standards below, write a concise root-cause diagnosis. Start with a single line "
                  "'DIAGNOSIS: <one-line root cause>', then 2-4 sentences of reasoning that cite the "
                  "standards. Recommendations are for human approval only — never auto-execute.")
        user = (f"Incident: {goal.get('incident')}\nKPIs: {obs.get('get_network_kpis')}\n"
                f"Alarms: {obs.get('get_alarms')}\nConfig: {obs.get('get_cell_config')}\n"
                f"BSS: {bss}\nRetrieved standards:\n{std_txt}")
        raw = (self._call_text(system, user, max_tokens=400) or "").strip()
        if len(raw) < 40:
            raise ValueError("empty LLM final")
        first = raw.splitlines()[0].replace("DIAGNOSIS:", "").replace("Diagnosis:", "").strip()
        biz = (f"{bss.get('affected_subscribers'):,} subscribers, "
               f"~${bss.get('revenue_at_risk_per_day'):,.0f}/day at risk" if bss else "")
        return {"hypothesis": (first or "OTel LLM grounded diagnosis")[:140],
                "reasoning": raw, "business_impact": biz,
                "citations": cites,
                "actions": ["Review and approve the recommended remediation before any network change"],
                "confidence": 0.8}


# ---------------------------------------------------------------- SQL over UC
def _sql(query):
    r = _w().statement_execution.execute_statement(
        warehouse_id=WAREHOUSE_ID, catalog=CATALOG, schema=SCHEMA, statement=query, wait_timeout="30s")
    cols = [c.name for c in r.manifest.schema.columns]
    data = (r.result.data_array if r.result else None) or []
    return [dict(zip(cols, row)) for row in data]


def _i(v):
    try: return int(float(v))
    except Exception: return None
def _f(v):
    try: return float(v)
    except Exception: return None


def tool_get_network_kpis(region, tech="5G-NR", **_):
    q = f"SELECT * FROM network_kpis WHERE region = '{region}'" + (f" AND tech = '{tech}'" if tech else "")
    rows = _sql(q)
    cells = [{"id": r["cell_id"], "rsrp": _i(r["rsrp"]), "sinr": _f(r["sinr"]), "cqi": _f(r["cqi"]),
              "prb": _i(r["prb"]), "dl": _i(r["dl_mbps"]), "ues": _i(r["ues"]), "drop": _f(r["drop_pct"]),
              "pci": _i(r["pci"]), "alarm": r["alarm"]} for r in rows]
    return {"count": len(cells), "cells": cells,
            "avg_prb": round(sum(c["prb"] for c in cells) / max(1, len(cells)), 1),
            "min_dl_mbps": min((c["dl"] for c in cells), default=None)}


def tool_get_alarms(cell_ids=None, region=None, tech="5G-NR", **_):
    q = "SELECT cell_id, alarm FROM network_kpis WHERE alarm IS NOT NULL"
    if region: q += f" AND region = '{region}'"
    rows = _sql(q)
    ids = set(cell_ids) if cell_ids else None
    return {r["cell_id"]: [r["alarm"]] for r in rows if (ids is None or r["cell_id"] in ids)}


def tool_get_cell_config(cell_ids=None, region=None, tech="5G-NR", **_):
    q = "SELECT cell_id, pci, rsrp FROM network_kpis WHERE 1=1"
    if region: q += f" AND region = '{region}'"
    rows = _sql(q)
    ids = set(cell_ids) if cell_ids else None
    return {r["cell_id"]: {"pci": _i(r["pci"]), "rsrp": _i(r["rsrp"])}
            for r in rows if (ids is None or r["cell_id"] in ids)}


def tool_get_bss_data(region, **_):
    rows = _sql(f"SELECT * FROM bss_impact WHERE region = '{region}'")
    if not rows:
        return {}
    b = rows[0]
    out = {"affected_subscribers": _i(b["affected_subscribers"]), "open_complaints_24h": _i(b["complaints_24h"]),
           "arpu": _f(b["arpu"]), "vip_lines": _i(b["vip_lines"])}
    out["revenue_at_risk_per_day"] = round(out["affected_subscribers"] * out["arpu"] / 30.0, 2)
    return out


# ---------------------------------------------------------------- RAG grounding
def _embed(text):
    resp = _w().api_client.do("POST", f"/serving-endpoints/{EMB_ENDPOINT}/invocations",
                              body={"inputs": [text]})
    vec = resp["predictions"][0]
    n = math.sqrt(sum(x * x for x in vec)) or 1.0     # L2-normalize (index holds unit vectors)
    return [x / n for x in vec]


def _vsc():
    # VectorSearchClient does not auto-detect the Apps service-principal creds the way
    # WorkspaceClient does — pass them explicitly from the runtime env.
    from databricks.vector_search.client import VectorSearchClient
    host = os.environ.get("DATABRICKS_HOST") or _w().config.host
    if host and not host.startswith("http"):
        host = "https://" + host
    cid, csec = os.environ.get("DATABRICKS_CLIENT_ID"), os.environ.get("DATABRICKS_CLIENT_SECRET")
    if cid and csec:
        return VectorSearchClient(workspace_url=host, service_principal_client_id=cid,
                                  service_principal_client_secret=csec, disable_notice=True)
    return VectorSearchClient(disable_notice=True)


def tool_retrieve_standards(query, **_):
    res = _vsc().get_index(VS_ENDPOINT, INDEX_NAME).similarity_search(
        query_vector=_embed(query), columns=["cite", "content"], num_results=3)
    return [{"cite": row[0], "text": row[1]} for row in res["result"]["data_array"]]


# ---------------------------------------------------------------- wiring
def wire(TOOLS):
    """Point the app's tool registry at the real UC/VS-backed implementations."""
    TOOLS["get_network_kpis"]["fn"] = tool_get_network_kpis
    TOOLS["get_alarms"]["fn"] = tool_get_alarms
    TOOLS["get_cell_config"]["fn"] = tool_get_cell_config
    TOOLS["get_bss_data"]["fn"] = tool_get_bss_data
    TOOLS["retrieve_standards"]["fn"] = tool_retrieve_standards
    return TOOLS
