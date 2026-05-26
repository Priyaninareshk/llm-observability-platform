import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from storage.trace_storage import trace_storage

logger = logging.getLogger("llm_observability.trace_query")

router = APIRouter(prefix="/traces", tags=["traces"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class TraceListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    traces: List[Dict[str, Any]]


class TraceStatsResponse(BaseModel):
    total_traces: int
    avg_latency_ms: Optional[float]
    avg_cost: Optional[float]
    total_tokens: Optional[int]
    total_cost: Optional[float]
    total_errors: Optional[int]
    avg_faithfulness: Optional[float]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("", response_model=TraceListResponse, summary="List and filter traces")
async def list_traces(
    # Exact filters
    model_name: Optional[str] = Query(None, description="Filter by model name"),
    endpoint: Optional[str] = Query(None, description="Filter by endpoint path"),
    error_type: Optional[str] = Query(None, description="Filter by error type"),
    faithfulness_label: Optional[str] = Query(
        None, description="faithful | uncertain | hallucinated"
    ),
    has_error: Optional[bool] = Query(None, description="Only show traces with errors"),
    # Range filters
    min_latency_ms: Optional[float] = Query(None, description="Min total latency (ms)"),
    max_latency_ms: Optional[float] = Query(None, description="Max total latency (ms)"),
    min_cost: Optional[float] = Query(None, description="Min total cost (USD)"),
    max_cost: Optional[float] = Query(None, description="Max total cost (USD)"),
    # Time range
    start_time: Optional[str] = Query(None, description="ISO 8601 start timestamp"),
    end_time: Optional[str] = Query(None, description="ISO 8601 end timestamp"),
    # Full-text
    search: Optional[str] = Query(None, description="Search prompt/response text"),
    # Pagination & ordering
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    order_by: str = Query("created_at", description="Sort column"),
    order_dir: str = Query("DESC", description="ASC or DESC"),
):
    filters: Dict[str, Any] = {}
    if model_name:
        filters["model_name"] = model_name
    if endpoint:
        filters["endpoint"] = endpoint
    if error_type:
        filters["error_type"] = error_type
    if faithfulness_label:
        filters["faithfulness_label"] = faithfulness_label
    if has_error is not None:
        filters["has_error"] = has_error
    if min_latency_ms is not None:
        filters["min_latency_ms"] = min_latency_ms
    if max_latency_ms is not None:
        filters["max_latency_ms"] = max_latency_ms
    if min_cost is not None:
        filters["min_cost"] = min_cost
    if max_cost is not None:
        filters["max_cost"] = max_cost
    if start_time:
        filters["start_time"] = start_time
    if end_time:
        filters["end_time"] = end_time
    if search:
        filters["search"] = search

    traces = trace_storage.list_traces(
        limit=limit,
        offset=offset,
        filters=filters,
        order_by=order_by,
        order_dir=order_dir,
    )
    total = trace_storage.count_traces(filters=filters)

    return TraceListResponse(total=total, limit=limit, offset=offset, traces=traces)


@router.get("/stats", response_model=TraceStatsResponse, summary="Aggregate trace statistics")
async def get_stats():
    stats = trace_storage.get_stats()
    return TraceStatsResponse(
        total_traces=stats.get("total_traces", 0),
        avg_latency_ms=stats.get("avg_latency_ms"),
        avg_cost=stats.get("avg_cost"),
        total_tokens=stats.get("total_tokens"),
        total_cost=stats.get("total_cost"),
        total_errors=stats.get("total_errors"),
        avg_faithfulness=stats.get("avg_faithfulness"),
    )


@router.get("/{trace_id}", summary="Get a single trace by ID")
async def get_trace(trace_id: str):
    trace = trace_storage.get_trace(trace_id)
    if not trace:
        raise HTTPException(status_code=404, detail=f"Trace '{trace_id}' not found")
    return trace


@router.get("/search/hallucinated", summary="List hallucinated traces")
async def list_hallucinated(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    traces = trace_storage.list_traces(
        limit=limit,
        offset=offset,
        filters={"faithfulness_label": "hallucinated"},
        order_by="faithfulness_score",
        order_dir="ASC",
    )
    return {"count": len(traces), "traces": traces}


@router.get("/search/errors", summary="List error traces")
async def list_error_traces(
    error_type: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    filters: Dict[str, Any] = {"has_error": True}
    if error_type:
        filters["error_type"] = error_type
    traces = trace_storage.list_traces(limit=limit, offset=offset, filters=filters)
    return {"count": len(traces), "traces": traces}


@router.get("/search/slow", summary="List slow traces above a latency threshold")
async def list_slow_traces(
    threshold_ms: float = Query(2000.0, description="Latency threshold in ms"),
    limit: int = Query(50, ge=1, le=500),
):
    traces = trace_storage.list_traces(
        limit=limit,
        filters={"min_latency_ms": threshold_ms},
        order_by="latency_total_ms",
        order_dir="DESC",
    )
    return {"count": len(traces), "threshold_ms": threshold_ms, "traces": traces}
