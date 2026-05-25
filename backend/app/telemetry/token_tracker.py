import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from app.telemetry.base import MetricsPort, TokenTrackerPort

logger = logging.getLogger(__name__)


@dataclass
class TokenUsageRecord:
    """Normalized token usage payload for observability pipelines."""

    model_name: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    timestamp: str
    trace_id: str
    request_id: str
    request_latency_ms: float


class TokenUsageTracker(TokenTrackerPort):
    """Token lifecycle tracker with logs, metrics placeholders, and storage hook."""

    def __init__(self, metrics: MetricsPort) -> None:
        self._metrics = metrics
        self._last_record: TokenUsageRecord | None = None

    def track(self, model: str, prompt_tokens: int, completion_tokens: int) -> None:
        # Compatibility path for existing calls where request metadata is unavailable.
        self.track_usage(
            model_name=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            trace_id="",
            request_id="",
            request_latency_ms=0.0,
        )

    def track_usage(
        self,
        model_name: str,
        prompt_tokens: int,
        completion_tokens: int,
        trace_id: str,
        request_id: str,
        request_latency_ms: float,
    ) -> TokenUsageRecord:
        """Track per-request token metrics and return normalized token record."""
        total_tokens = prompt_tokens + completion_tokens
        record = TokenUsageRecord(
            model_name=model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            timestamp=datetime.now(timezone.utc).isoformat(),
            trace_id=trace_id,
            request_id=request_id,
            request_latency_ms=request_latency_ms,
        )
        self._last_record = record

        self._metrics.increment("total_tokens_used", total_tokens, labels={"model": model_name})
        self._metrics.increment("requests_per_model", 1, labels={"model": model_name})
        self._metrics.observe("avg_tokens_per_request", total_tokens, labels={"model": model_name})

        logger.info("token.usage", extra=asdict(record))
        self._persist_placeholder(record)
        return record

    def last_record(self) -> TokenUsageRecord | None:
        """Return most recently tracked token usage for current request context."""
        return self._last_record

    def _persist_placeholder(self, record: TokenUsageRecord) -> None:
        """Placeholder hook for future DB/warehouse persistence."""
        logger.debug("token.persistence.placeholder", extra=asdict(record))
