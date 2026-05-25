# Developer Onboarding Notes

## Welcome

This repository is structured to support incremental delivery of enterprise observability features.
US-01 and US-02 establish the foundation only.

## Where to Start

- API entrypoint: `backend/main.py`
- API routes: `backend/app/api/routes.py`
- Config and env loading: `backend/app/core/config.py`
- Logging bootstrap: `backend/app/core/logging.py`
- Telemetry contracts: `backend/app/telemetry/base.py`
- DI providers: `backend/app/dependencies.py`

## Development Principles

- Keep business logic in `services/` as stories expand.
- Keep API route handlers thin and orchestration-focused.
- Depend on telemetry interfaces (ports), not concrete adapters.
- Add adapter implementations without changing API/business code.

## Telemetry Extension Path

1. Add OpenTelemetry tracer adapter implementing `TracerPort`.
2. Add Prometheus adapter implementing `MetricsPort`.
3. Add LangSmith callback bridge inside telemetry/service layer.
4. Add storage repositories under `database/` for trace and cost data.

## Dependency Injection Pattern

Use providers from `app/dependencies.py` in FastAPI dependencies.
This allows controlled replacement in tests and environment-specific wiring.

## Testing Guidance (Starter)

- Add API tests under `tests/` for root and health endpoints.
- Add unit tests for telemetry adapters as they are introduced.
- Mock telemetry ports when testing service logic.

## Collaboration Notes

- Keep modules small and responsibility-focused.
- Prefer explicit type hints and docstrings.
- Update `docs/architecture.md` when major architecture decisions change.
