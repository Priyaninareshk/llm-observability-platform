import time
import logging
import traceback
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from dataclasses import dataclass, field, asdict

logger = logging.getLogger("llm_observability.error_tracker")


@dataclass
class ErrorEvent:
    error_type: str
    error_message: str
    endpoint: str
    trace_id: Optional[str]
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    stack_trace: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ErrorRateTracker:
    """
    Tracks error rates using a sliding window per endpoint.
    Emits structured log events for each error and exposes
    aggregated metrics for Prometheus / the /metrics endpoint.
    """

    def __init__(self, window_seconds: int = 60):
        self.window_seconds = window_seconds
        # endpoint -> deque of (timestamp, error_type)
        self._windows: Dict[str, deque] = defaultdict(deque)
        self._total_requests: Dict[str, int] = defaultdict(int)
        self._error_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_request(self, endpoint: str) -> None:
        """Call at the start of every request."""
        self._total_requests[endpoint] += 1

    def record_error(
        self,
        error: Exception,
        endpoint: str,
        trace_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ErrorEvent:
        """Record an error event and return a structured ErrorEvent."""
        now = time.time()
        error_type = type(error).__name__
        stack = traceback.format_exc()

        event = ErrorEvent(
            error_type=error_type,
            error_message=str(error),
            endpoint=endpoint,
            trace_id=trace_id,
            stack_trace=stack,
            metadata=metadata or {},
        )

        # Sliding-window bucket
        self._windows[endpoint].append((now, error_type))
        self._error_counts[endpoint][error_type] += 1

        # Structured log
        logger.error(
            "llm.request.error",
            extra={
                "event": event.to_dict(),
                "error_rate_1m": self.error_rate(endpoint),
            },
        )

        return event

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def _purge_old(self, endpoint: str) -> None:
        cutoff = time.time() - self.window_seconds
        w = self._windows[endpoint]
        while w and w[0][0] < cutoff:
            w.popleft()

    def error_rate(self, endpoint: str) -> float:
        """Fraction of requests that errored in the last window."""
        self._purge_old(endpoint)
        total = self._total_requests.get(endpoint, 0)
        if total == 0:
            return 0.0
        return len(self._windows[endpoint]) / total

    def error_count_window(self, endpoint: str) -> int:
        """Number of errors in the sliding window."""
        self._purge_old(endpoint)
        return len(self._windows[endpoint])

    def get_metrics(self) -> Dict[str, Any]:
        """Return aggregated error metrics for all endpoints."""
        metrics = {}
        for endpoint in set(list(self._windows.keys()) + list(self._total_requests.keys())):
            self._purge_old(endpoint)
            metrics[endpoint] = {
                "total_requests": self._total_requests[endpoint],
                "errors_in_window": len(self._windows[endpoint]),
                "error_rate": self.error_rate(endpoint),
                "error_breakdown": dict(self._error_counts[endpoint]),
                "window_seconds": self.window_seconds,
            }
        return metrics

    def prometheus_text(self) -> str:
        """Emit Prometheus-compatible text for scraping."""
        lines = [
            "# HELP llm_error_rate Error rate per endpoint (sliding window)",
            "# TYPE llm_error_rate gauge",
        ]
        for endpoint, data in self.get_metrics().items():
            safe = endpoint.replace("/", "_").strip("_")
            lines.append(f'llm_error_rate{{endpoint="{endpoint}"}} {data["error_rate"]:.6f}')
            lines.append(f'llm_error_count_total{{endpoint="{endpoint}"}} {data["errors_in_window"]}')
        return "\n".join(lines)


# Singleton instance shared across the app
error_tracker = ErrorRateTracker(window_seconds=60)
