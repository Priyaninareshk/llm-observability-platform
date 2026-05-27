import logging
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from app.core.pricing import ModelPricing
from app.telemetry.base import CostTrackerPort, MetricsPort
from app.telemetry.token_tracker import TokenUsageRecord

logger = logging.getLogger(__name__)


@dataclass
class CostBreakdown:
    """Per-request cost estimate in USD."""

    prompt_cost: float
    completion_cost: float
    total_cost: float
    model_name: str
    pricing_found: bool


@dataclass
class CostRecord:
    """Per-request cost record used for API reporting."""

    timestamp: str
    trace_id: str
    request_id: str
    model_name: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    prompt_cost: float
    completion_cost: float
    total_cost: float
    pricing_found: bool


class CostTracker(CostTrackerPort):
    """Cost monitoring with pricing map, metrics placeholders, and alert hook."""

    def __init__(self, metrics: MetricsPort, pricing_by_model: dict[str, ModelPricing], alert_threshold_usd: float) -> None:
        self._metrics = metrics
        self._pricing_by_model = pricing_by_model
        self._alert_threshold_usd = alert_threshold_usd
        self._last_cost: CostBreakdown | None = None
        self._records: deque[CostRecord] = deque(maxlen=5000)

    def track(self, model: str, total_tokens: int, estimated_cost_usd: float) -> None:
        # Compatibility path for legacy calls.
        logger.info(
            "cost.usage.legacy",
            extra={"model_name": model, "total_tokens": total_tokens, "estimated_cost_usd": estimated_cost_usd},
        )

    def calculate_and_track(self, token_usage: TokenUsageRecord) -> CostBreakdown:
        """Calculate per-request cost and emit metrics/log events."""
        pricing = self._pricing_by_model.get(token_usage.model_name)
        if pricing is None:
            pricing = self._pricing_by_model.get("llama3-8b-8192")
            pricing_found = False
        else:
            pricing_found = True

        prompt_cost = (token_usage.prompt_tokens / 1000.0) * pricing.input_per_1k
        completion_cost = (token_usage.completion_tokens / 1000.0) * pricing.output_per_1k
        total_cost = prompt_cost + completion_cost

        breakdown = CostBreakdown(
            prompt_cost=prompt_cost,
            completion_cost=completion_cost,
            total_cost=total_cost,
            model_name=token_usage.model_name,
            pricing_found=pricing_found,
        )
        self._last_cost = breakdown
        self._records.append(
            CostRecord(
                timestamp=datetime.now(timezone.utc).isoformat(),
                trace_id=token_usage.trace_id,
                request_id=token_usage.request_id,
                model_name=token_usage.model_name,
                prompt_tokens=token_usage.prompt_tokens,
                completion_tokens=token_usage.completion_tokens,
                total_tokens=token_usage.total_tokens,
                prompt_cost=prompt_cost,
                completion_cost=completion_cost,
                total_cost=total_cost,
                pricing_found=pricing_found,
            )
        )

        self._metrics.observe("total_cost_usd", total_cost, labels={"model": token_usage.model_name})
        self._metrics.observe("avg_cost_per_request", total_cost, labels={"model": token_usage.model_name})
        self._metrics.observe("cost_per_model", total_cost, labels={"model": token_usage.model_name})

        logger.info(
            "cost.calculated",
            extra={
                **asdict(breakdown),
                "trace_id": token_usage.trace_id,
                "request_id": token_usage.request_id,
                "pricing_input_per_1k": pricing.input_per_1k,
                "pricing_output_per_1k": pricing.output_per_1k,
            },
        )

        if total_cost > self._alert_threshold_usd:
            self._trigger_cost_alert(token_usage, breakdown)

        self._persist_placeholder(token_usage, breakdown)
        return breakdown

    def last_cost(self) -> CostBreakdown | None:
        """Return most recently computed cost breakdown."""
        return self._last_cost

    def _trigger_cost_alert(self, token_usage: TokenUsageRecord, breakdown: CostBreakdown) -> None:
        """Placeholder for future alert manager integration."""
        logger.warning(
            "cost.alert.placeholder",
            extra={
                "trace_id": token_usage.trace_id,
                "request_id": token_usage.request_id,
                "model_name": token_usage.model_name,
                "total_cost": breakdown.total_cost,
                "threshold_usd": self._alert_threshold_usd,
            },
        )

    def _persist_placeholder(self, token_usage: TokenUsageRecord, breakdown: CostBreakdown) -> None:
        """Placeholder hook for future persistence in OLAP/time-series databases."""
        logger.debug(
            "cost.persistence.placeholder",
            extra={
                "trace_id": token_usage.trace_id,
                "request_id": token_usage.request_id,
                **asdict(breakdown),
            },
        )

    def report(self) -> dict:
        """Return aggregated cost report payload for API consumers."""
        records = list(self._records)
        total_requests = len(records)
        total_cost = sum(item.total_cost for item in records)
        by_model: dict[str, dict[str, float | int]] = {}
        for item in records:
            if item.model_name not in by_model:
                by_model[item.model_name] = {"requests": 0, "total_cost": 0.0, "total_tokens": 0}
            by_model[item.model_name]["requests"] += 1
            by_model[item.model_name]["total_cost"] += item.total_cost
            by_model[item.model_name]["total_tokens"] += item.total_tokens

        avg_cost_per_request = total_cost / total_requests if total_requests else 0.0
        return {
            "total_requests": total_requests,
            "total_cost_usd": total_cost,
            "avg_cost_per_request_usd": avg_cost_per_request,
            "alert_threshold_usd": self._alert_threshold_usd,
            "by_model": by_model,
            "recent_records": [asdict(item) for item in records[-20:]],
        }
