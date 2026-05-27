"""
A/B Testing Service — run parallel model comparisons.

Supports:
  - Routing requests to two models simultaneously
  - Collecting latency, cost, quality metrics per variant
  - Statistical comparison summaries
"""
import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("llm_observability.ab_testing")


@dataclass
class VariantResult:
    variant_id: str       # "control" | "treatment" | custom name
    model_name: str
    response: str
    latency_ms: float
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float
    faithfulness_score: Optional[float] = None
    error: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ABTestRecord:
    test_id: str
    experiment_name: str
    prompt: str
    control: VariantResult
    treatment: VariantResult
    winner: Optional[str] = None   # "control" | "treatment" | "tie"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def compare(self) -> Dict[str, Any]:
        """Return a structured comparison of both variants."""
        if self.control.error and self.treatment.error:
            winner = "tie"
        elif self.control.error:
            winner = "treatment"
        elif self.treatment.error:
            winner = "control"
        else:
            # Score on latency (lower=better) and cost (lower=better)
            control_score = 0
            treatment_score = 0
            if self.control.latency_ms < self.treatment.latency_ms:
                control_score += 1
            elif self.treatment.latency_ms < self.control.latency_ms:
                treatment_score += 1

            if self.control.cost_usd < self.treatment.cost_usd:
                control_score += 1
            elif self.treatment.cost_usd < self.control.cost_usd:
                treatment_score += 1

            if self.control.faithfulness_score and self.treatment.faithfulness_score:
                if self.control.faithfulness_score > self.treatment.faithfulness_score:
                    control_score += 1
                elif self.treatment.faithfulness_score > self.control.faithfulness_score:
                    treatment_score += 1

            if control_score > treatment_score:
                winner = "control"
            elif treatment_score > control_score:
                winner = "treatment"
            else:
                winner = "tie"

        self.winner = winner
        return {
            "test_id": self.test_id,
            "experiment_name": self.experiment_name,
            "winner": winner,
            "latency_delta_ms": (
                self.treatment.latency_ms - self.control.latency_ms
                if not (self.control.error or self.treatment.error) else None
            ),
            "cost_delta_usd": (
                self.treatment.cost_usd - self.control.cost_usd
                if not (self.control.error or self.treatment.error) else None
            ),
            "control": self.control.to_dict(),
            "treatment": self.treatment.to_dict(),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "test_id": self.test_id,
            "experiment_name": self.experiment_name,
            "prompt": self.prompt,
            "winner": self.winner,
            "control": self.control.to_dict(),
            "treatment": self.treatment.to_dict(),
            "created_at": self.created_at,
        }


class ABTestingService:
    """
    Runs two LLM variants in parallel and records comparison metrics.
    
    Usage
    -----
    service = ABTestingService()
    result = await service.run_comparison(
        prompt="Explain quantum entanglement",
        control_model="llama3-8b-8192",
        treatment_model="llama3-70b-8192",
        experiment_name="quality_vs_cost"
    )
    """

    def __init__(self, max_history: int = 1000):
        self._history: List[ABTestRecord] = []
        self._max_history = max_history
        self._experiment_stats: Dict[str, List[ABTestRecord]] = {}

    async def run_comparison(
        self,
        prompt: str,
        control_model: str,
        treatment_model: str,
        experiment_name: str = "default",
        control_fn=None,
        treatment_fn=None,
    ) -> ABTestRecord:
        """
        Run prompt against both models in parallel.
        control_fn / treatment_fn are async callables: (model, prompt) -> VariantResult
        If not provided, uses mock results (useful for testing the framework).
        """
        test_id = str(uuid.uuid4())

        async def _call(variant_id: str, model: str, fn) -> VariantResult:
            start = time.perf_counter()
            try:
                if fn:
                    result = await fn(model, prompt)
                    result.variant_id = variant_id
                    return result
                else:
                    # Mock result — replace with real LLM calls in production
                    await asyncio.sleep(0.1)
                    latency = (time.perf_counter() - start) * 1000
                    return VariantResult(
                        variant_id=variant_id,
                        model_name=model,
                        response=f"[Mock response from {model}]",
                        latency_ms=round(latency, 2),
                        prompt_tokens=len(prompt.split()),
                        completion_tokens=20,
                        total_tokens=len(prompt.split()) + 20,
                        cost_usd=0.0001,
                    )
            except Exception as exc:
                latency = (time.perf_counter() - start) * 1000
                logger.error("A/B variant %s failed: %s", variant_id, exc)
                return VariantResult(
                    variant_id=variant_id,
                    model_name=model,
                    response="",
                    latency_ms=round(latency, 2),
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_tokens=0,
                    cost_usd=0.0,
                    error=str(exc),
                )

        control_result, treatment_result = await asyncio.gather(
            _call("control", control_model, control_fn),
            _call("treatment", treatment_model, treatment_fn),
        )

        record = ABTestRecord(
            test_id=test_id,
            experiment_name=experiment_name,
            prompt=prompt,
            control=control_result,
            treatment=treatment_result,
        )
        record.compare()

        self._history.append(record)
        if len(self._history) > self._max_history:
            self._history.pop(0)

        self._experiment_stats.setdefault(experiment_name, []).append(record)

        logger.info(
            "A/B test completed: %s | winner=%s | control_lat=%.1fms | treatment_lat=%.1fms",
            test_id, record.winner,
            control_result.latency_ms, treatment_result.latency_ms,
        )

        return record

    def get_experiment_summary(self, experiment_name: str) -> Dict[str, Any]:
        """Aggregate stats for a named experiment."""
        records = self._experiment_stats.get(experiment_name, [])
        if not records:
            return {"experiment_name": experiment_name, "total_tests": 0}

        control_wins = sum(1 for r in records if r.winner == "control")
        treatment_wins = sum(1 for r in records if r.winner == "treatment")
        ties = sum(1 for r in records if r.winner == "tie")

        valid = [r for r in records if not r.control.error and not r.treatment.error]
        avg_ctrl_latency = sum(r.control.latency_ms for r in valid) / len(valid) if valid else None
        avg_trt_latency = sum(r.treatment.latency_ms for r in valid) / len(valid) if valid else None
        avg_ctrl_cost = sum(r.control.cost_usd for r in valid) / len(valid) if valid else None
        avg_trt_cost = sum(r.treatment.cost_usd for r in valid) / len(valid) if valid else None

        models = set()
        control_model = records[0].control.model_name if records else "unknown"
        treatment_model = records[0].treatment.model_name if records else "unknown"

        return {
            "experiment_name": experiment_name,
            "total_tests": len(records),
            "control_model": control_model,
            "treatment_model": treatment_model,
            "control_wins": control_wins,
            "treatment_wins": treatment_wins,
            "ties": ties,
            "win_rate_control": control_wins / len(records) if records else 0,
            "win_rate_treatment": treatment_wins / len(records) if records else 0,
            "avg_latency_ms": {
                "control": avg_ctrl_latency,
                "treatment": avg_trt_latency,
            },
            "avg_cost_usd": {
                "control": avg_ctrl_cost,
                "treatment": avg_trt_cost,
            },
        }

    def get_history(self, limit: int = 50, experiment_name: Optional[str] = None) -> List[Dict[str, Any]]:
        records = self._history
        if experiment_name:
            records = [r for r in records if r.experiment_name == experiment_name]
        return [r.to_dict() for r in records[-limit:]]

    def list_experiments(self) -> List[str]:
        return list(self._experiment_stats.keys())


# Singleton
ab_testing_service = ABTestingService()
