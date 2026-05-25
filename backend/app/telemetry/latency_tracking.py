import logging

from app.telemetry.base import LatencyTrackerPort
from app.telemetry.latency_tracker import LatencyRecord

logger = logging.getLogger(__name__)


class NoOpLatencyTracker(LatencyTrackerPort):
    """Starter latency tracker for US-07 integration readiness."""

    def track(self, operation: str, duration_ms: float) -> None:
        self.track_stage(operation, duration_ms, "", "")

    def track_stage(self, operation: str, duration_ms: float, trace_id: str, endpoint: str) -> LatencyRecord:
        record = LatencyRecord(
            operation=operation,
            duration_ms=duration_ms,
            trace_id=trace_id,
            endpoint=endpoint,
            timestamp="",
        )
        logger.debug(
            "Track latency (no-op)",
            extra={
                "operation": operation,
                "duration_ms": duration_ms,
            },
        )
        return record

    def rolling_latency_values(self) -> list[float]:
        return []
