from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import Settings
from app.telemetry.base import MetricsPort
from app.telemetry.latency_tracker import LatencyTracker


class InMemoryMetrics(MetricsPort):
    def __init__(self) -> None:
        self.gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}

    def increment(self, name: str, value: float = 1.0, labels=None) -> None:
        return None

    def observe(self, name: str, value: float, labels=None) -> None:
        return None

    def set_gauge(self, name: str, value: float, labels=None) -> None:
        key = (name, tuple(sorted((labels or {}).items())))
        self.gauges[key] = value


def _gauge(metrics: InMemoryMetrics, name: str, operation: str, endpoint: str) -> float:
    return metrics.gauges[(name, (("endpoint", endpoint), ("operation", operation)))]


def test_percentiles_are_scoped_by_endpoint_and_operation() -> None:
    metrics = InMemoryMetrics()
    settings = Settings()
    tracker = LatencyTracker(metrics=metrics, settings=settings, rolling_window_size=100)

    tracker.track_stage("middleware_latency", 100.0, "t1", "/a")
    tracker.track_stage("middleware_latency", 200.0, "t2", "/b")
    tracker.track_stage("middleware_latency", 300.0, "t3", "/a")

    assert _gauge(metrics, "avg_response_time", "middleware_latency", "/a") == 200.0
    assert _gauge(metrics, "avg_response_time", "middleware_latency", "/b") == 200.0
    assert _gauge(metrics, "p50_latency", "middleware_latency", "/a") == 200.0
    assert _gauge(metrics, "p50_latency", "middleware_latency", "/b") == 200.0
