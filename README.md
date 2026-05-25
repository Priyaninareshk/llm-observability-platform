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
