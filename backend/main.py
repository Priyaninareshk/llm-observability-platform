from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router as system_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.dependencies import get_latency_tracker
from app.telemetry.instrumentation import initialize_telemetry, instrument_fastapi_app


from monitoring.error_tracker import error_tracker

from hallucination.async_pipeline import hallucination_pipeline

from storage.trace_storage import trace_storage

from storage.trace_query_router import router as traces_router


from alerting.alert_engine import alert_engine
from alerting.alert_router import router as alerts_router
from alerting.latency_cost_rules import register_all_rules
from alerting.notification_channels import dispatcher


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan hook.

    Startup:
      - Configure logging and telemetry (existing)
      - Start async hallucination pipeline workers (US-10)
      - Register hallucination result callback → patches trace storage (US-11)
      - Register all pre-built alert rules for latency, cost, errors, hallucination (US-15)

    Shutdown:
      - Drain hallucination queue gracefully (US-10)
    """
    settings = get_settings()
    configure_logging(settings.log_level)
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


app = FastAPI(
    title="LLM Observability Platform",
    description="Production-grade monitoring foundation for LangChain/LangGraph workloads.",
    version="0.1.0",
    lifespan=lifespan,
)


app.include_router(system_router)


app.include_router(traces_router)


app.include_router(alerts_router)

instrument_fastapi_app(app, get_latency_tracker())
