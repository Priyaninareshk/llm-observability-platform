import logging
from collections.abc import Mapping
from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

from app.telemetry.base import TracerPort
from app.telemetry.config import TelemetryConfig

logger = logging.getLogger(__name__)


class OpenTelemetryTracer(TracerPort):
    """TracerPort adapter backed by OpenTelemetry SDK."""

    def __init__(self, tracer_name: str = "app.telemetry") -> None:
        self._tracer = trace.get_tracer(tracer_name)

    def start_span(self, name: str, attributes: Mapping[str, Any] | None = None) -> Any:
        span = self._tracer.start_span(name=name)
        for key, value in (attributes or {}).items():
            span.set_attribute(key, value)
        return span

    def end_span(self, span: Any) -> None:
        span.end()


def initialize_tracer_provider(config: TelemetryConfig) -> None:
    """Initialize process-wide tracer provider and span export pipeline."""
    resource = Resource.create({"service.name": config.service_name})
    provider = TracerProvider(resource=resource)

    if config.otlp_endpoint:
        exporter = OTLPSpanExporter(endpoint=config.otlp_endpoint, insecure=config.otlp_insecure)
        logger.info("OpenTelemetry OTLP exporter configured", extra={"endpoint": config.otlp_endpoint})
    else:
        exporter = ConsoleSpanExporter()
        logger.info("OpenTelemetry console exporter enabled (no OTLP endpoint configured)")

    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
