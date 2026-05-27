"""
Live and Historical Monitoring API.

Provides:
  - /monitoring/live      — snapshot of current system health
  - /monitoring/history   — time-bucketed historical metrics
  - /monitoring/summary   — high-level summary for dashboards
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query
from storage.trace_storage import trace_storage
from monitoring.error_tracker import error_tracker
from alerting.alert_engine import alert_engine

logger = logging.getLogger("llm_observability.monitoring_views")

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


def _bucket_traces_by_hour(traces: List[Dict[str, Any]], hours: int = 24) -> List[Dict[str, Any]]:
    """Group traces into hourly buckets for historical charts."""
    now = datetime.now(timezone.utc)
    buckets: Dict[str, Dict[str, Any]] = {}

    for h in range(hours, 0, -1):
        bucket_start = now - timedelta(hours=h)
        label = bucket_start.strftime("%Y-%m-%dT%H:00Z")
        buckets[label] = {
            "timestamp": label,
            "request_count": 0,
            "error_count": 0,
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "latency_sum_ms": 0.0,
            "hallucinated_count": 0,
        }

    for trace in traces:
        created = trace.get("created_at", "")
        try:
            dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            bucket_label = dt.strftime("%Y-%m-%dT%H:00Z")
            if bucket_label in buckets:
                b = buckets[bucket_label]
                b["request_count"] += 1
                if trace.get("error_type"):
                    b["error_count"] += 1
                b["total_tokens"] += trace.get("total_tokens", 0)
                b["total_cost_usd"] += trace.get("total_cost", 0.0)
                b["latency_sum_ms"] += trace.get("latency_total_ms", 0.0)
                if trace.get("faithfulness_label") == "hallucinated":
                    b["hallucinated_count"] += 1
        except Exception:
            continue

    # Compute derived metrics per bucket
    result = []
    for label, b in sorted(buckets.items()):
        count = b["request_count"]
        b["avg_latency_ms"] = round(b["latency_sum_ms"] / count, 2) if count > 0 else 0
        b["error_rate"] = round(b["error_count"] / count, 4) if count > 0 else 0
        del b["latency_sum_ms"]
        result.append(b)

    return result


@router.get("/live", summary="Real-time system health snapshot")
async def live_monitoring():
    """
    Returns a current-state snapshot of the LLM observability platform:
    recent request rates, error rates, alert status, and trace health.
    """
    now = datetime.now(timezone.utc)
    five_min_ago = (now - timedelta(minutes=5)).isoformat()
    one_hour_ago = (now - timedelta(hours=1)).isoformat()

    # Recent traces (last 5 min)
    recent_traces = trace_storage.list_traces(
        limit=500,
        filters={"start_time": five_min_ago},
        order_by="created_at",
        order_dir="DESC",
    )

    # Last hour for broader context
    hour_traces = trace_storage.list_traces(
        limit=2000,
        filters={"start_time": one_hour_ago},
        order_by="created_at",
        order_dir="DESC",
    )

    total_recent = len(recent_traces)
    error_recent = len([t for t in recent_traces if t.get("error_type")])
    latencies = [t["latency_total_ms"] for t in recent_traces if t.get("latency_total_ms")]
    costs = [t["total_cost"] for t in recent_traces if t.get("total_cost") is not None]
    hallucinated = [t for t in recent_traces if t.get("faithfulness_label") == "hallucinated"]
    scored = [t for t in recent_traces if t.get("faithfulness_label")]

    avg_latency = round(sum(latencies) / len(latencies), 2) if latencies else 0
    error_rate = round(error_recent / total_recent, 4) if total_recent > 0 else 0
    hal_rate = round(len(hallucinated) / len(scored), 4) if scored else 0

    # Active alerts
    active_rules = alert_engine.active_rules_summary()
    recent_alerts = alert_engine.get_history(limit=10)

    return {
        "timestamp": now.isoformat(),
        "window": "last_5_minutes",
        "requests": {
            "total": total_recent,
            "errors": error_recent,
            "error_rate": error_rate,
            "requests_per_minute": round(total_recent / 5, 2),
        },
        "latency": {
            "avg_ms": avg_latency,
            "sample_count": len(latencies),
        },
        "cost": {
            "total_usd": round(sum(costs), 6),
            "avg_per_request_usd": round(sum(costs) / len(costs), 6) if costs else 0,
        },
        "hallucination": {
            "hallucinated_count": len(hallucinated),
            "scored_count": len(scored),
            "hallucination_rate": hal_rate,
        },
        "alerts": {
            "total_rules": len(active_rules),
            "recent_fired": len(recent_alerts),
            "last_alert": recent_alerts[-1] if recent_alerts else None,
        },
        "hour_summary": {
            "total_requests": len(hour_traces),
            "total_errors": len([t for t in hour_traces if t.get("error_type")]),
            "total_cost_usd": round(sum(t.get("total_cost", 0) for t in hour_traces), 6),
        },
    }


@router.get("/history", summary="Historical metrics in hourly buckets")
async def historical_monitoring(
    hours: int = Query(24, ge=1, le=168, description="Hours of history (max 7 days)"),
):
    """
    Returns request counts, error rates, latency, cost, and hallucination
    rates bucketed into hourly intervals for trend visualization.
    """
    now = datetime.now(timezone.utc)
    start_time = (now - timedelta(hours=hours)).isoformat()

    traces = trace_storage.list_traces(
        limit=50_000,
        filters={"start_time": start_time},
        order_by="created_at",
        order_dir="ASC",
    )

    buckets = _bucket_traces_by_hour(traces, hours=hours)

    return {
        "period_hours": hours,
        "total_traces": len(traces),
        "generated_at": now.isoformat(),
        "buckets": buckets,
    }


@router.get("/summary", summary="High-level dashboard summary")
async def monitoring_summary():
    """
    Returns a single-page summary suitable for the main dashboard:
    all-time stats, recent health, and alert status.
    """
    all_stats = trace_storage.get_stats()
    recent_alerts = alert_engine.get_history(limit=5)
    error_metrics = error_tracker.get_metrics()

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "all_time": {
            "total_traces": all_stats.get("total_traces", 0),
            "avg_latency_ms": round(all_stats.get("avg_latency_ms") or 0, 2),
            "total_cost_usd": round(all_stats.get("total_cost") or 0, 6),
            "total_tokens": all_stats.get("total_tokens", 0),
            "total_errors": all_stats.get("total_errors", 0),
            "avg_faithfulness_score": round(all_stats.get("avg_faithfulness") or 0, 4),
        },
        "alerts": {
            "recent": recent_alerts,
            "rules_count": len(alert_engine.get_rules()),
        },
        "error_tracker": error_metrics,
    }
