from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router as system_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.dependencies import get_latency_tracker
from app.telemetry.instrumentation import initialize_telemetry, instrument_fastapi_app

from monitoring.error_tracker import error_tracker
from monitoring.monitoring_views import router as monitoring_router

from hallucination.async_pipeline import hallucination_pipeline

from storage.trace_storage import trace_storage
from storage.trace_query_router import router as traces_router

from alerting.alert_engine import alert_engine
from alerting.alert_router import router as alerts_router
from alerting.latency_cost_rules import register_all_rules
from alerting.notification_channels import dispatcher

from sla.sla_router import router as sla_router
from root_cause.rca_router import router as rca_router
from runbooks.runbook_router import router as runbooks_router
from ab_testing.ab_router import router as ab_router

settings = get_settings()
configure_logging(settings.log_level)

# App must be created BEFORE lifespan so middleware can be added at module load time.
app = FastAPI(
    title="LLM Observability Platform",
    description=(
        "Production-grade monitoring for LangChain/LangGraph workloads. "
        "Includes alerts, SLA reporting, root-cause analysis, A/B testing, and runbooks."
    ),
    version="0.2.0",
)

# Instrument BEFORE app starts — middleware cannot be added after startup.
instrument_fastapi_app(app, get_latency_tracker())

# Core routes
app.include_router(system_router)
app.include_router(traces_router)
app.include_router(alerts_router)

# New feature routes
app.include_router(monitoring_router)
app.include_router(sla_router)
app.include_router(rca_router)
app.include_router(runbooks_router)
app.include_router(ab_router)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # initialize_telemetry sets up OTEL tracer/meter providers at startup.
    initialize_telemetry(app, settings, get_latency_tracker())

    await hallucination_pipeline.start()

    async def _patch_hallucination_result(result):
        trace_storage.update_hallucination(
            trace_id=result.trace_id,
            score=result.faithfulness_score,
            label=result.label,
        )

    hallucination_pipeline.register_callback(_patch_hallucination_result)
    register_all_rules(alert_engine)

    yield

    await hallucination_pipeline.shutdown()


app.router.lifespan_context = lifespan
