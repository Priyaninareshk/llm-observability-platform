"""FastAPI router for runbook endpoints."""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from runbooks.runbook_registry import runbook_registry

router = APIRouter(prefix="/runbooks", tags=["runbooks"])


@router.get("", summary="List all runbooks")
async def list_runbooks(
    severity: Optional[str] = Query(None, description="Filter by: warning | critical | info"),
    category: Optional[str] = Query(None, description="Filter by: latency | errors | hallucination | cost"),
):
    if severity:
        return {"runbooks": runbook_registry.list_by_severity(severity)}
    if category:
        return {"runbooks": runbook_registry.list_by_category(category)}
    return {"runbooks": runbook_registry.list_all()}


@router.get("/{rule_id}", summary="Get runbook for a specific alert rule")
async def get_runbook(rule_id: str):
    """
    Returns the full operational runbook for a given alert rule_id,
    including triage steps, escalation path, and resolution verification.
    """
    rb = runbook_registry.get(rule_id)
    if not rb:
        raise HTTPException(status_code=404, detail=f"No runbook found for rule_id '{rule_id}'")
    return rb.to_dict()
