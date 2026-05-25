import logging
from dataclasses import asdict

from app.telemetry.base import TokenTrackerPort
from app.telemetry.token_tracker import TokenUsageRecord

logger = logging.getLogger(__name__)


class NoOpTokenTracker(TokenTrackerPort):
    """Starter token tracker for US-05 integration readiness."""

    def track(self, model: str, prompt_tokens: int, completion_tokens: int) -> None:
        self.track_usage(model, prompt_tokens, completion_tokens, "", "", 0.0)

    def track_usage(
        self,
        model_name: str,
        prompt_tokens: int,
        completion_tokens: int,
        trace_id: str,
        request_id: str,
        request_latency_ms: float,
    ) -> TokenUsageRecord:
        record = TokenUsageRecord(
            model_name=model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            timestamp="",
            trace_id=trace_id,
            request_id=request_id,
            request_latency_ms=request_latency_ms,
        )
        logger.debug("Track token usage (no-op)", extra=asdict(record))
        return record

    def last_record(self) -> TokenUsageRecord | None:
        return None
