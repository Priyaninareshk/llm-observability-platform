import json
import logging
from dataclasses import dataclass

from app.core.config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelPricing:
    """Token pricing definition in USD per 1K tokens."""

    input_per_1k: float
    output_per_1k: float


DEFAULT_MODEL_PRICING: dict[str, ModelPricing] = {
    "gpt-4o-mini": ModelPricing(input_per_1k=0.00015, output_per_1k=0.0006),
    "gpt-4o": ModelPricing(input_per_1k=0.005, output_per_1k=0.015),
    "gpt-3.5-turbo": ModelPricing(input_per_1k=0.0005, output_per_1k=0.0015),
}


def load_model_pricing(settings: Settings) -> dict[str, ModelPricing]:
    """Load pricing from defaults plus optional JSON overrides in environment."""
    pricing = dict(DEFAULT_MODEL_PRICING)
    if not settings.model_pricing_json:
        return pricing

    try:
        raw = json.loads(settings.model_pricing_json)
        for model_name, cfg in raw.items():
            pricing[model_name] = ModelPricing(
                input_per_1k=float(cfg["input_per_1k"]),
                output_per_1k=float(cfg["output_per_1k"]),
            )
    except (ValueError, KeyError, TypeError) as exc:
        logger.warning("Invalid MODEL_PRICING_JSON override; using defaults", extra={"error": str(exc)})
    return pricing
