from dataclasses import dataclass

from app.core.config import Settings


@dataclass(frozen=True)
class TelemetryConfig:
    """Normalized OpenTelemetry configuration used at runtime."""

    service_name: str
    otlp_endpoint: str
    otlp_insecure: bool


def build_telemetry_config(settings: Settings) -> TelemetryConfig:
    """Build telemetry config from app settings."""
    return TelemetryConfig(
        service_name=settings.otel_service_name,
        otlp_endpoint=settings.otel_exporter_otlp_endpoint,
        otlp_insecure=settings.otel_exporter_otlp_insecure,
    )
