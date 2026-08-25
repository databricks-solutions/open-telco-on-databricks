#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OTel ReAct Agent — Autonomous RAN/OSS-BSS Troubleshooting (runnable demo)
=========================================================================

A self-contained Python app that runs a GENERIC ReAct + Reflection agent loop
(Thought -> Action -> Observation -> Reflection, max 10 rounds) with real
tool-calling against synthetic OSS / BSS / network-KPI data, a browser UI to
drive it, a live visualization of the agentic loop and data flow, and
OpenTelemetry-style traces + spans collected for review and export.

WHY THIS SHAPE
--------------
* The LLM "brain" and the tools sit behind pluggable interfaces. Deployed on
  Databricks (OTEL_MODE=real — the default in app.yaml) the brain is a served
  OTel LLM and the tools read governed Unity Catalog data + Vector Search; see
  backends.py.
* If those backends aren't reachable the loop transparently falls back to a
  deterministic MockLLM + synthetic tools, so it still runs with zero setup
  (handy for local iteration). Set ANTHROPIC_API_KEY + OTEL_LLM=claude to route
  reasoning through Claude instead. The loop, tools, and tracing are identical
  across all three.

RUN IT
------
    # On Databricks (the default): deploy the whole stack — data, served models,
    # index, and this app — with  ./deploy/deploy.sh <profile>  (see ../deploy/README.md).

    # Local offline fallback:
    python3 app.py            # then open the URL it prints (default http://127.0.0.1:8000)

    # optional — use Claude as the reasoning engine locally:
    export ANTHROPIC_API_KEY=sk-ant-...
    export OTEL_LLM=claude
    export CLAUDE_MODEL=claude-sonnet-4-5   # override if needed

