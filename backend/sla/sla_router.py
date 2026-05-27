"""FastAPI router for SLA report endpoints."""
from typing import Optional

from fastapi import APIRouter, Query

from sla.sla_reporter import generate_sla_report

router = APIRouter(prefix="/sla", tags=["sla"])


@router.get("/report", summary="Generate automated SLA compliance report")
async def sla_report(
    period_hours: int = Query(24, ge=1, le=720, description="Lookback window in hours"),
    start_time: Optional[str] = Query(None, description="ISO 8601 start (overrides period_hours)"),
    end_time: Optional[str] = Query(None, description="ISO 8601 end"),
):
    """
    Returns a full SLA compliance report including availability, latency,
    error rate, hallucination rate, and cost budget adherence.
    """
    report = generate_sla_report(
        period_hours=period_hours,
        start_time=start_time,
        end_time=end_time,
    )
    return report.to_dict()


@router.get("/targets", summary="List current SLA targets")
async def sla_targets():
    """Return the configured SLA threshold values."""
    import os
    return {
        "availability_pct": float(os.getenv("SLA_AVAILABILITY_PCT", "99.5")),
        "p95_latency_ms": float(os.getenv("SLA_P95_LATENCY_MS", "3000")),
        "p99_latency_ms": float(os.getenv("SLA_P99_LATENCY_MS", "6000")),
        "error_rate_max": float(os.getenv("SLA_ERROR_RATE_MAX", "0.02")),
        "hallucination_rate_max": float(os.getenv("SLA_HALLUCINATION_MAX", "0.10")),
        "daily_cost_budget_usd": float(os.getenv("SLA_COST_BUDGET_DAILY", "50.0")),
    }
