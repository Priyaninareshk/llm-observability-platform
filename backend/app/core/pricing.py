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
    "llama3-8b-8192": ModelPricing(input_per_1k=0.00005, output_per_1k=0.00008),
    "llama3-70b-8192": ModelPricing(input_per_1k=0.00059, output_per_1k=0.00079),
    "mixtral-8x7b-32768": ModelPricing(input_per_1k=0.00024, output_per_1k=0.00024),
    "gemma2-9b-it": ModelPricing(input_per_1k=0.00020, output_per_1k=0.00020),
    "llama-3.1-8b-instant": ModelPricing(input_per_1k=0.00005, output_per_1k=0.00008),
    "llama-3.3-70b-versatile": ModelPricing(input_per_1k=0.00059, output_per_1k=0.00079),
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
