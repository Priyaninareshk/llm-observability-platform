import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from langchain_core.callbacks.base import BaseCallbackHandler
from opentelemetry import trace

from app.telemetry.base import CostTrackerPort, LatencyTrackerPort, MetricsPort, TokenTrackerPort
from app.telemetry.cost_tracker import CostBreakdown
from app.telemetry.token_tracker import TokenUsageRecord

logger = logging.getLogger(__name__)


@dataclass
class CallbackLatency:
    llm_inference_ms: float
    callback_processing_ms: float


class LangSmithObservabilityCallback(BaseCallbackHandler):
    """Custom LangChain callback handler for trace and usage capture.

    Callback lifecycle:
    - on_llm_start: marks request start, prompt metadata
    - on_llm_end: captures response metadata, token usage, and latency
    - on_llm_error: tracks failures for observability and alerting readiness
    """

    def __init__(
        self,
        metrics: MetricsPort,
        token_tracker: TokenTrackerPort,
        cost_tracker: CostTrackerPort,
        latency_tracker: LatencyTrackerPort,
        trace_id_getter,
    ) -> None:
        self._metrics = metrics
        self._token_tracker = token_tracker
        self._cost_tracker = cost_tracker
        self._latency_tracker = latency_tracker
        self._trace_id_getter = trace_id_getter
        self._started_at: dict[str, float] = {}
        self._request_ids: dict[str, str] = {}
        self._latest_token_usage: TokenUsageRecord | None = None
        self._latest_cost: CostBreakdown | None = None
        self._latest_latency: CallbackLatency | None = None

    def on_llm_start(self, serialized: dict[str, Any], prompts: list[str], *, run_id, **kwargs: Any) -> None:
        run_key = str(run_id)
        self._started_at[run_key] = time.perf_counter()
        self._request_ids[run_key] = uuid.uuid4().hex
        model_name = serialized.get("name", "unknown-model")
        logger.info(
            "llm.request.start",
            extra={
                "run_id": run_key,
                "trace_id": self._trace_id_getter(),
                "request_id": self._request_ids[run_key],
                "model_name": model_name,
                "prompt_count": len(prompts),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
        self._metrics.increment("llm_request_count", labels={"model": model_name})

    def on_llm_end(self, response, *, run_id, **kwargs: Any) -> None:
        callback_started_at = time.perf_counter()
        run_key = str(run_id)
        started_at = self._started_at.pop(run_key, time.perf_counter())
        request_id = self._request_ids.pop(run_key, "")
        llm_latency_ms = (time.perf_counter() - started_at) * 1000

        usage = getattr(response, "llm_output", {}) or {}
        token_usage = usage.get("token_usage", {}) if isinstance(usage, dict) else {}
        prompt_tokens = int(token_usage.get("prompt_tokens", 0))
        completion_tokens = int(token_usage.get("completion_tokens", 0))
        total_tokens = int(token_usage.get("total_tokens", prompt_tokens + completion_tokens))
        model_name = usage.get("model_name", "unknown-model") if isinstance(usage, dict) else "unknown-model"

        trace_id = self._trace_id_getter()
        token_usage = self._token_tracker.track_usage(
            model_name=model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            trace_id=trace_id,
            request_id=request_id,
            request_latency_ms=llm_latency_ms,
        )
        self._latest_token_usage = token_usage

        self._latency_tracker.track("llm_inference", llm_latency_ms)
        self._metrics.observe("llm_latency_ms", llm_latency_ms, labels={"model": model_name})
        self._metrics.increment("llm_token_usage_total", token_usage.total_tokens, labels={"model": model_name})

        cost = self._cost_tracker.calculate_and_track(token_usage)
        self._latest_cost = cost
        self._metrics.observe("llm_cost_usd", cost.total_cost, labels={"model": model_name})
        span = trace.get_current_span()
        span.set_attribute("tokens.prompt", token_usage.prompt_tokens)
        span.set_attribute("tokens.completion", token_usage.completion_tokens)
        span.set_attribute("tokens.total", token_usage.total_tokens)
        span.set_attribute("cost.prompt", cost.prompt_cost)
        span.set_attribute("cost.completion", cost.completion_cost)
        span.set_attribute("cost.total", cost.total_cost)
        span.set_attribute("latency.llm_ms", llm_latency_ms)

        callback_processing_ms = (time.perf_counter() - callback_started_at) * 1000
        self._latest_latency = CallbackLatency(
            llm_inference_ms=llm_latency_ms,
            callback_processing_ms=callback_processing_ms,
        )
        self._latency_tracker.track("callback_processing", callback_processing_ms)
        span.set_attribute("latency.callback_ms", callback_processing_ms)

        logger.info(
            "llm.request.success",
            extra={
                "run_id": run_key,
                "trace_id": trace_id,
                "request_id": request_id,
                "model_name": model_name,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "latency_llm_ms": llm_latency_ms,
                "latency_callback_ms": callback_processing_ms,
                "prompt_cost": cost.prompt_cost,
                "completion_cost": cost.completion_cost,
                "total_cost": cost.total_cost,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    def on_llm_error(self, error: BaseException, *, run_id, **kwargs: Any) -> None:
        run_key = str(run_id)
        self._started_at.pop(run_key, None)
        logger.exception(
            "llm.request.failure",
            extra={
                "run_id": run_key,
                "trace_id": self._trace_id_getter(),
                "error_type": type(error).__name__,
                "error_message": str(error),
            },
        )
        self._metrics.increment("llm_error_count", labels={"error_type": type(error).__name__})

    def latest_usage(self) -> tuple[TokenUsageRecord | None, CostBreakdown | None]:
        """Return last token usage and cost summaries captured by callback lifecycle."""
        return self._latest_token_usage, self._latest_cost

    def latest_latency(self) -> CallbackLatency | None:
        """Return callback lifecycle latency summary."""
        return self._latest_latency
