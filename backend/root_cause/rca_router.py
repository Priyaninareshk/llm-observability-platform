"""FastAPI router for root-cause analysis endpoints."""
from fastapi import APIRouter, HTTPException

from root_cause.analyzer import root_cause_analyzer

router = APIRouter(prefix="/root-cause", tags=["root-cause"])


@router.get("/trace/{trace_id}", summary="Root-cause analysis for a specific trace")
async def analyze_trace(trace_id: str):
    """
    Inspects a single trace and returns ranked root-cause hypotheses
    with remediation suggestions.
    """
    report = root_cause_analyzer.analyze_trace(trace_id)
    return report.to_dict()


@router.get("/latest-errors", summary="Root-cause for most recent error traces")
async def analyze_latest_errors(limit: int = 10):
    """
    Runs root-cause analysis across the most recent error traces.
    """
    from storage.trace_storage import trace_storage
    error_traces = trace_storage.list_traces(
        limit=limit,
        filters={"has_error": True},
        order_by="created_at",
        order_dir="DESC",
    )
    reports = []
    for t in error_traces:
        report = root_cause_analyzer.analyze_trace(t["trace_id"])
        reports.append(report.to_dict())
    return {"count": len(reports), "analyses": reports}


@router.get("/latest-hallucinations", summary="Root-cause for recent hallucinated traces")
async def analyze_latest_hallucinations(limit: int = 10):
    """
    Root-cause analysis for the most recently detected hallucinated responses.
    """
    from storage.trace_storage import trace_storage
    hal_traces = trace_storage.list_traces(
        limit=limit,
        filters={"faithfulness_label": "hallucinated"},
        order_by="created_at",
        order_dir="DESC",
    )
    reports = []
    for t in hal_traces:
        report = root_cause_analyzer.analyze_trace(t["trace_id"])
        reports.append(report.to_dict())
    return {"count": len(reports), "analyses": reports}