DEPENDENCIES: the offline fallback is Python 3.8+ standard library only (the
Claude backend uses urllib). The Databricks backends use databricks-sdk /
databricks-vectorsearch — see requirements.txt.
"""

import os
import sys
import json
import time
import uuid
import argparse
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# =============================================================================
# 1. SYNTHETIC OSS / BSS / KPI DATA  (stands in for Huawei U2000 / Ericsson ENM
#    on the OSS side and a BSS/CRM system on the business side)
# =============================================================================
SCENARIOS = {
    "5g_lowtput": {
        "label": "5G low throughput — Riverside neighborhood",
        "tech": "5G-NR", "region": "Riverside",
        "incident": ("Subscribers report slow 5G data in the Riverside neighborhood; "
                     "several NR cells show low downlink throughput."),
        "cells": [
            {"id": "gNB-4471_cell0", "rsrp": -79, "sinr": 18.2, "cqi": 12.9, "prb": 41, "dl": 210, "ues": 32, "drop": 0.2, "pci": 118, "alarm": None},
            {"id": "gNB-4471_cell1", "rsrp": -88, "sinr": 4.1,  "cqi": 6.2,  "prb": 44, "dl": 38,  "ues": 41, "drop": 0.9, "pci": 311, "alarm": "EXTERNAL_INTERFERENCE_UL"},
            {"id": "gNB-4472_cell0", "rsrp": -91, "sinr": 3.4,  "cqi": 5.8,  "prb": 39, "dl": 33,  "ues": 37, "drop": 1.0, "pci": 311, "alarm": "EXTERNAL_INTERFERENCE_UL"},
        ],
        "bss": {"affected_subscribers": 5400, "open_complaints_24h": 63, "arpu": 41.0, "vip_lines": 12},
    },
    "4g_congestion": {
        "label": "4G congestion — city-wide busy hour",
        "tech": "4G-LTE", "region": "Metro",
        "incident": ("Widespread 4G slowness across the metro area during the evening "
                     "busy hour affecting many sites."),
        "cells": [
            {"id": "eNB-12_cellA", "rsrp": -84, "sinr": 9.0, "cqi": 8, "prb": 97, "dl": 6,  "ues": 210, "drop": 0.6, "pci": 41, "alarm": None},
            {"id": "eNB-13_cellA", "rsrp": -86, "sinr": 8.4, "cqi": 8, "prb": 99, "dl": 4,  "ues": 240, "drop": 0.7, "pci": 52, "alarm": None},
            {"id": "eNB-14_cellA", "rsrp": -83, "sinr": 9.2, "cqi": 8, "prb": 96, "dl": 8,  "ues": 205, "drop": 0.5, "pci": 63, "alarm": None},
            {"id": "eNB-15_cellA", "rsrp": -85, "sinr": 9.1, "cqi": 9, "prb": 72, "dl": 26, "ues": 120, "drop": 0.4, "pci": 74, "alarm": None},
            {"id": "eNB-16_cellA", "rsrp": -87, "sinr": 8.1, "cqi": 7, "prb": 98, "dl": 5,  "ues": 231, "drop": 0.8, "pci": 85, "alarm": None},
            {"id": "eNB-17_cellA", "rsrp": -82, "sinr": 9.4, "cqi": 8, "prb": 95, "dl": 9,  "ues": 200, "drop": 0.5, "pci": 96, "alarm": None},
        ],
        "bss": {"affected_subscribers": 28800, "open_complaints_24h": 214, "arpu": 33.0, "vip_lines": 47},
    },
}

KNOWLEDGE_BASE = [
    ("3GPP TS 38.214 §5.2", "Low SINR/CQI forces a lower MCS -> low per-UE throughput even at "
     "moderate PRB. Low throughput with LOW PRB load indicates a radio-quality (interference/"
     "coverage) problem, not congestion."),
    ("3GPP TS 36.213 §7.2", "LTE downlink throughput saturates as PRB utilization approaches "
     "100%. Sustained PRB >90% across neighboring cells in busy hour is the signature of "
     "CONGESTION (capacity limit), not radio quality."),
    ("O-RAN WG1 UC", "Congestion remediation order: (1) load-balance/traffic-steer to under-"
     "utilized neighbors, (2) enable/verify carrier aggregation, (3) add carrier/spectrum, "
     "(4) cell split / new site."),
    ("3GPP TS 36.331 §8.1", "PCI collision between neighbor cells corrupts measurement reports "
     "and handovers, degrading SINR and raising drop/HO-failure rates. Resolve PCI conflicts "
     "before RF optimization."),
    ("RF Ops Playbook", "Correlate recurring EXTERNAL_INTERFERENCE_UL alarms with low-SINR cells "
     "before adjusting tilt or power."),
    ("TM Forum Open API", "Standardized management interfaces enable vendor-agnostic data "
     "collection across Huawei/Ericsson/Nokia OSS/BSS for closed-loop automation."),
]

# =============================================================================
# 2. OpenTelemetry-STYLE TRACER  (no external deps; spans exportable as JSON)
# =============================================================================
class Tracer:
    """Minimal OTel-shaped tracer: one trace, nested spans with attributes,
    events, timing and status. Export matches the mental model of OTLP."""

    def __init__(self):
        self.trace_id = uuid.uuid4().hex
        self.spans = []
        self._t0 = time.perf_counter()

    def _now_ms(self):
        return round((time.perf_counter() - self._t0) * 1000, 2)

    def span(self, name, kind="INTERNAL", attributes=None, parent=None):
        return _Span(self, name, kind, attributes or {}, parent)

    def export(self):
        return {"trace_id": self.trace_id, "spans": self.spans}


class _Span:
    def __init__(self, tracer, name, kind, attributes, parent):
        self.tr = tracer
        self.data = {
            "span_id": uuid.uuid4().hex[:16],
            "parent_span_id": parent,
            "name": name,
            "kind": kind,
            "attributes": attributes,
            "events": [],
            "status": "OK",
            "start_ms": None,
            "end_ms": None,
            "duration_ms": None,
        }

    @property
    def id(self):
        return self.data["span_id"]

    def event(self, name, **attrs):
        self.data["events"].append({"t_ms": self.tr._now_ms(), "name": name, "attrs": attrs})

    def set(self, **attrs):
        self.data["attributes"].update(attrs)

    def __enter__(self):
        self.data["start_ms"] = self.tr._now_ms()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.data["end_ms"] = self.tr._now_ms()
        self.data["duration_ms"] = round(self.data["end_ms"] - self.data["start_ms"], 2)
        if exc_type:
            self.data["status"] = "ERROR"
            self.data["attributes"]["error"] = str(exc)
        self.tr.spans.append(self.data)
        return False


# =============================================================================
# 3. TOOLS  (the agent's "hands" — OSS/BSS/KPI/RAG). Every call is traced.
# =============================================================================
def _cells(region, tech):
    for sc in SCENARIOS.values():
        if sc["region"] == region and sc["tech"] == tech:
            return sc["cells"]
    # fall back: match by region only
    for sc in SCENARIOS.values():
        if sc["region"] == region:
            return sc["cells"]
    return []


def _bss(region):
    for sc in SCENARIOS.values():
        if sc["region"] == region:
            return sc["bss"]
    return {}


def tool_get_network_kpis(region, tech="5G-NR", **_):
    """OSS/NMS (U2000/ENM) northbound: PM counters for cells in a region."""
    cells = _cells(region, tech)
    return {"count": len(cells), "cells": cells,
            "avg_prb": round(sum(c["prb"] for c in cells) / max(1, len(cells)), 1),
            "min_dl_mbps": min((c["dl"] for c in cells), default=None)}


def tool_get_alarms(cell_ids=None, region=None, tech="5G-NR", **_):
    """OSS: active alarms for the given cells (or all degraded cells in region)."""
    cells = _cells(region, tech) if region else [c for sc in SCENARIOS.values() for c in sc["cells"]]
    ids = set(cell_ids or [c["id"] for c in cells])
    return {cid: [c["alarm"]] for c in cells if (cid := c["id"]) in ids and c["alarm"]}


def tool_get_cell_config(cell_ids=None, region=None, tech="5G-NR", **_):
    """OSS: RF / PCI configuration for the given cells."""
    cells = _cells(region, tech) if region else [c for sc in SCENARIOS.values() for c in sc["cells"]]
    ids = set(cell_ids or [c["id"] for c in cells])
    return {c["id"]: {"pci": c["pci"], "rsrp": c["rsrp"]} for c in cells if c["id"] in ids}


def tool_get_bss_data(region, **_):
    """BSS/CRM: business impact — affected subscribers, complaints, ARPU, VIP lines."""
    b = _bss(region)
    if not b:
        return {}
    b = dict(b)
    b["revenue_at_risk_per_day"] = round(b["affected_subscribers"] * b["arpu"] / 30.0, 2)
    return b


def tool_retrieve_standards(query, **_):
    """RAG over the telecom standards corpus (OTel-Embedding + Reranker in prod)."""
    q = set(query.lower().split())
    scored = sorted(KNOWLEDGE_BASE, key=lambda kv: len(q & set(kv[1].lower().split())), reverse=True)
    return [{"cite": c, "text": t} for c, t in scored[:3]]


TOOLS = {
    "get_network_kpis": {"fn": tool_get_network_kpis,
        "desc": "Fetch PM counters (RSRP, SINR, CQI, PRB util, DL throughput, UEs) for cells in a region. args: region, tech"},
    "get_alarms": {"fn": tool_get_alarms,
        "desc": "Fetch active alarms for cells. args: cell_ids (list) or region"},
    "get_cell_config": {"fn": tool_get_cell_config,
        "desc": "Fetch RF/PCI configuration for cells. args: cell_ids (list) or region"},
    "get_bss_data": {"fn": tool_get_bss_data,
        "desc": "Fetch BSS/CRM business impact (affected subscribers, complaints, ARPU, revenue at risk). args: region"},
    "retrieve_standards": {"fn": tool_retrieve_standards,
        "desc": "RAG over 3GPP/O-RAN/TM-Forum standards to ground the diagnosis. args: query"},
}

TOOL_TO_BACKEND = {  # for the data-flow diagram
    "get_network_kpis": "OSS", "get_alarms": "OSS", "get_cell_config": "OSS",
    "get_bss_data": "BSS", "retrieve_standards": "KB",
}

# When OTEL_MODE=real, point the tool registry at the governed UC/Vector Search backends
# (synthetic stand-ins remain the fallback for local / offline runs).
if os.environ.get("OTEL_MODE") == "real":
    try:
        import backends
        backends.wire(TOOLS)
        print("[otel] real mode: tools wired to Unity Catalog + Vector Search", file=sys.stderr)
    except Exception as e:
        print(f"[warn] real backends unavailable ({e}); using synthetic tools.", file=sys.stderr)


# =============================================================================
# 4. LLM BACKENDS  (pluggable reasoning brain)
#    Contract: policy(goal, scratchpad, tools) -> dict with either
#       {"thought": str, "action": {"tool": str, "args": {...}}}
#    or  {"thought": str, "final": {...}}
#    reflect(goal, scratchpad) -> {"reflection": str, "done": bool}
# =============================================================================
class MockLLM:
    """Deterministic, no-API-key reasoning policy. Produces a genuine ReAct
    trajectory by planning the next sensible tool from what it already knows,
    then classifying the fault. Mirrors the shape a real LLM policy returns."""

    name = "MockLLM (offline, deterministic)"

    def policy(self, goal, scratchpad, tools):
        used = {s["action"]["tool"] for s in scratchpad if s.get("action")}
        obs = {s["action"]["tool"]: s["observation"] for s in scratchpad if s.get("action")}
        region = goal["region"]; tech = goal["tech"]

        if "get_network_kpis" not in used:
            return {"thought": "Start by pulling live KPIs for the affected region from the OSS.",
                    "action": {"tool": "get_network_kpis", "args": {"region": region, "tech": tech}}}

        kpi = obs["get_network_kpis"]
        sick = [c["id"] for c in kpi["cells"] if c["dl"] < 60 or c["prb"] >= 90]

        if "get_alarms" not in used:
            return {"thought": f"{len(sick)} cells look degraded. Check alarms on them before concluding.",
                    "action": {"tool": "get_alarms", "args": {"cell_ids": sick, "region": region, "tech": tech}}}

        if "get_cell_config" not in used:
            return {"thought": "Pull RF/PCI config to check for PCI collisions or coverage issues.",
                    "action": {"tool": "get_cell_config", "args": {"cell_ids": sick, "region": region, "tech": tech}}}

        if "retrieve_standards" not in used:
            sig = "congestion PRB" if kpi["avg_prb"] >= 90 else "SINR CQI interference PCI throughput"
            return {"thought": "Ground the hypothesis in the standards corpus.",
                    "action": {"tool": "retrieve_standards", "args": {"query": sig}}}

        if "get_bss_data" not in used:
            return {"thought": "Quantify business impact from the BSS before recommending action.",
                    "action": {"tool": "get_bss_data", "args": {"region": region}}}

        # enough evidence -> conclude
        return {"thought": "I have KPIs, alarms, config, standards and business impact. Concluding.",
                "final": self._diagnose(kpi, obs)}

    def _diagnose(self, kpi, obs):
        cells = kpi["cells"]; avg = kpi["avg_prb"]
        bss = obs.get("get_bss_data", {})
        if avg >= 90:
            hyp = "CONGESTION (capacity-limited)"
            reason = (f"Mean PRB utilization {avg:.0f}% with "
                      f"{sum(1 for c in cells if c['prb'] >= 90)} cells near 100% in busy hour; "
                      f"throughput collapses as PRB saturates — a capacity limit, not radio quality.")
            actions = ["Traffic-steer / load-balance to under-utilized neighbor cells",
                       "Verify / enable carrier aggregation on congested cells",
                       "Schedule spectrum / carrier addition; cell split if sustained"]
            cites = ["3GPP TS 36.213 §7.2", "O-RAN WG1 UC"]
        else:
            alarms = obs.get("get_alarms", {})
            cfg = obs.get("get_cell_config", {})
            pcis = {}; clash = None
            for cid, c in cfg.items():
                p = c["pci"]
                if p in pcis:
                    clash = f"PCI {p} shared by {pcis[p]} & {cid}"
                pcis[p] = cid
            hyp = "RADIO QUALITY — uplink interference / PCI confusion"
            reason = (f"{sum(1 for c in cells if c['dl'] < 60)} cell(s) show low throughput at low "
                      f"load (~{avg:.0f}% PRB), SINR < 6 dB, CQI < 7 → radio quality, not congestion. "
                      + (f"Recurring interference alarms on {list(alarms)}. " if alarms else "")
                      + (f"{clash}. " if clash else ""))
            actions = ([f"Resolve PCI collision ({clash}) — re-plan PCI FIRST"] if clash else []) + \
                      ["Mitigate the uplink interference source on affected cells",
                       "RF-optimize (tilt / power) only if SINR remains low"]
            cites = ["3GPP TS 38.214 §5.2", "3GPP TS 36.331 §8.1"]
        biz = ""
        if bss:
            biz = (f"Business impact (BSS): {bss.get('affected_subscribers'):,} subscribers, "
                   f"{bss.get('open_complaints_24h')} complaints/24h, "
                   f"~${bss.get('revenue_at_risk_per_day'):,.0f}/day revenue at risk"
                   + (f", {bss['vip_lines']} VIP lines." if bss.get('vip_lines') else "."))
        return {"hypothesis": hyp, "reasoning": reason, "business_impact": biz,
                "citations": cites, "actions": actions,
                "confidence": 0.86 if avg >= 90 else 0.83}

    def reflect(self, goal, scratchpad):
        last = scratchpad[-1] if scratchpad else None
        if not last or not last.get("action"):
            return {"reflection": "No observation yet.", "done": False}
        tool = last["action"]["tool"]
        n = len(scratchpad)
        notes = {
            "get_network_kpis": "KPIs in hand — localize which cells are degraded and why (load vs quality).",
            "get_alarms": "Alarm evidence gathered; correlate with the low-SINR cells.",
            "get_cell_config": "Config checked for PCI/coverage faults; almost ready to classify.",
            "retrieve_standards": "Hypothesis is now grounded in cited standards.",
            "get_bss_data": "Business impact quantified; ready to conclude and recommend (gated).",
        }
        return {"reflection": notes.get(tool, "Progressing."), "done": n >= 6}


class ClaudeLLM:
    """Routes the ReAct policy + reflection through the Claude Messages API.
    Activated when OTEL_LLM=claude and ANTHROPIC_API_KEY is set. Uses only urllib
    so there is nothing to pip-install. Swap the URL/model for your OTel-LLM
    endpoint later — the contract is identical."""

    name = "Claude (Anthropic Messages API)"
    API = "https://api.anthropic.com/v1/messages"

    def __init__(self):
        self.key = os.environ["ANTHROPIC_API_KEY"]
        self.model = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-5")

    def _call(self, system, user, max_tokens=700):
        body = json.dumps({
            "model": self.model, "max_tokens": max_tokens,
            "system": system, "messages": [{"role": "user", "content": user}],
        }).encode()
        req = urllib.request.Request(self.API, data=body, method="POST", headers={
            "content-type": "application/json", "x-api-key": self.key,
            "anthropic-version": "2023-06-01"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read())
        text = "".join(b.get("text", "") for b in data.get("content", []))
        return _extract_json(text)

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
        return self._call(system, user)

    def reflect(self, goal, scratchpad):
        system = ('Reflect on the ReAct trajectory so far. Respond ONLY as JSON: '
                  '{"reflection": "one sentence critique / next focus", "done": true|false}. '
                  'Set done=true only if there is enough evidence to diagnose confidently.')
        user = json.dumps({"goal": goal, "scratchpad": _slim(scratchpad)}, indent=2)
        try:
            return self._call(system, user, max_tokens=200)
        except Exception as e:
            return {"reflection": f"(reflection error: {e})", "done": len(scratchpad) >= 6}


def _slim(scratchpad):
    out = []
    for s in scratchpad:
        row = {"thought": s.get("thought")}
        if s.get("action"):
            row["action"] = s["action"]
            row["observation"] = s["observation"]
        out.append(row)
    return out


def _extract_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1].lstrip("json").strip()
    start = text.find("{"); depth = 0
    for i in range(start, len(text)):
        if text[i] == "{": depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    return json.loads(text)


class HybridLLM:
    """Real-mode brain: a deterministic planner drives the ReAct tool sequence (fast, robust),
    and the served OTel LLM authors the final grounded diagnosis in a single call over the real
    UC data + real Vector Search citations. Set OTEL_LLM_FULL_REACT=1 to have the OTel LLM drive
    every step instead (slower; needs a warm endpoint)."""
    def __init__(self, dbllm):
        self.mock = MockLLM()
        self.db = dbllm
        self.name = f"OTel LLM final-synthesis ({dbllm.ep}) + deterministic planner"

    def policy(self, goal, scratchpad, tools):
        step = self.mock.policy(goal, scratchpad, tools)
        if "final" in step:
            try:
                step["final"] = self.db.synthesize_final(goal, scratchpad)
            except Exception as e:
                print(f"[otel] final-synthesis fallback to deterministic diagnosis: {e}", file=sys.stderr)
        return step

    def reflect(self, goal, scratchpad):
        return self.mock.reflect(goal, scratchpad)


def make_llm():
    if os.environ.get("OTEL_LLM_ENDPOINT"):
        try:
            import backends
            dbllm = backends.DatabricksLLM(fallback=MockLLM())
            if os.environ.get("OTEL_LLM_FULL_REACT"):
                return dbllm
            return HybridLLM(dbllm)
        except Exception as e:
            print(f"[warn] Databricks OTel LLM backend unavailable ({e}); using MockLLM.", file=sys.stderr)
    if os.environ.get("OTEL_LLM", "").lower() == "claude" and os.environ.get("ANTHROPIC_API_KEY"):
        try:
            return ClaudeLLM()
        except Exception as e:
            print(f"[warn] Claude backend unavailable ({e}); using MockLLM.", file=sys.stderr)
    return MockLLM()


# =============================================================================
# 5. THE GENERIC ReAct + REFLECTION AGENT LOOP  (max 10 rounds)
# =============================================================================
class ReActAgent:
    MAX_ROUNDS = 10

    def __init__(self, llm):
        self.llm = llm

    def run(self, scenario):
        goal = {"incident": scenario["incident"], "region": scenario["region"],
                "tech": scenario["tech"], "objective": "diagnose root cause and recommend remediation (human-gated)"}
        tr = Tracer()
        events = []
        scratchpad = []

        def emit(**e):
            e["ts_ms"] = tr._now_ms()
            events.append(e)

        with tr.span("agent.run", kind="SERVER",
                     attributes={"llm": self.llm.name, "incident": goal["incident"],
                                 "max_rounds": self.MAX_ROUNDS}) as root:
            emit(t="start", llm=self.llm.name, goal=goal)
            final = None

            for rnd in range(1, self.MAX_ROUNDS + 1):
                with tr.span(f"round.{rnd}", parent=root.id, attributes={"round": rnd}) as rspan:
                    emit(t="round", n=rnd)

                    # --- THINK / ACT (LLM policy) ---
                    with tr.span("llm.policy", kind="CLIENT", parent=rspan.id,
                                 attributes={"round": rnd, "model": self.llm.name}) as pspan:
                        step = self.llm.policy(goal, scratchpad, TOOLS)
                        pspan.set(decision="final" if "final" in step else "action")
                    thought = step.get("thought", "")
                    emit(t="thought", n=rnd, text=thought)

                    if "final" in step:
                        final = step["final"]
                        emit(t="final", n=rnd, **final)
                        rspan.event("concluded")
                        root.set(rounds_used=rnd, outcome="diagnosed")
                        break

                    action = step["action"]
                    tool = action["tool"]; args = action.get("args", {})
                    emit(t="action", n=rnd, tool=tool, args=args, backend=TOOL_TO_BACKEND.get(tool, "?"))

                    # --- OBSERVE (tool call, traced as its own span) ---
                    with tr.span(f"tool.{tool}", kind="CLIENT", parent=rspan.id,
                                 attributes={"tool": tool, "args": args,
                                             "backend": TOOL_TO_BACKEND.get(tool, "?")}) as tspan:
                        try:
                            result = TOOLS[tool]["fn"](**args)
                            tspan.set(result_summary=_summarize(tool, result))
                            tspan.event("tool_ok")
                        except Exception as ex:  # noqa
                            result = {"error": str(ex)}
                            tspan.event("tool_error", error=str(ex))
                    summary = _summarize(tool, result)
                    emit(t="observation", n=rnd, tool=tool, summary=summary, data=result,
                         backend=TOOL_TO_BACKEND.get(tool, "?"))
                    scratchpad.append({"thought": thought, "action": action, "observation": result})

                    # --- REFLECT ---
                    with tr.span("llm.reflect", kind="CLIENT", parent=rspan.id,
                                 attributes={"round": rnd}) as fspan:
                        refl = self.llm.reflect(goal, scratchpad)
                        fspan.set(done=refl.get("done", False))
                    emit(t="reflection", n=rnd, text=refl.get("reflection", ""), done=refl.get("done", False))

            else:
                emit(t="halt", reason="max_rounds")
                root.set(rounds_used=self.MAX_ROUNDS, outcome="halted_max_rounds")

        return {"events": events, "trace": tr.export(), "final": final,
                "scratchpad": _slim(scratchpad), "llm": self.llm.name}


def _summarize(tool, result):
    if isinstance(result, dict) and "error" in result:
        return f"error: {str(result['error'])[:160]}"
    if not isinstance(result, dict):
        return str(result)[:120]
    if tool == "get_network_kpis":
        return f"{result.get('count')} cells · avg PRB {result.get('avg_prb')}% · min DL {result.get('min_dl_mbps')} Mbps"
    if tool == "get_alarms":
        return (", ".join(f"{k}: {v[0]}" for k, v in result.items()) if result else "no active alarms")
    if tool == "get_cell_config":
        return f"config for {len(result)} cells (PCIs {sorted({c['pci'] for c in result.values()})})"
    if tool == "get_bss_data":
        return (f"{result.get('affected_subscribers','?'):,} subs · {result.get('open_complaints_24h','?')} "
                f"complaints/24h · ${result.get('revenue_at_risk_per_day','?'):,}/day at risk")
    if tool == "retrieve_standards":
        return "top refs: " + ", ".join(r["cite"] for r in result)
    return json.dumps(result)[:120]


# =============================================================================
# 6. WEB SERVER + UI
# =============================================================================
def build_scenarios_json():
    return json.dumps([{"id": k, "label": v["label"], "tech": v["tech"],
                        "region": v["region"], "incident": v["incident"]}
                       for k, v in SCENARIOS.items()])


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _send(self, code, ctype, body):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            html = HTML.replace("%%SCENARIOS%%", build_scenarios_json()) \
                       .replace("%%LLM%%", make_llm().name)
            self._send(200, "text/html; charset=utf-8", html)
        else:
            self._send(404, "text/plain", "not found")

    def do_POST(self):
        if self.path != "/run":
            self._send(404, "text/plain", "not found")
            return
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or "{}")
        sid = payload.get("scenario", next(iter(SCENARIOS)))
        scenario = SCENARIOS.get(sid, next(iter(SCENARIOS.values())))
        # allow a custom incident override
        if payload.get("incident"):
            scenario = dict(scenario); scenario["incident"] = payload["incident"]
        try:
            agent = ReActAgent(make_llm())
            result = agent.run(scenario)
            self._send(200, "application/json", json.dumps(result))
        except Exception as e:  # never 502 — surface the error to the UI instead of crashing
            import traceback
            self._send(200, "application/json", json.dumps(
                {"error": str(e), "trace": traceback.format_exc()[-3000:]}))


# --- The UI (single-page; animates the returned events, draws data flow + spans) ---
HTML = r"""<!DOCTYPE html><html lang="en" data-theme="dark"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>OTel ReAct Agent · RAN/OSS-BSS Troubleshooting</title>
<style>
:root{--surface:#1a1a19;--s2:#111110;--page:#0d0d0d;--panel:#201f1e;--panel2:#262523;
--ink:#fff;--ink2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--border:rgba(255,255,255,.10);
--blue:#3987e5;--orange:#d95926;--aqua:#199e70;--violet:#9085e9;--yellow:#fab219;
--good:#0ca30c;--warn:#fab219;--crit:#d03b3b;--r:12px;
font-family:system-ui,-apple-system,"Segoe UI",sans-serif}
*{box-sizing:border-box}
body{margin:0;background:radial-gradient(1200px 600px at 80% -10%,#16223a55,transparent),var(--page);color:var(--ink)}
.wrap{max-width:1280px;margin:0 auto;padding:20px 20px 60px}
header{display:flex;gap:14px;align-items:flex-start;flex-wrap:wrap;justify-content:space-between}
.brand{display:flex;gap:13px;align-items:center}
.logo{width:44px;height:44px;border-radius:11px;background:linear-gradient(135deg,var(--blue),#1c5cab);display:grid;place-items:center;font-weight:800}
h1{font-size:19px;margin:0}
.sub{color:var(--ink2);font-size:13px;margin-top:3px;max-width:680px;line-height:1.45}
.tag{display:inline-block;font-size:11px;color:var(--ink2);border:1px solid var(--border);border-radius:999px;padding:3px 10px;margin-top:8px}
.tag b{color:var(--aqua)}
.ctrl{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin:18px 0}
select,button,input[type=text]{font:inherit}
select,input[type=text]{background:var(--panel2);color:var(--ink);border:1px solid var(--border);border-radius:9px;padding:9px 11px;font-size:13px}
input[type=text]{flex:1;min-width:240px}
button.run{background:linear-gradient(135deg,var(--blue),#1c5cab);color:#fff;border:0;border-radius:9px;padding:10px 18px;font-weight:700;cursor:pointer;font-size:13px}
button.run:disabled{opacity:.5;cursor:default}
button.ghost{background:transparent;color:var(--ink2);border:1px solid var(--border);border-radius:9px;padding:9px 13px;cursor:pointer;font-size:12.5px}
.grid{display:grid;grid-template-columns:1.3fr 1fr;gap:16px}
@media(max-width:960px){.grid{grid-template-columns:1fr}}
.card{background:var(--panel);border:1px solid var(--border);border-radius:var(--r);padding:15px}
.card h2{font-size:11.5px;text-transform:uppercase;letter-spacing:.09em;color:var(--muted);margin:0 0 12px;display:flex;justify-content:space-between}
/* ReAct loop graph (SVG) */
.loopwrap{width:100%;overflow-x:auto}
#loopsvg{width:100%;min-width:840px;height:auto;display:block}
.seg{fill:none;stroke:#44443f;stroke-width:2.6}
.seg.flow{stroke:var(--blue);stroke-dasharray:7 7;animation:march .55s linear infinite}
@keyframes march{to{stroke-dashoffset:-28}}
.edge{fill:none;stroke:#37362f;stroke-width:1.7}
.edge.act{stroke:var(--orange);stroke-width:2.6;stroke-dasharray:6 6;animation:march .45s linear infinite}
.pill rect{fill:var(--panel2);stroke:var(--border);stroke-width:1.5;transition:.2s}
.pill text{fill:var(--ink2);font-size:12.5px;font-weight:750;text-anchor:middle;letter-spacing:.06em}
.pill.on rect{fill:#16233a;stroke:var(--blue);stroke-width:2.5}
.pill.on text{fill:#fff}
.loopctr{fill:var(--muted);font-size:12px;font-weight:600;text-anchor:middle}
.loopcap{fill:#6d6c66;font-size:10px;text-anchor:middle;letter-spacing:.14em}
.tbox rect{fill:var(--panel2);stroke:var(--border);transition:.2s}
.tbox .tn{fill:var(--ink2);font-size:12px;text-anchor:middle;font-family:ui-monospace,Menlo,monospace}
.tbox .sub{fill:var(--muted);font-size:9.5px;text-anchor:middle}
.tbox.act rect{fill:#2a1a12;stroke:var(--orange);stroke-width:2.2}
.tbox.act .tn{fill:#fff}
.bbox rect{fill:var(--panel2);stroke:var(--border);transition:.2s}
.bbox .bn{fill:var(--ink);font-size:12.5px;text-anchor:middle;font-weight:650}
.bbox .sub{fill:var(--muted);font-size:9.5px;text-anchor:middle}
.bbox.act rect{stroke:var(--blue);stroke-width:2.4;fill:#16233a}
.svglabel{fill:#6d6c66;font-size:10px;letter-spacing:.14em;text-anchor:middle}
/* react stream */
.stream{max-height:520px;min-height:0;overflow:auto;display:flex;flex-direction:column;gap:10px}
/* Big screens: trace card fills its grid cell (matches the 3 right-hand blocks); stream grows */
@media(min-width:961px){#tracecard{display:flex;flex-direction:column}#tracecard>h2{flex:0 0 auto}#tracecard .stream{flex:1 1 auto;max-height:none}}
.round{border:1px solid var(--border);border-radius:10px;overflow:hidden;opacity:0;transform:translateY(6px);animation:in .3s forwards;min-width:0;flex-shrink:0}
@keyframes in{to{opacity:1;transform:none}}
.round .rh{background:var(--panel2);padding:7px 11px;font-size:11px;color:var(--muted);letter-spacing:.06em;text-transform:uppercase;font-weight:650}
.step{padding:8px 12px;font-size:12.8px;line-height:1.5;border-top:1px solid var(--grid);overflow-wrap:anywhere;word-break:break-word}
.step:first-of-type{border-top:0}
.lab{display:inline-block;font-weight:750;font-size:10.5px;letter-spacing:.05em;padding:1px 7px;border-radius:5px;margin-right:8px;vertical-align:1px}
.lab.think{background:#16233a;color:#7fb0ee}.lab.act{background:#2a1a12;color:#f0a074}
.lab.obs{background:#0f2a1f;color:#5fcf9f}.lab.refl{background:#1e1a33;color:#b3a7f5}.lab.final{background:#0f2a10;color:#67d267}
code{font-family:ui-monospace,Menlo,monospace;font-size:11.6px;color:var(--ink2);white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word}
.mono{font-family:ui-monospace,Menlo,monospace}
/* tool log */
table{width:100%;border-collapse:collapse;font-size:11.6px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--grid);vertical-align:top}
th{color:var(--muted);text-transform:uppercase;font-size:9.5px;letter-spacing:.06em}
td.mono{font-family:ui-monospace,monospace}
.badge{font-size:9.5px;padding:1px 6px;border-radius:5px;font-weight:700}
.badge.OSS{background:#2a1a12;color:#f0a074}.badge.BSS{background:#16233a;color:#7fb0ee}.badge.KB{background:#1e1a33;color:#b3a7f5}
/* spans */
.waterfall{font-size:11px}
.spanrow{display:flex;align-items:center;gap:8px;padding:3px 0}
.spanname{flex:0 0 210px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--ink2);font-family:ui-monospace,monospace;font-size:10.6px}
.spantrack{flex:1;height:15px;background:var(--s2);border-radius:4px;position:relative}
.spanbar{position:absolute;height:100%;border-radius:4px;background:var(--blue);display:flex;align-items:center;justify-content:flex-end;padding-right:4px;color:#fff;font-size:9px;font-weight:650}
.spanbar.tool{background:var(--orange)}.spanbar.llm{background:var(--violet)}.spanbar.round{background:#2b4a78}.spanbar.root{background:var(--aqua)}
/* diagnosis */
.diag{border-left:3px solid var(--crit);padding:11px 13px;background:var(--panel2);border-radius:0 10px 10px 0}
.diag.congest{border-color:var(--warn)}
.diag .h{font-weight:750;font-size:14px;margin-bottom:5px}
.diag .r{color:var(--ink2);font-size:12.6px;line-height:1.5}
.diag .biz{color:#7fb0ee;font-size:12px;margin-top:6px}
.cites{color:var(--muted);font-size:11px;margin-top:6px}.cites b{color:var(--ink2)}
ol{margin:8px 0 0;padding-left:18px;font-size:12.6px;line-height:1.55}
.gate{margin-top:10px;border:1px dashed var(--crit);border-radius:9px;padding:9px 11px;background:#d03b3b12}
.gate .m{font-weight:750;color:#f07070;font-size:12px}
.muted{color:var(--muted)}.foot{margin-top:22px;color:var(--muted);font-size:11.4px;line-height:1.6;border-top:1px solid var(--grid);padding-top:14px}
.kbd{font-family:ui-monospace,monospace;background:var(--s2);border:1px solid var(--border);border-radius:5px;padding:1px 6px;font-size:11px;color:var(--ink2)}
</style></head><body><div class="wrap">
<header>
  <div class="brand"><div class="logo">OT</div><div>
    <h1>OTel ReAct Agent · RAN / OSS-BSS Troubleshooting</h1>
    <div class="sub">A generic <b>ReAct + reflection</b> loop (Think → Act → Observe → Reflect,
      max 10 rounds) that calls OSS/BSS/KPI tools to diagnose a network fault, grounds it in
      standards, quantifies business impact, and recommends a <b>human-gated</b> fix. Every LLM
      and tool call is captured as OpenTelemetry-style spans for review.</div>
    <span class="tag">reasoning engine: <b>%%LLM%%</b> · swap in OTel-LLM later — the loop is unchanged</span>
  </div></div>
</header>

<div class="ctrl">
  <select id="scen"></select>
  <input type="text" id="incident" placeholder="…or describe your own incident">
  <button class="run" id="run">▶ Run agent</button>
  <button class="ghost" id="dl" disabled>⬇ Export trace (OTel JSON)</button>
  <span class="muted" id="status"></span>
</div>

<div class="card" style="margin-bottom:16px">
  <h2>ReAct agentic loop — Think → Act → Observe → Reflect <span class="muted" id="roundpill"></span></h2>
  <div class="loopwrap">
  <svg id="loopsvg" viewBox="0 0 960 360" preserveAspectRatio="xMidYMid meet">
    <defs>
      <marker id="ah" markerWidth="9" markerHeight="9" refX="5" refY="3" orient="auto" markerUnits="userSpaceOnUse">
        <path d="M0,0 L6,3 L0,6 Z" fill="#7a7a74"/></marker>
    </defs>
    <text class="svglabel" x="200" y="18">R E A C T   L O O P</text>
    <text class="svglabel" x="565" y="18">T O O L   C A L L S</text>
    <text class="svglabel" x="850" y="18">D A T A   S O U R C E S</text>

    <!-- ring segments (the loop edges, clockwise) -->
    <path class="seg" id="seg-think-act"     marker-end="url(#ah)" d="M224.9,72.6 A120,120 0 0 1 317.4,165"/>
    <path class="seg" id="seg-act-observe"   marker-end="url(#ah)" d="M317.4,215 A120,120 0 0 1 224.9,307.4"/>
    <path class="seg" id="seg-observe-reflect" marker-end="url(#ah)" d="M175.05,307.4 A120,120 0 0 1 82.6,215"/>
    <path class="seg" id="seg-reflect-think" marker-end="url(#ah)" d="M82.6,165.05 A120,120 0 0 1 175.05,72.6"/>

    <!-- ACT -> tool edges -->
    <path class="edge" id="e-act-get_network_kpis"   d="M368,190 C420,190 420,45 470,45"/>
    <path class="edge" id="e-act-get_alarms"         d="M368,190 C420,190 420,112 470,112"/>
    <path class="edge" id="e-act-get_cell_config"    d="M368,190 C420,190 420,179 470,179"/>
    <path class="edge" id="e-act-get_bss_data"       d="M368,190 C420,190 420,246 470,246"/>
    <path class="edge" id="e-act-retrieve_standards" d="M368,190 C420,190 420,313 470,313"/>

    <!-- tool -> data-source edges -->
    <path class="edge" id="e-be-get_network_kpis"   marker-end="url(#ah)" d="M660,45  C712,45  712,90  760,90"/>
    <path class="edge" id="e-be-get_alarms"         marker-end="url(#ah)" d="M660,112 C712,112 712,90  760,90"/>
    <path class="edge" id="e-be-get_cell_config"    marker-end="url(#ah)" d="M660,179 C712,179 712,90  760,90"/>
    <path class="edge" id="e-be-get_bss_data"       marker-end="url(#ah)" d="M660,246 C712,246 712,180 760,180"/>
    <path class="edge" id="e-be-retrieve_standards" marker-end="url(#ah)" d="M660,313 C712,313 712,270 760,270"/>

    <!-- phase pills -->
    <g class="pill" id="ph-think"><rect x="154" y="53" width="92" height="34" rx="9"/><text x="200" y="74">THINK</text></g>
    <g class="pill" id="ph-act"><rect x="274" y="173" width="92" height="34" rx="9"/><text x="320" y="194">ACT</text></g>
    <g class="pill" id="ph-observe"><rect x="150" y="293" width="100" height="34" rx="9"/><text x="200" y="314">OBSERVE</text></g>
    <g class="pill" id="ph-reflect"><rect x="30" y="173" width="100" height="34" rx="9"/><text x="80" y="194">REFLECT</text></g>
    <text id="loopRound" class="loopctr" x="200" y="187">round 0 / 10</text>
    <text class="loopcap" x="200" y="203">max 10</text>

    <!-- tool boxes -->
    <g class="tbox" id="tool-get_network_kpis"><rect x="470" y="22" width="190" height="46" rx="8"/><text class="tn" x="565" y="42">get_network_kpis</text><text class="sub" x="565" y="57">RSRP · SINR · PRB · DL</text></g>
    <g class="tbox" id="tool-get_alarms"><rect x="470" y="89" width="190" height="46" rx="8"/><text class="tn" x="565" y="109">get_alarms</text><text class="sub" x="565" y="124">active cell alarms</text></g>
    <g class="tbox" id="tool-get_cell_config"><rect x="470" y="156" width="190" height="46" rx="8"/><text class="tn" x="565" y="176">get_cell_config</text><text class="sub" x="565" y="191">RF · PCI</text></g>
    <g class="tbox" id="tool-get_bss_data"><rect x="470" y="223" width="190" height="46" rx="8"/><text class="tn" x="565" y="243">get_bss_data</text><text class="sub" x="565" y="258">subs · complaints · ARPU</text></g>
    <g class="tbox" id="tool-retrieve_standards"><rect x="470" y="290" width="190" height="46" rx="8"/><text class="tn" x="565" y="310">retrieve_standards</text><text class="sub" x="565" y="325">RAG over corpus</text></g>

    <!-- data-source (backend) boxes -->
    <g class="bbox" id="be-OSS"><rect x="760" y="63" width="180" height="54" rx="9"/><text class="bn" x="850" y="86">OSS / NMS</text><text class="sub" x="850" y="103">U2000 · ENM · PM counters</text></g>
    <g class="bbox" id="be-BSS"><rect x="760" y="153" width="180" height="54" rx="9"/><text class="bn" x="850" y="176">BSS / CRM</text><text class="sub" x="850" y="193">subscribers · billing</text></g>
    <g class="bbox" id="be-KB"><rect x="760" y="243" width="180" height="54" rx="9"/><text class="bn" x="850" y="266">Standards KB</text><text class="sub" x="850" y="283">3GPP · O-RAN · TM Forum</text></g>
  </svg>
  </div>
  <div class="muted" style="font-size:11px;margin-top:8px">The ring is the reasoning loop; each edge to the right is a live tool call
    reaching the OSS/BSS/standards sources. Nodes and edges light up as the agent runs.</div>
</div>

<div class="grid">
  <div class="card" id="tracecard">
    <h2>ReAct loop — live trace</h2>
    <div class="stream" id="stream"><div class="muted" style="font-size:12.5px">Pick a scenario and press “Run agent”.</div></div>
  </div>
  <div>
    <div class="card"><h2>Diagnosis &amp; safety gate</h2><div id="diag"><div class="muted" style="font-size:12.5px">—</div></div></div>
    <div class="card" style="margin-top:16px"><h2>Tool-call log</h2>
      <div style="overflow:auto"><table id="toollog"><thead><tr><th>#</th><th>Tool</th><th>Backend</th><th>Args</th><th>Result</th><th>ms</th></tr></thead><tbody></tbody></table></div></div>
    <div class="card" style="margin-top:16px"><h2>Trace — span waterfall <span class="muted" id="tracemeta"></span></h2>
      <div class="waterfall" id="waterfall"><div class="muted" style="font-size:12.5px">—</div></div></div>
  </div>
</div>

<div class="foot"><b>How to extend.</b> Tools live in the <span class="kbd">TOOLS</span> registry — point
<span class="kbd">get_network_kpis</span> / <span class="kbd">get_alarms</span> at your real U2000/ENM northbound
API and <span class="kbd">get_bss_data</span> at your BSS. The reasoning brain is the <span class="kbd">LLMBackend</span>: your served
<span class="kbd">OTel-LLM</span> endpoint on Databricks by default, with <span class="kbd">ClaudeLLM</span> (an API key)
and a deterministic <span class="kbd">MockLLM</span> as fallbacks — same contract. Spans export as OTel-shaped JSON for your observability stack.</div>
</div>

<script>
const SCEN = %%SCENARIOS%%;
const $ = s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const sel=$("#scen"); SCEN.forEach(s=>{const o=document.createElement("option");o.value=s.id;o.textContent=s.label;sel.appendChild(o)});
sel.addEventListener("change",()=>{$("#incident").placeholder=SCEN.find(x=>x.id===sel.value).incident});
$("#incident").placeholder=SCEN[0].incident;
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let lastResult=null;

function resetView(){
  $("#stream").innerHTML=""; $("#diag").innerHTML='<div class="muted" style="font-size:12.5px">—</div>';
  $("#toollog").querySelector("tbody").innerHTML=""; $("#waterfall").innerHTML="";
  $("#roundpill").textContent=""; $("#tracemeta").textContent="";
  $$(".pill").forEach(p=>p.classList.remove("on"));
  $$(".seg,.edge,.tbox,.bbox").forEach(e=>e.classList.remove("flow","act"));
  const lr=$("#loopRound"); if(lr) lr.textContent="round 0 / 10";
}
// which ring segment leads INTO each phase (so the traversed edge animates)
const ENTER={think:"seg-reflect-think",act:"seg-think-act",observe:"seg-act-observe",reflect:"seg-observe-reflect"};
function flowSeg(id){const s=document.getElementById(id);if(!s)return;s.classList.add("flow");setTimeout(()=>s.classList.remove("flow"),1000);}
function setPhase(name){
  $$(".pill").forEach(p=>p.classList.remove("on"));
  const p=document.getElementById("ph-"+name); if(p)p.classList.add("on");
  if(ENTER[name]) flowSeg(ENTER[name]);
}
function hitTool(tool,backend){
  const on=(id,t)=>{const el=document.getElementById(id);if(el){el.classList.add("act");setTimeout(()=>el.classList.remove("act"),t);}};
  on("e-act-"+tool,1200); on("tool-"+tool,1200); on("e-be-"+tool,1200); on("be-"+backend,1200);
}
let roundEl=null;
function ensureRound(n){
  roundEl=document.createElement("div"); roundEl.className="round";
  roundEl.innerHTML=`<div class="rh">Round ${n} / 10</div>`; $("#stream").appendChild(roundEl);
  $("#roundpill").textContent="· round "+n;
  const lr=$("#loopRound"); if(lr) lr.textContent="round "+n+" / 10";
  $("#stream").scrollTop=$("#stream").scrollHeight;
}
function addStep(cls,lab,html){
  const d=document.createElement("div"); d.className="step";
  d.innerHTML=`<span class="lab ${cls}">${lab}</span>${html}`;
  (roundEl||$("#stream")).appendChild(d); $("#stream").scrollTop=$("#stream").scrollHeight;
}

async function animate(res){
  let toolN=0;
  for(const e of res.events){
    if(e.t==="round"){ ensureRound(e.n); await sleep(150); }
    else if(e.t==="thought"){ setPhase("think"); addStep("think","THINK",escapeHtml(e.text)); await sleep(520); }
    else if(e.t==="action"){ setPhase("act"); hitTool(e.tool,e.backend);
      addStep("act","ACT",`call <code>${e.tool}(${escapeHtml(JSON.stringify(e.args))})</code> <span class="badge ${e.backend}">${e.backend}</span>`); await sleep(650); }
    else if(e.t==="observation"){ setPhase("observe"); addStep("obs","OBSERVE",escapeHtml(e.summary));
      addToolLog(++toolN,e,res.trace); await sleep(480); }
    else if(e.t==="reflection"){ setPhase("reflect");
      addStep("refl","REFLECT",escapeHtml(e.text)+(e.done?' <span class="muted">— sufficient evidence ✓</span>':"")); await sleep(460); }
    else if(e.t==="final"){ renderDiag(e); await sleep(120); }
    else if(e.t==="halt"){ addStep("refl","HALT","Reached max rounds ("+10+")."); }
  }
  renderWaterfall(res.trace);
  $("#dl").disabled=false; lastResult=res;
}
function addToolLog(i,e,trace){
  const sp=(trace.spans||[]).find(s=>s.name==="tool."+e.tool && s.attributes && JSON.stringify(s.attributes.args)===JSON.stringify(e.args));
  const ms=sp?sp.duration_ms:"";
  const tr=document.createElement("tr");
  tr.innerHTML=`<td>${i}</td><td class="mono">${e.tool}</td><td><span class="badge ${e.backend}">${e.backend}</span></td>
    <td class="mono">${escapeHtml(JSON.stringify(e.args))}</td><td>${escapeHtml(e.summary)}</td><td class="mono">${ms}</td>`;
  $("#toollog").querySelector("tbody").appendChild(tr);
}
function renderDiag(f){
  const congest=/congestion/i.test(f.hypothesis||"");
  const acts=(f.actions||[]).map(a=>`<li>${escapeHtml(a)}</li>`).join("");
  $("#diag").innerHTML=`<div class="diag ${congest?'congest':''}">
    <div class="h">${escapeHtml(f.hypothesis||"—")} <span class="muted" style="font-weight:500;font-size:11.5px">· confidence ${Math.round((f.confidence||0)*100)}%</span></div>
    <div class="r">${escapeHtml(f.reasoning||"")}</div>
    ${f.business_impact?`<div class="biz">💵 ${escapeHtml(f.business_impact)}</div>`:""}
    <div class="cites">Grounded in: <b>${(f.citations||[]).map(escapeHtml).join("</b>, <b>")}</b></div>
    <ol>${acts}</ol>
    <div class="gate"><div class="m">🛡 RECOMMEND — human approval required</div>
      <div class="muted" style="font-size:11.5px;margin-top:3px">The agent recommends; a network engineer signs off before any change is pushed to the live network.</div></div>
  </div>`;
}
function renderWaterfall(trace){
  const spans=(trace.spans||[]).slice().sort((a,b)=>a.start_ms-b.start_ms);
  if(!spans.length){return;}
  const max=Math.max(...spans.map(s=>s.end_ms));
  const depth={}; spans.forEach(s=>{depth[s.span_id]=s.parent_span_id?(depth[s.parent_span_id]||0)+1:0;});
  const cls=n=>n.startsWith("tool.")?"tool":n.startsWith("llm.")?"llm":n.startsWith("round.")?"round":n==="agent.run"?"root":"";
  $("#waterfall").innerHTML=spans.map(s=>{
    const left=(s.start_ms/max*100), w=Math.max(1.2,(s.duration_ms/max*100));
    const pad=(depth[s.span_id]||0)*10;
    return `<div class="spanrow"><div class="spanname" style="padding-left:${pad}px">${escapeHtml(s.name)}</div>
      <div class="spantrack"><div class="spanbar ${cls(s.name)}" style="left:${left}%;width:${w}%">${s.duration_ms}ms</div></div></div>`;
  }).join("");
  $("#tracemeta").textContent=`· ${spans.length} spans · trace ${trace.trace_id.slice(0,8)}`;
}
function escapeHtml(s){return (s==null?"":String(s)).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}

$("#run").addEventListener("click",async()=>{
  $("#run").disabled=true; $("#dl").disabled=true; $("#status").textContent="agent running…"; resetView();
  try{
    const r=await fetch("/run",{method:"POST",headers:{"content-type":"application/json"},
      body:JSON.stringify({scenario:sel.value, incident:$("#incident").value.trim()||null})});
    const res=await r.json();
    $("#status").textContent="engine: "+res.llm;
    await animate(res);
  }catch(err){ $("#status").textContent="error: "+err; }
  $("#run").disabled=false;
});
$("#dl").addEventListener("click",()=>{
  if(!lastResult)return;
  const blob=new Blob([JSON.stringify(lastResult.trace,null,2)],{type:"application/json"});
  const a=document.createElement("a"); a.href=URL.createObjectURL(blob);
  a.download="otel_trace_"+lastResult.trace.trace_id.slice(0,8)+".json"; a.click();
});
</script></body></html>"""


# =============================================================================
# 7. MAIN
# =============================================================================
def main():
    # Databricks Apps injects the port to bind via DATABRICKS_APP_PORT and expects the
    # server to listen on 0.0.0.0. Fall back to sensible local defaults otherwise.
    default_port = int(os.environ.get("DATABRICKS_APP_PORT", os.environ.get("PORT", 8000)))
    default_host = "0.0.0.0" if os.environ.get("DATABRICKS_APP_PORT") else "127.0.0.1"
    ap = argparse.ArgumentParser(description="OTel ReAct agent demo server")
    ap.add_argument("--host", default=default_host)
    ap.add_argument("--port", type=int, default=default_port)
    ap.add_argument("--selftest", action="store_true", help="run the loop in the terminal and exit")
    args = ap.parse_args()

    llm = make_llm()
    if args.selftest:
        for sid, sc in SCENARIOS.items():
            print(f"\n=== {sc['label']}  (engine: {llm.name}) ===")
            res = ReActAgent(make_llm()).run(sc)
            for e in res["events"]:
                if e["t"] == "thought": print(f"  THINK    {e['text']}")
                elif e["t"] == "action": print(f"  ACT      {e['tool']}({e['args']})  ->[{e['backend']}]")
                elif e["t"] == "observation": print(f"  OBSERVE  {e['summary']}")
                elif e["t"] == "reflection": print(f"  REFLECT  {e['text']}")
                elif e["t"] == "final": print(f"  FINAL    {e['hypothesis']}  ({int(e['confidence']*100)}%)")
            print(f"  spans collected: {len(res['trace']['spans'])}")
        return

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}"
    print("=" * 66)
    print("  OTel ReAct Agent — RAN/OSS-BSS troubleshooting demo")
    print(f"  reasoning engine : {llm.name}")
    print(f"  open in browser  : {url}")
    print("  (set ANTHROPIC_API_KEY and OTEL_LLM=claude to use Claude)")
    print("  Ctrl-C to stop")
    print("=" * 66)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()