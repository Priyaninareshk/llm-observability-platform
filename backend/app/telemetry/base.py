from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.telemetry.cost_tracker import CostBreakdown
    from app.telemetry.latency_tracker import LatencyRecord
    from app.telemetry.token_tracker import TokenUsageRecord


class TracerPort(ABC):
    """Abstract tracing interface.

    Future implementations can route traces to OpenTelemetry, LangSmith, or custom
    backends without changing business logic.
    """

    @abstractmethod
    def start_span(self, name: str, attributes: Mapping[str, Any] | None = None) -> Any:
        """Start and return a span handle for an operation."""

    @abstractmethod
    def end_span(self, span: Any) -> None:
        """Close the provided span handle."""


class MetricsPort(ABC):
    """Abstract metrics interface for counters, histograms, and gauges."""

    @abstractmethod
    def increment(self, name: str, value: float = 1.0, labels: Mapping[str, str] | None = None) -> None:
        """Increment a named metric with optional labels."""

    @abstractmethod
    def observe(self, name: str, value: float, labels: Mapping[str, str] | None = None) -> None:
        """Observe a value for histogram/summary style metrics."""

    @abstractmethod
    def set_gauge(self, name: str, value: float, labels: Mapping[str, str] | None = None) -> None:
        """Set a gauge metric value."""


class TokenTrackerPort(ABC):
    """Abstract token accounting interface for prompt/completion usage."""

    @abstractmethod
    def track(self, model: str, prompt_tokens: int, completion_tokens: int) -> None:
        """Record token usage for a model invocation."""

    @abstractmethod
    def track_usage(
        self,
        model_name: str,
        prompt_tokens: int,
        completion_tokens: int,
        trace_id: str,
        request_id: str,
        request_latency_ms: float,
    ) -> "TokenUsageRecord":
        """Record rich token usage metadata for one request."""

    @abstractmethod
    def last_record(self) -> "TokenUsageRecord | None":
        """Return most recent usage record."""


class CostTrackerPort(ABC):
    """Abstract cost accounting interface for model invocations."""

    @abstractmethod
    def track(self, model: str, total_tokens: int, estimated_cost_usd: float) -> None:
        """Record estimated cost metadata for an invocation."""

    @abstractmethod
    def calculate_and_track(self, token_usage: "TokenUsageRecord") -> "CostBreakdown":
        """Calculate and record per-request cost from token usage."""

    @abstractmethod
    def last_cost(self) -> "CostBreakdown | None":
        """Return most recent cost breakdown."""


class LatencyTrackerPort(ABC):
    """Abstract latency tracking interface for API and model calls."""

    @abstractmethod
    def track(self, operation: str, duration_ms: float) -> None:
        """Record latency in milliseconds for a named operation."""

    @abstractmethod
    def track_stage(self, operation: str, duration_ms: float, trace_id: str, endpoint: str) -> "LatencyRecord":
        """Track one latency stage with endpoint and trace metadata."""

    @abstractmethod
    def rolling_latency_values(self) -> list[float]:
        """Return rolling latency buffer for future percentile calculations."""
