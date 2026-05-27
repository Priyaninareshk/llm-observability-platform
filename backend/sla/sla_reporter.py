"""
Automated SLA Report Generator.

Calculates and reports:
  - Availability (uptime percentage)
  - P50/P95/P99 latency vs SLA targets
  - Error rate vs SLA threshold
  - Hallucination rate vs quality SLA
  - Cost budget adherence
  - Per-model breakdown
"""
import logging
import os
import statistics
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from storage.trace_storage import trace_storage

logger = logging.getLogger("llm_observability.sla")


# ---------------------------------------------------------------------------
# SLA targets (env-overridable)
# ---------------------------------------------------------------------------

SLA_AVAILABILITY_PCT   = float(os.getenv("SLA_AVAILABILITY_PCT",   "99.5"))   # %
SLA_P95_LATENCY_MS     = float(os.getenv("SLA_P95_LATENCY_MS",     "3000"))   # ms
SLA_P99_LATENCY_MS     = float(os.getenv("SLA_P99_LATENCY_MS",     "6000"))   # ms
SLA_ERROR_RATE_MAX     = float(os.getenv("SLA_ERROR_RATE_MAX",      "0.02"))   # 2%
SLA_HALLUCINATION_MAX  = float(os.getenv("SLA_HALLUCINATION_MAX",   "0.10"))   # 10%
SLA_COST_BUDGET_DAILY  = float(os.getenv("SLA_COST_BUDGET_DAILY",   "50.0"))   # USD


@dataclass
class SLAMetric:
    name: str
    target: float
    actual: float
    unit: str
    met: bool
    breach_pct: float = 0.0   # how much over/under target (positive = worse)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SLAReport:
    report_id: str
    period_start: str
    period_end: str
    generated_at: str
    total_requests: int
    total_errors: int
    metrics: List[SLAMetric] = field(default_factory=list)
    model_breakdown: Dict[str, Any] = field(default_factory=dict)
    overall_sla_met: bool = True
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


def _percentile(data: List[float], p: float) -> float:
    if not data:
        return 0.0
    sorted_data = sorted(data)
    idx = int(len(sorted_data) * p / 100)
    return sorted_data[min(idx, len(sorted_data) - 1)]


def generate_sla_report(
    period_hours: int = 24,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
) -> SLAReport:
    """
    Generate an SLA compliance report for the given time period.
    Defaults to the last `period_hours` hours.
    """
    now = datetime.now(timezone.utc)

    if end_time is None:
        end_dt = now
        end_time = end_dt.isoformat()
    else:
        end_dt = datetime.fromisoformat(end_time)

    if start_time is None:
        start_dt = end_dt - timedelta(hours=period_hours)
        start_time = start_dt.isoformat()
    else:
        start_dt = datetime.fromisoformat(start_time)

    import uuid
    report_id = str(uuid.uuid4())[:8]

    # Fetch traces in period
    traces = trace_storage.list_traces(
        limit=10_000,
        filters={"start_time": start_time, "end_time": end_time},
        order_by="created_at",
        order_dir="ASC",
    )

    total_requests = len(traces)
    error_traces = [t for t in traces if t.get("error_type")]
    total_errors = len(error_traces)

    latencies = [t["latency_total_ms"] for t in traces if t.get("latency_total_ms")]
    costs = [t["total_cost"] for t in traces if t.get("total_cost") is not None]
    hallucination_traces = [t for t in traces if t.get("faithfulness_label") == "hallucinated"]
    scored_traces = [t for t in traces if t.get("faithfulness_label") is not None]

    # Compute metrics
    p95_latency = _percentile(latencies, 95) if latencies else 0.0
    p99_latency = _percentile(latencies, 99) if latencies else 0.0
    error_rate = total_errors / total_requests if total_requests > 0 else 0.0
    hallucination_rate = (
        len(hallucination_traces) / len(scored_traces) if scored_traces else 0.0
    )
    total_cost = sum(costs)
    # Estimate availability: 100% - error_rate (simplification for this platform)
    availability = (1.0 - error_rate) * 100.0

    # Build SLA metric checks
    metrics: List[SLAMetric] = []

    def _check(name, target, actual, unit, higher_is_better=False) -> SLAMetric:
        if higher_is_better:
            met = actual >= target
            breach = (target - actual) / target * 100 if not met else 0.0
        else:
            met = actual <= target
            breach = (actual - target) / target * 100 if not met else 0.0
        return SLAMetric(name=name, target=target, actual=actual, unit=unit, met=met, breach_pct=round(breach, 2))

    metrics.append(_check("Availability", SLA_AVAILABILITY_PCT, availability, "%", higher_is_better=True))
    metrics.append(_check("P95 Latency", SLA_P95_LATENCY_MS, p95_latency, "ms"))
    metrics.append(_check("P99 Latency", SLA_P99_LATENCY_MS, p99_latency, "ms"))
    metrics.append(_check("Error Rate", SLA_ERROR_RATE_MAX, error_rate, "ratio"))
    metrics.append(_check("Hallucination Rate", SLA_HALLUCINATION_MAX, hallucination_rate, "ratio"))
    metrics.append(_check("Daily Cost Budget", SLA_COST_BUDGET_DAILY, total_cost, "USD"))

    overall_met = all(m.met for m in metrics)

    # Per-model breakdown
    model_data: Dict[str, List] = {}
    for t in traces:
        model = t.get("model_name", "unknown")
        model_data.setdefault(model, []).append(t)

    model_breakdown: Dict[str, Any] = {}
    for model, model_traces in model_data.items():
        mlat = [t["latency_total_ms"] for t in model_traces if t.get("latency_total_ms")]
        mcosts = [t["total_cost"] for t in model_traces if t.get("total_cost") is not None]
        merrors = [t for t in model_traces if t.get("error_type")]
        model_breakdown[model] = {
            "total_requests": len(model_traces),
            "total_errors": len(merrors),
            "error_rate": len(merrors) / len(model_traces) if model_traces else 0,
            "avg_latency_ms": round(sum(mlat) / len(mlat), 2) if mlat else 0,
            "p95_latency_ms": round(_percentile(mlat, 95), 2),
            "total_cost_usd": round(sum(mcosts), 6),
        }

    # Summary text
    breached = [m for m in metrics if not m.met]
    if not breached:
        summary = f"✅ All SLA targets met for the {period_hours}h period ({total_requests} requests)."
    else:
        breach_names = ", ".join(m.name for m in breached)
        summary = (
            f"⚠️ SLA breached for: {breach_names}. "
            f"Period: {total_requests} requests, {total_errors} errors."
        )

    report = SLAReport(
        report_id=report_id,
        period_start=start_time,
        period_end=end_time,
        generated_at=now.isoformat(),
        total_requests=total_requests,
        total_errors=total_errors,
        metrics=metrics,
        model_breakdown=model_breakdown,
        overall_sla_met=overall_met,
        summary=summary,
    )

    logger.info("SLA report generated: %s | overall_met=%s", report_id, overall_met)
    return report
