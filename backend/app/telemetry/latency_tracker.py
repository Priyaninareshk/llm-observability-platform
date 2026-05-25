import logging
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from math import floor

from app.core.config import Settings
from app.telemetry.base import LatencyTrackerPort, MetricsPort

logger = logging.getLogger(__name__)


@dataclass
class LatencyRecord:
    """Normalized latency payload for one operation stage."""

    operation: str
    duration_ms: float
    trace_id: str
    endpoint: str
    timestamp: str


@dataclass
class LatencyBreakdown:
    """Latency breakdown returned by API for a request lifecycle."""

    total_ms: float
    llm_ms: float
    callback_ms: float
    middleware_ms: float


class LatencyTracker(LatencyTrackerPort):
    """Latency tracker with metrics placeholders and percentile-ready buffering."""

    def __init__(self, metrics: MetricsPort, settings: Settings, rolling_window_size: int = 1000) -> None:
        self._metrics = metrics
        self._warning_threshold_ms = settings.latency_warning_threshold_ms
        self._rolling = deque(maxlen=rolling_window_size)

    def track(self, operation: str, duration_ms: float) -> None:
        self.track_stage(operation=operation, duration_ms=duration_ms, trace_id="", endpoint="")

    def track_stage(self, operation: str, duration_ms: float, trace_id: str, endpoint: str) -> LatencyRecord:
        """Track one latency stage for logs, traces, metrics, and rolling analytics."""
        record = LatencyRecord(
            operation=operation,
            duration_ms=duration_ms,
            trace_id=trace_id,
            endpoint=endpoint,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        self._rolling.append(duration_ms)

        self._metrics.observe("request_latency_ms", duration_ms, labels={"operation": operation, "endpoint": endpoint or "unknown"})
        labels = {"operation": operation, "endpoint": endpoint or "unknown"}
        values = list(self._rolling)
        avg = sum(values) / len(values) if values else duration_ms
        p50 = self._percentile(values, 50)
        p95 = self._percentile(values, 95)
        p99 = self._percentile(values, 99)
        self._metrics.set_gauge("avg_response_time", avg, labels=labels)
        self._metrics.set_gauge("p50_latency", p50, labels=labels)
        self._metrics.set_gauge("p95_latency", p95, labels=labels)
        self._metrics.set_gauge("p99_latency", p99, labels=labels)
        if operation == "llm_inference":
            self._metrics.observe("llm_latency_ms", duration_ms, labels={"endpoint": endpoint or "unknown"})

        logger.info("latency.stage", extra=asdict(record))
        if duration_ms > self._warning_threshold_ms:
            self._latency_warning_placeholder(record)
        return record

    def rolling_latency_values(self) -> list[float]:
        """Return rolling latency values for future percentile/SLA calculations."""
        return list(self._rolling)

    def _percentile(self, values: list[float], percentile: int) -> float:
        """Compute percentile from rolling values using nearest-rank interpolation."""
        if not values:
            return 0.0
        sorted_values = sorted(values)
        rank = (percentile / 100.0) * (len(sorted_values) - 1)
        low = floor(rank)
        high = min(low + 1, len(sorted_values) - 1)
        if low == high:
            return sorted_values[low]
        frac = rank - low
        return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * frac

    def _latency_warning_placeholder(self, record: LatencyRecord) -> None:
        """Placeholder alert hook for future AlertManager/SLA policy integration."""
        logger.warning(
            "latency.alert.placeholder",
            extra={
                "operation": record.operation,
                "duration_ms": record.duration_ms,
                "trace_id": record.trace_id,
                "endpoint": record.endpoint,
                "threshold_ms": self._warning_threshold_ms,
            },
        )
