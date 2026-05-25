# Setup Instructions

## Prerequisites
- Python 3.11+
- Docker + Docker Compose (optional for container workflow)

## Local Backend Setup

1. Create virtual environment.
2. Install dependencies:
   `pip install -r backend/requirements.txt`
3. Create environment file:
   - Linux/macOS: `cp backend/.env.example backend/.env`
   - Windows PowerShell: `Copy-Item backend/.env.example backend/.env`
4. Start API:
   `uvicorn main:app --reload --app-dir backend`
5. Validate:
   - `http://localhost:8000/`
   - `http://localhost:8000/health`

## Docker Setup

1. From repository root:
   `docker compose up --build`
2. Verify services:
   - Backend: `http://localhost:8000`
   - Prometheus: `http://localhost:9090`

## Environment Variables

- `OPENAI_API_KEY`: API key for future model integrations.
- `DATABASE_URL`: DSN for trace/cost/usage storage backend.
- `OTEL_SERVICE_NAME`: OpenTelemetry logical service name.
- `OTEL_EXPORTER_OTLP_ENDPOINT`: OTLP endpoint for traces.
- `OTEL_EXPORTER_OTLP_INSECURE`: Insecure OTLP transport for local setup.
- `PROMETHEUS_PORT`: Port for Prometheus metrics exposure.
- `LOG_LEVEL`: Logging verbosity (`INFO` default).
- `LANGCHAIN_API_KEY`: LangSmith API key.
- `LANGCHAIN_TRACING_V2`: Enable LangSmith tracing v2.
- `LANGCHAIN_PROJECT`: LangSmith project name.
- `DEFAULT_LLM_MODEL`: Default model used by `/chat`.
- `COST_ALERT_THRESHOLD_USD`: Cost warning threshold for placeholder alert hook.
- `MODEL_PRICING_JSON`: Optional JSON pricing overrides by model.
- `LATENCY_WARNING_THRESHOLD_MS`: Warning threshold for high-latency placeholder alerts.
