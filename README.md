# LLM Observability Platform

Production-grade monitoring and observability foundation for LangChain/LangGraph applications.

## Scope Implemented

- US-01: Project Setup
- US-02: Observability Platform Design
- US-03: OpenTelemetry SDK Integration
- US-04: LangSmith Callback Integration
- US-05: Token Usage Monitoring
- US-06: Cost Tracking System
- US-07: Latency Monitoring System

## Quick Start

1. Create and activate a virtual environment.
2. Install dependencies:
```bash
pip install -r backend/requirements.txt
```
3. Copy env file:
```powershell
Copy-Item backend/.env.example backend/.env
```
4. Run backend:
```bash
uvicorn main:app --reload --app-dir backend
```

## Endpoints

- `GET /`
- `GET /health`
- `GET /metrics`
- `GET /reports/cost`
- `GET /observability/langsmith`
- `POST /chat`

## Observability Variables

- `OTEL_SERVICE_NAME`
- `OTEL_EXPORTER_OTLP_ENDPOINT`
- `OTEL_EXPORTER_OTLP_INSECURE`
- `LANGCHAIN_API_KEY`
- `LANGCHAIN_TRACING_V2`
- `LANGCHAIN_PROJECT`
- `DEFAULT_LLM_MODEL`
- `COST_ALERT_THRESHOLD_USD`
- `MODEL_PRICING_JSON`
- `LATENCY_WARNING_THRESHOLD_MS`

## /chat Example

Request:
```json
{
  "prompt": "Hello"
}
```

Response shape:
```json
{
  "response": "Hello there...",
  "latency": {
    "total_ms": 123.4,
    "llm_ms": 98.0,
    "callback_ms": 12.0,
    "middleware_ms": 13.4
  },
  "token_usage": {
    "prompt_tokens": 20,
    "completion_tokens": 50,
    "total_tokens": 70,
    "model_name": "gpt-4o-mini",
    "timestamp": "2026-05-25T12:00:00+00:00",
    "request_id": "f4be...",
    "trace_id": "6d7a..."
  },
  "cost": {
    "prompt_cost": 0.000003,
    "completion_cost": 0.00003,
    "total_cost": 0.000033,
    "model_name": "gpt-4o-mini",
    "pricing_found": true
  },
  "trace_id": "6d7a..."
}
```

Example latency log:
```json
{
  "message": "chat.request.success",
  "trace_id": "6d7a...",
  "endpoint": "/chat",
  "latency_total_ms": 123.4,
  "latency_llm_ms": 98.0,
  "latency_callback_ms": 12.0,
  "latency_middleware_ms": 13.4
}
```

---

## Streamlit Frontend

A full observability dashboard built with Streamlit.

### Pages

| Page | Description |
|---|---|
| 📊 Dashboard | All-time stats, alert rules, error-rate chart, faithfulness gauge |
| 📡 Live Monitor | Real-time 5-min snapshot: requests, latency, cost, hallucinations |
| 📈 Historical Trends | Hourly charts for requests, errors, latency, cost, hallucinations |
| 🔍 Trace Explorer | Filterable table + detail view for every stored trace |
| 🧪 A/B Testing | Run parallel model comparisons and view experiment summaries |
| 📋 SLA Report | Compliance table against configured SLA targets |
| 📚 Runbooks | Browse operational runbooks by severity and category |
| 💬 Chat Playground | Send prompts to the backend with full observability metadata |

### Running

```bash
# 1. Install frontend deps
pip install -r frontend/requirements.txt

# 2. Run (assumes backend is on localhost:8000)
streamlit run frontend/app.py

# 3. Override backend URL
BACKEND_URL=http://my-backend:8000 streamlit run frontend/app.py
```

---

## Bug Fixes Applied

| # | File | Bug | Fix |
|---|---|---|---|
| 1 | `storage/trace_query_router.py` | `/search/hallucinated`, `/search/errors`, `/search/slow` were declared **after** `/{trace_id}`, so FastAPI matched them as trace-ID lookups and returned 404 | Moved all `/search/*` routes before `/{trace_id}` |
| 2 | `backend/requirements.txt` | `transformers` and `torch` were missing; the `NLIFaithfulnessScorer` imports them at runtime — their absence silently degraded hallucination scoring to the heuristic fallback with no install guidance | Added `transformers>=4.40.0` and `torch>=2.2.0` |
| 3 | `storage/trace_storage.py` | `count_traces()` fetched up to 10 000 rows into memory just to call `len()` | Replaced with a single `SELECT COUNT(*)` SQL query |
| 4 | `main.py` | `instrument_fastapi_app()` was called at module level **after** `app` creation but **before** `initialize_telemetry()` ran inside the lifespan, so FastAPI instrumentation attached before the OTEL providers were initialised | Moved both calls into lifespan, in correct order |
| 5 | `.env.example` | Only had a PostgreSQL `DATABASE_URL`; trace storage defaults to SQLite, confusing local dev setup | Added SQLite default with PostgreSQL as a commented option; documented all env vars |
