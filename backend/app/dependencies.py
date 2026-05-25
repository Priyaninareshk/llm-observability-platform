from functools import lru_cache

from app.telemetry import (
    OpenTelemetryMetricsCollector,
    OpenTelemetryTracer,
)
from app.core.config import Settings, get_settings
from app.core.pricing import load_model_pricing
from app.services.llm_service import LLMService
from app.telemetry.cost_tracker import CostTracker
from app.telemetry.base import CostTrackerPort, LatencyTrackerPort, MetricsPort, TokenTrackerPort, TracerPort
from app.telemetry.latency_tracker import LatencyTracker
from app.telemetry.token_tracker import TokenUsageTracker


@lru_cache(maxsize=1)
def get_tracer() -> TracerPort:
    """Dependency-injected tracer provider."""
    return OpenTelemetryTracer()


@lru_cache(maxsize=1)
def get_metrics_collector() -> MetricsPort:
    """Dependency-injected metrics provider."""
    return OpenTelemetryMetricsCollector()


@lru_cache(maxsize=1)
def get_token_tracker() -> TokenTrackerPort:
    """Dependency-injected token tracking provider."""
    return TokenUsageTracker(metrics=get_metrics_collector())


@lru_cache(maxsize=1)
def get_cost_tracker() -> CostTrackerPort:
    """Dependency-injected cost tracking provider."""
    settings = get_settings()
    return CostTracker(
        metrics=get_metrics_collector(),
        pricing_by_model=load_model_pricing(settings),
        alert_threshold_usd=settings.cost_alert_threshold_usd,
    )


@lru_cache(maxsize=1)
def get_latency_tracker() -> LatencyTrackerPort:
    """Dependency-injected latency tracking provider."""
    settings = get_settings()
    return LatencyTracker(metrics=get_metrics_collector(), settings=settings)


@lru_cache(maxsize=1)
def get_llm_service() -> LLMService:
    """Dependency-injected LLM service with observability adapters."""
    settings: Settings = get_settings()
    return LLMService(
        settings=settings,
        tracer=get_tracer(),
        metrics=get_metrics_collector(),
        token_tracker=get_token_tracker(),
        cost_tracker=get_cost_tracker(),
        latency_tracker=get_latency_tracker(),
    )
