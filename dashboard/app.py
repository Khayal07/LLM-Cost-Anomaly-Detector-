"""Streamlit dashboard for the LLM Cost Anomaly Detector.

Reads everything over HTTP from the FastAPI service (``API_URL``): cost trends,
cost by model/endpoint, flagged incidents, and a per-incident drill-down showing
the request pattern that triggered it.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

import httpx
import pandas as pd
import streamlit as st

API_URL = os.environ.get("API_URL", "http://localhost:8000").rstrip("/")
API_KEY = os.environ.get("API_KEY") or None
_HEADERS = {"X-API-Key": API_KEY} if API_KEY else {}

st.set_page_config(page_title="LLM Cost Anomaly Detector", layout="wide")

RANGES = {
    "Last 1 hour": (1, "minute"),
    "Last 6 hours": (6, "minute"),
    "Last 24 hours": (24, "hour"),
    "Last 7 days": (24 * 7, "day"),
}

SEVERITY_ICON = {"high": "🔴", "medium": "🟠", "low": "🟡"}


def _get(path: str, params: dict | None = None):
    try:
        resp = httpx.get(f"{API_URL}{path}", params=params, headers=_HEADERS, timeout=10.0)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:  # noqa: BLE001 - surface API errors in the UI
        st.error(f"API request failed ({path}): {exc}")
        return None


# --- sidebar --------------------------------------------------------------
st.sidebar.title("⚙️ Controls")
range_label = st.sidebar.selectbox("Time range", list(RANGES), index=2)
hours, granularity = RANGES[range_label]
since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

auto = st.sidebar.checkbox("Auto-refresh", value=False)
interval = st.sidebar.slider("Refresh interval (s)", 5, 60, 15, disabled=not auto)
if st.sidebar.button("🔄 Refresh now"):
    st.rerun()
st.sidebar.caption(f"API: {API_URL}")

st.title("💸 LLM Cost Anomaly Detector")

# --- KPI row --------------------------------------------------------------
summary = _get("/stats/summary", {"since": since}) or {}
c1, c2, c3, c4 = st.columns(4)
c1.metric("Total cost", f"${summary.get('total_cost_usd', 0):.2f}")
c2.metric("Calls", f"{summary.get('total_calls', 0):,}")
c3.metric("Tokens", f"{summary.get('total_tokens', 0):,}")
c4.metric("Open incidents", summary.get("open_incidents", 0))

# --- cost over time -------------------------------------------------------
st.subheader("Cost over time")
series = _get("/stats/cost-over-time", {"granularity": granularity, "since": since})
if series:
    df = pd.DataFrame(series)
    df["bucket"] = pd.to_datetime(df["bucket"])
    st.line_chart(df.set_index("bucket")[["cost_usd"]])
else:
    st.info("No traffic in this window yet.")

# --- cost by model / endpoint --------------------------------------------
col_left, col_right = st.columns(2)
with col_left:
    st.subheader("Cost by model")
    data = _get("/stats/cost-by-model", {"since": since})
    if data:
        st.bar_chart(pd.DataFrame(data).set_index("key")[["cost_usd"]])
with col_right:
    st.subheader("Cost by endpoint")
    data = _get("/stats/cost-by-endpoint", {"since": since})
    if data:
        st.bar_chart(pd.DataFrame(data).set_index("key")[["cost_usd"]])

# --- incidents ------------------------------------------------------------
st.subheader("🚨 Flagged incidents")
incidents = _get("/incidents", {"since": since, "limit": 200}) or []
if not incidents:
    st.success("No incidents flagged in this window.")
else:
    table = pd.DataFrame(
        [
            {
                "id": i["id"],
                "detected_at": i["detected_at"],
                "type": i["type"],
                "severity": f"{SEVERITY_ICON.get(i['severity'], '')} {i['severity']}",
                "scope": f"{i['scope_type']}={i['scope_value']}",
                "score": i["score"],
                "status": i["status"],
                "message": i["message"],
            }
            for i in incidents
        ]
    )
    st.dataframe(table, use_container_width=True, hide_index=True)

    # --- drill-down -------------------------------------------------------
    st.subheader("🔍 Incident drill-down")
    chosen = st.selectbox(
        "Inspect incident",
        options=[i["id"] for i in incidents],
        format_func=lambda x: f"#{x} — "
        + next((i["type"] + " · " + i["message"][:60] for i in incidents if i["id"] == x), str(x)),
    )
    detail = _get(f"/incidents/{chosen}")
    if detail:
        inc = detail["incident"]
        left, right = st.columns([1, 2])
        with left:
            st.markdown(f"**Type:** {inc['type']}")
            st.markdown(f"**Severity:** {SEVERITY_ICON.get(inc['severity'], '')} {inc['severity']}")
            st.markdown(f"**Scope:** {inc['scope_type']} = `{inc['scope_value']}`")
            st.markdown(f"**Score:** {inc['score']}")
            st.markdown(f"**Detected:** {inc['detected_at']}")
            if inc.get("baseline"):
                st.caption("Baseline")
                st.json(inc["baseline"], expanded=False)
            if inc.get("observed"):
                st.caption("Observed")
                st.json(inc["observed"], expanded=False)
        with right:
            st.markdown("**Request pattern around the incident**")
            recs = detail.get("surrounding_records", [])
            if recs:
                rdf = pd.DataFrame(recs)
                rdf["ts"] = pd.to_datetime(rdf["ts"])
                st.line_chart(rdf.set_index("ts")[["tokens_in", "cost_usd"]])
                st.dataframe(
                    rdf[["ts", "model", "caller", "endpoint", "tokens_in", "cost_usd", "request_hash"]],
                    use_container_width=True,
                    hide_index=True,
                )

if auto:
    time.sleep(interval)
    st.rerun()
