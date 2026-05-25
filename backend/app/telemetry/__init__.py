"""Telemetry abstractions and adapters for observability services.

Primary implementations for US-03..US-07:
- `OpenTelemetryTracer`
- `OpenTelemetryMetricsCollector`
- `TokenUsageTracker`
- `CostTracker`
- `LatencyTracker`

Legacy `*_tracking.py` no-op adapters remain for backward compatibility only.
"""

from app.telemetry.base import (
    CostTrackerPort,
    LatencyTrackerPort,
    MetricsPort,
    TokenTrackerPort,
    TracerPort,
)
from app.telemetry.cost_tracking import NoOpCostTracker
from app.telemetry.cost_tracker import CostTracker
from app.telemetry.latency_tracking import NoOpLatencyTracker
from app.telemetry.latency_tracker import LatencyTracker, LatencyBreakdown, LatencyRecord
from app.telemetry.metrics import NoOpMetricsCollector, OpenTelemetryMetricsCollector
from app.telemetry.token_tracking import NoOpTokenTracker
from app.telemetry.token_tracker import TokenUsageTracker
from app.telemetry.tracing import NoOpTracer
from app.telemetry.tracer import OpenTelemetryTracer

__all__ = [
    "TracerPort",
    "MetricsPort",
    "TokenTrackerPort",
    "CostTrackerPort",
    "LatencyTrackerPort",
    "NoOpTracer",
    "OpenTelemetryTracer",
    "OpenTelemetryMetricsCollector",
    "TokenUsageTracker",
    "CostTracker",
    "LatencyTracker",
    "LatencyRecord",
    "LatencyBreakdown",
    "NoOpTracer",
    "NoOpMetricsCollector",
    "NoOpTokenTracker",
    "NoOpCostTracker",
    "NoOpLatencyTracker",
]
