import logging

from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from app.core.middleware import RequestLatencyMiddleware
from app.telemetry.base import LatencyTrackerPort
from app.telemetry.metrics import initialize_meter_provider
from app.telemetry.tracer import initialize_tracer_provider
from app.telemetry.config import build_telemetry_config
from app.core.config import Settings

logger = logging.getLogger(__name__)

def instrument_fastapi_app(app: FastAPI, latency_tracker: LatencyTrackerPort) -> None:
    """Register instrumentation middleware before app startup."""
    FastAPIInstrumentor.instrument_app(app)
    app.add_middleware(RequestLatencyMiddleware, latency_tracker=latency_tracker)


def initialize_telemetry(app: FastAPI, settings: Settings, latency_tracker: LatencyTrackerPort) -> None:
    """Initialize OpenTelemetry SDK providers during startup."""
    telemetry_config = build_telemetry_config(settings)
    initialize_tracer_provider(telemetry_config)
    initialize_meter_provider(telemetry_config)
