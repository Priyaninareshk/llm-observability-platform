import logging

from app.telemetry.base import CostTrackerPort
from app.telemetry.cost_tracker import CostBreakdown
from app.telemetry.token_tracker import TokenUsageRecord

logger = logging.getLogger(__name__)


class NoOpCostTracker(CostTrackerPort):
    """Starter cost tracker for US-06 integration readiness."""

    def track(self, model: str, total_tokens: int, estimated_cost_usd: float) -> None:
        logger.debug(
            "Track model cost",
            extra={
                "model": model,
                "total_tokens": total_tokens,
                "estimated_cost_usd": estimated_cost_usd,
            },
        )

    def calculate_and_track(self, token_usage: TokenUsageRecord) -> CostBreakdown:
        breakdown = CostBreakdown(
            prompt_cost=0.0,
            completion_cost=0.0,
            total_cost=0.0,
            model_name=token_usage.model_name,
            pricing_found=False,
        )
        logger.debug("Calculate cost (no-op)", extra={"model_name": token_usage.model_name})
        return breakdown

    def last_cost(self) -> CostBreakdown | None:
        return None
