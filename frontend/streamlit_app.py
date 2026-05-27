"""
LLM Observability Platform — Streamlit Frontend
================================================
Run:  streamlit run frontend/app.py
Env:  BACKEND_URL (default: http://localhost:8000)
"""

import os
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import requests
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# ── Config ───────────────────────────────────────────────────────────────────

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")
PAGE_TITLE  = "LLM Observability Platform"
REFRESH_SEC = 30   # auto-refresh interval for live view

st.set_page_config(
    page_title=PAGE_TITLE,
    page_icon="🔭",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _get(path: str, params: Optional[Dict] = None, timeout: int = 10) -> Optional[Any]:
    try:
        r = requests.get(f"{BACKEND_URL}{path}", params=params, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.ConnectionError:
        st.error(f"⚠️ Cannot reach backend at **{BACKEND_URL}**. Is the server running?")
        return None
    except requests.exceptions.HTTPError as e:
        st.error(f"Backend error: {e}")
        return None
    except Exception as e:
        st.error(f"Unexpected error: {e}")
        return None


def _post(path: str, json: Dict, timeout: int = 30) -> Optional[Any]:
    try:
        r = requests.post(f"{BACKEND_URL}{path}", json=json, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.ConnectionError:
        st.error(f"⚠️ Cannot reach backend at **{BACKEND_URL}**.")
        return None
    except requests.exceptions.HTTPError as e:
        st.error(f"Backend error: {e.response.text}")
        return None
    except Exception as e:
        st.error(f"Unexpected error: {e}")
        return None


def fmt_ms(v: Optional[float]) -> str:
    if v is None:
        return "—"
    return f"{v:,.1f} ms"


def fmt_usd(v: Optional[float]) -> str:
    if v is None:
        return "—"
    return f"${v:.6f}"


def fmt_pct(v: Optional[float]) -> str:
    if v is None:
        return "—"
    return f"{v * 100:.2f}%"


def label_badge(label: str) -> str:
    colors = {"faithful": "🟢", "uncertain": "🟡", "hallucinated": "🔴"}
    return colors.get(label, "⚪") + " " + label


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("🔭 LLM Observability")
    st.caption(f"Backend: `{BACKEND_URL}`")
    st.divider()

    page = st.radio(
        "Navigation",
        [
            "📊 Dashboard",
            "📡 Live Monitor",
            "📈 Historical Trends",
            "🔍 Trace Explorer",
            "🧪 A/B Testing",
            "📋 SLA Report",
            "📚 Runbooks",
            "💬 Chat Playground",
        ],
        label_visibility="collapsed",
    )

    st.divider()
    health = _get("/health")
    if health:
        st.success("✅ Backend healthy")
    else:
        st.error("❌ Backend offline")

# ── Page: Dashboard ───────────────────────────────────────────────────────────

if page == "📊 Dashboard":
    st.title("📊 Dashboard")

    summary = _get("/monitoring/summary")
    stats   = _get("/traces/stats")

    if summary and stats:
        at = summary.get("all_time", {})
        et = summary.get("error_tracker", {})

        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("Total Traces",     f"{at.get('total_traces', 0):,}")
        col2.metric("Avg Latency",       fmt_ms(at.get("avg_latency_ms")))
        col3.metric("Total Cost",        f"${at.get('total_cost_usd', 0):.4f}")
        col4.metric("Total Tokens",      f"{at.get('total_tokens', 0):,}")
        col5.metric("Total Errors",      f"{at.get('total_errors', 0):,}")

        st.divider()

        col_a, col_b = st.columns(2)

        with col_a:
            st.subheader("Alert Rules")
            alerts_info = summary.get("alerts", {})
            st.metric("Active Rules", alerts_info.get("rules_count", 0))
            recent = alerts_info.get("recent", [])
            if recent:
                st.dataframe(
                    pd.DataFrame(recent),
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("No recent alerts fired.")

        with col_b:
            st.subheader("Error Rate by Endpoint")
            if et:
                rows = [
                    {
                        "endpoint": ep,
                        "total_requests": v.get("total_requests", 0),
                        "error_rate": v.get("error_rate", 0),
                        "errors_in_window": v.get("errors_in_window", 0),
                    }
                    for ep, v in et.items()
                ]
                df = pd.DataFrame(rows)
                fig = px.bar(
                    df,
                    x="endpoint",
                    y="error_rate",
                    color="error_rate",
                    color_continuous_scale="RdYlGn_r",
                    labels={"error_rate": "Error Rate", "endpoint": "Endpoint"},
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No endpoint data yet.")

        st.subheader("Avg Faithfulness Score")
        avg_faith = at.get("avg_faithfulness_score", 0)
        fig_gauge = go.Figure(go.Indicator(
            mode="gauge+number",
            value=avg_faith,
            number={"suffix": "", "valueformat": ".3f"},
            gauge={
                "axis": {"range": [0, 1]},
                "bar": {"color": "#2ecc71" if avg_faith >= 0.7 else "#e74c3c"},
                "steps": [
                    {"range": [0, 0.4], "color": "#fadbd8"},
                    {"range": [0.4, 0.7], "color": "#fef9e7"},
                    {"range": [0.7, 1.0], "color": "#d5f5e3"},
                ],
                "threshold": {"line": {"color": "red", "width": 4}, "thickness": 0.75, "value": 0.4},
            },
            title={"text": "Average Faithfulness"},
        ))
        fig_gauge.update_layout(height=280)
        st.plotly_chart(fig_gauge, use_container_width=True)

# ── Page: Live Monitor ────────────────────────────────────────────────────────

elif page == "📡 Live Monitor":
    st.title("📡 Live Monitor")
    st.caption(f"Auto-refreshes every {REFRESH_SEC}s. Last fetch: {datetime.now().strftime('%H:%M:%S')}")

    live = _get("/monitoring/live")
    if live:
        req  = live.get("requests", {})
        lat  = live.get("latency", {})
        cost = live.get("cost", {})
        hal  = live.get("hallucination", {})
        alts = live.get("alerts", {})
        hr   = live.get("hour_summary", {})

        st.subheader("Last 5 Minutes")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Requests",       req.get("total", 0))
        c2.metric("Errors",         req.get("errors", 0), delta=f"{req.get('error_rate', 0)*100:.1f}% rate", delta_color="inverse")
        c3.metric("Avg Latency",    fmt_ms(lat.get("avg_ms")))
        c4.metric("Cost (5m)",      fmt_usd(cost.get("total_usd")))

        c5, c6, c7, c8 = st.columns(4)
        c5.metric("Req/min",        req.get("requests_per_minute", 0))
        c6.metric("Hallucinated",   hal.get("hallucinated_count", 0))
        c7.metric("Hal Rate",       fmt_pct(hal.get("hallucination_rate")))
        c8.metric("Alerts Fired",   alts.get("recent_fired", 0))

        st.divider()
        st.subheader("Last Hour Summary")
        h1, h2, h3 = st.columns(3)
        h1.metric("Total Requests", hr.get("total_requests", 0))
        h2.metric("Total Errors",   hr.get("total_errors", 0))
        h3.metric("Total Cost",     fmt_usd(hr.get("total_cost_usd")))

        last_alert = alts.get("last_alert")
        if last_alert:
            st.subheader("Last Alert")
            st.json(last_alert)

    # Auto-refresh
    time.sleep(0.1)
    if st.button("🔄 Refresh Now"):
        st.rerun()

# ── Page: Historical Trends ───────────────────────────────────────────────────

elif page == "📈 Historical Trends":
    st.title("📈 Historical Trends")

    hours = st.slider("Lookback window (hours)", 1, 168, 24)
    hist  = _get("/monitoring/history", params={"hours": hours})

    if hist:
        buckets = hist.get("buckets", [])
        if buckets:
            df = pd.DataFrame(buckets)
            df["timestamp"] = pd.to_datetime(df["timestamp"])

            tab1, tab2, tab3, tab4 = st.tabs(["Requests & Errors", "Latency", "Cost & Tokens", "Hallucinations"])

            with tab1:
                fig = px.line(df, x="timestamp", y=["request_count", "error_count"],
                              labels={"value": "Count", "variable": "Metric"},
                              title="Request & Error Counts Over Time")
                st.plotly_chart(fig, use_container_width=True)

                fig2 = px.bar(df, x="timestamp", y="error_rate",
                              title="Error Rate Over Time",
                              color="error_rate", color_continuous_scale="RdYlGn_r")
                st.plotly_chart(fig2, use_container_width=True)

            with tab2:
                fig = px.line(df, x="timestamp", y="avg_latency_ms",
                              title="Average Latency (ms) Over Time",
                              labels={"avg_latency_ms": "Avg Latency (ms)"})
                st.plotly_chart(fig, use_container_width=True)

            with tab3:
                fig = px.area(df, x="timestamp", y="total_cost_usd",
                              title="Total Cost (USD) Over Time",
                              labels={"total_cost_usd": "Cost (USD)"})
                st.plotly_chart(fig, use_container_width=True)

                fig2 = px.bar(df, x="timestamp", y="total_tokens",
                              title="Token Usage Over Time",
                              labels={"total_tokens": "Tokens"})
                st.plotly_chart(fig2, use_container_width=True)

            with tab4:
                fig = px.bar(df, x="timestamp", y="hallucinated_count",
                             title="Hallucinated Response Count Over Time",
                             color="hallucinated_count", color_continuous_scale="Reds")
                st.plotly_chart(fig, use_container_width=True)

            st.caption(f"Period: {hist.get('period_hours')}h | Total traces: {hist.get('total_traces'):,}")
        else:
            st.info("No trace data found for this period.")

# ── Page: Trace Explorer ──────────────────────────────────────────────────────

elif page == "🔍 Trace Explorer":
    st.title("🔍 Trace Explorer")

    with st.expander("🔎 Filters", expanded=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            search_text    = st.text_input("Search prompt/response")
            model_name     = st.text_input("Model name")
        with col2:
            faith_label    = st.selectbox("Faithfulness", ["", "faithful", "uncertain", "hallucinated"])
            has_error      = st.selectbox("Has error", ["", "yes", "no"])
        with col3:
            min_lat        = st.number_input("Min latency (ms)", min_value=0.0, value=0.0)
            max_lat        = st.number_input("Max latency (ms)", min_value=0.0, value=0.0)
        limit = st.slider("Max results", 10, 500, 50)

    params: Dict[str, Any] = {"limit": limit}
    if search_text:   params["search"]            = search_text
    if model_name:    params["model_name"]         = model_name
    if faith_label:   params["faithfulness_label"] = faith_label
    if has_error == "yes": params["has_error"]     = True
    if has_error == "no":  params["has_error"]     = False
    if min_lat > 0:   params["min_latency_ms"]     = min_lat
    if max_lat > 0:   params["max_latency_ms"]     = max_lat

    data = _get("/traces", params=params)
    if data:
        traces = data.get("traces", [])
        st.caption(f"Showing {len(traces)} of {data.get('total', 0)} traces")

        if traces:
            cols_to_show = [
                "trace_id", "model_name", "latency_total_ms", "total_cost",
                "total_tokens", "faithfulness_label", "faithfulness_score",
                "error_type", "created_at",
            ]
            df = pd.DataFrame(traces)
            # Keep only columns that exist
            show_cols = [c for c in cols_to_show if c in df.columns]
            df_display = df[show_cols].copy()
            if "faithfulness_label" in df_display.columns:
                df_display["faithfulness_label"] = df_display["faithfulness_label"].apply(
                    lambda x: label_badge(x) if x else "⚪ unscored"
                )

            st.dataframe(df_display, use_container_width=True, hide_index=True)

            # Detail view
            trace_ids = [t["trace_id"] for t in traces]
            selected_id = st.selectbox("Inspect trace", [""] + trace_ids)
            if selected_id:
                detail = _get(f"/traces/{selected_id}")
                if detail:
                    c1, c2 = st.columns(2)
                    with c1:
                        st.subheader("Prompt")
                        st.text_area("", detail.get("prompt", ""), height=150, disabled=True)
                    with c2:
                        st.subheader("Response")
                        st.text_area("", detail.get("response", ""), height=150, disabled=True)

                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Latency",    fmt_ms(detail.get("latency_total_ms")))
                    m2.metric("Cost",       fmt_usd(detail.get("total_cost")))
                    m3.metric("Tokens",     detail.get("total_tokens", 0))
                    m4.metric("Faithfulness", label_badge(detail.get("faithfulness_label") or "unscored"))

                    with st.expander("Full JSON"):
                        st.json(detail)
        else:
            st.info("No traces match the current filters.")

# ── Page: A/B Testing ─────────────────────────────────────────────────────────

elif page == "🧪 A/B Testing":
    st.title("🧪 A/B Testing")

    tab1, tab2 = st.tabs(["Run Comparison", "Experiment History"])

    with tab1:
        st.subheader("Run A/B Comparison")
        prompt       = st.text_area("Prompt", height=120)
        col1, col2, col3 = st.columns(3)
        control      = col1.text_input("Control model",   "gpt-4o-mini")
        treatment    = col2.text_input("Treatment model", "gpt-4o")
        exp_name     = col3.text_input("Experiment name", "default")

        if st.button("▶️ Run Comparison", disabled=not prompt):
            with st.spinner("Running both models in parallel…"):
                result = _post("/ab/compare", json={
                    "prompt": prompt,
                    "control_model": control,
                    "treatment_model": treatment,
                    "experiment_name": exp_name,
                })
            if result:
                winner = result.get("winner", "unknown")
                st.success(f"🏆 Winner: **{winner}**")

                c1, c2 = st.columns(2)
                for col, key, label in [(c1, "control", f"Control ({control})"), (c2, "treatment", f"Treatment ({treatment})")]:
                    v = result.get(key, {})
                    with col:
                        st.subheader(label)
                        st.metric("Latency",  fmt_ms(v.get("latency_ms")))
                        st.metric("Cost",     fmt_usd(v.get("cost_usd")))
                        st.metric("Tokens",   v.get("total_tokens", 0))
                        st.text_area("Response", v.get("response", ""), height=150, disabled=True, key=key)

                with st.expander("Raw result"):
                    st.json(result)

    with tab2:
        exps = _get("/ab/experiments")
        if exps:
            exp_list = exps.get("experiments", [])
            if exp_list:
                selected_exp = st.selectbox("Experiment", exp_list)
                summary = _get(f"/ab/experiments/{selected_exp}/summary")
                if summary:
                    st.json(summary)
            else:
                st.info("No experiments recorded yet.")

        history = _get("/ab/history", params={"limit": 20})
        if history:
            records = history.get("records", [])
            if records:
                st.subheader("Recent A/B Records")
                st.dataframe(pd.DataFrame(records), use_container_width=True, hide_index=True)

# ── Page: SLA Report ──────────────────────────────────────────────────────────

elif page == "📋 SLA Report":
    st.title("📋 SLA Report")

    period = st.slider("Lookback (hours)", 1, 720, 24)
    targets = _get("/sla/targets")
    report  = _get("/sla/report", params={"period_hours": period})

    if targets:
        st.subheader("SLA Targets")
        t1, t2, t3 = st.columns(3)
        t1.metric("Availability",       f"{targets.get('availability_pct', 0)}%")
        t2.metric("P95 Latency target", fmt_ms(targets.get("p95_latency_ms")))
        t3.metric("Daily Budget",       f"${targets.get('daily_cost_budget_usd', 0):.2f}")
        t4, t5, t6 = st.columns(3)
        t4.metric("Max Error Rate",     fmt_pct(targets.get("error_rate_max")))
        t5.metric("Max Hallucination",  fmt_pct(targets.get("hallucination_rate_max")))
        t6.metric("P99 Latency target", fmt_ms(targets.get("p99_latency_ms")))

    if report:
        st.divider()
        st.subheader("Compliance Summary")

        compliance = report.get("compliance", {})
        if compliance:
            rows = []
            for metric, data in compliance.items():
                if isinstance(data, dict):
                    rows.append({
                        "Metric":     metric,
                        "Compliant":  "✅" if data.get("compliant") else "❌",
                        "Actual":     str(data.get("actual", "—")),
                        "Target":     str(data.get("target", "—")),
                    })
            if rows:
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        with st.expander("Full Report JSON"):
            st.json(report)

# ── Page: Runbooks ────────────────────────────────────────────────────────────

elif page == "📚 Runbooks":
    st.title("📚 Runbooks")

    col1, col2 = st.columns(2)
    severity = col1.selectbox("Filter by severity", ["", "info", "warning", "critical"])
    category = col2.selectbox("Filter by category", ["", "latency", "errors", "hallucination", "cost"])

    params: Dict[str, Any] = {}
    if severity: params["severity"] = severity
    if category: params["category"] = category

    rbs = _get("/runbooks", params=params)
    if rbs:
        books = rbs.get("runbooks", [])
        if books:
            for rb in books:
                rule_id  = rb.get("rule_id", "unknown")
                title    = rb.get("title", rule_id)
                sev      = rb.get("severity", "")
                cat      = rb.get("category", "")
                sev_icon = {"critical": "🔴", "warning": "🟡", "info": "🔵"}.get(sev, "⚪")
                with st.expander(f"{sev_icon} **{title}** — `{rule_id}` [{cat}]"):
                    detail = _get(f"/runbooks/{rule_id}")
                    if detail:
                        if detail.get("description"):
                            st.write(detail["description"])
                        if detail.get("triage_steps"):
                            st.subheader("Triage Steps")
                            for step in detail["triage_steps"]:
                                st.markdown(f"- {step}")
                        if detail.get("escalation"):
                            st.subheader("Escalation Path")
                            st.write(detail["escalation"])
                        with st.expander("Full JSON"):
                            st.json(detail)
        else:
            st.info("No runbooks match the current filters.")

# ── Page: Chat Playground ─────────────────────────────────────────────────────

elif page == "💬 Chat Playground":
    st.title("💬 Chat Playground")
    st.caption("Send prompts directly to the backend and see full observability metadata.")

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    # Display history
    for item in st.session_state.chat_history:
        with st.chat_message("user"):
            st.write(item["prompt"])
        with st.chat_message("assistant"):
            st.write(item["response"])
            with st.expander("📊 Observability Metadata"):
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Latency",   fmt_ms(item.get("latency_total_ms")))
                c2.metric("Tokens",    item.get("total_tokens", 0))
                c3.metric("Cost",      fmt_usd(item.get("total_cost")))
                c4.metric("Trace ID",  item.get("trace_id", "—")[:8] + "…" if item.get("trace_id") else "—")

    prompt = st.chat_input("Enter your prompt…")
    if prompt:
        with st.chat_message("user"):
            st.write(prompt)

        with st.spinner("Calling LLM…"):
            result = _post("/chat", json={"prompt": prompt})

        if result:
            resp = result.get("response", "")
            lat  = result.get("latency", {})
            tok  = result.get("token_usage", {})
            cost = result.get("cost", {})

            with st.chat_message("assistant"):
                st.write(resp)
                with st.expander("📊 Observability Metadata"):
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Latency",   fmt_ms(lat.get("total_ms")))
                    c2.metric("Tokens",    tok.get("total_tokens", 0))
                    c3.metric("Cost",      fmt_usd(cost.get("total_cost")))
                    c4.metric("Trace ID",  (result.get("trace_id") or "—")[:8] + "…")

            st.session_state.chat_history.append({
                "prompt":           prompt,
                "response":         resp,
                "latency_total_ms": lat.get("total_ms"),
                "total_tokens":     tok.get("total_tokens"),
                "total_cost":       cost.get("total_cost"),
                "trace_id":         result.get("trace_id"),
            })

        if st.button("🗑️ Clear History"):
            st.session_state.chat_history = []
            st.rerun()
