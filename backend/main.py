from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router as system_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.dependencies import get_latency_tracker
from app.telemetry.instrumentation import initialize_telemetry, instrument_fastapi_app


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan hook.

    Keep startup logic centralized so future stories can initialize telemetry exporters,
    background tasks, and DB pools here.
    """
    settings = get_settings()
    configure_logging(settings.log_level)
    initialize_telemetry(app, settings, get_latency_tracker())
    yield


app = FastAPI(
    title="LLM Observability Platform",
    description="Production-grade monitoring foundation for LangChain/LangGraph workloads.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(system_router)
instrument_fastapi_app(app, get_latency_tracker())
