from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from alerting.alert_engine import AlertRule, Operator, Severity, alert_engine
from alerting.notification_channels import dispatcher

router = APIRouter(prefix="/alerts", tags=["alerts"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class RuleCreateRequest(BaseModel):
    rule_id: str
    name: str
    description: str
    metric_key: str
    operator: str
    threshold: float
    severity: str = "warning"
    cooldown_seconds: int = 300
    labels: Dict[str, str] = {}


class ThresholdUpdateRequest(BaseModel):
    threshold: float


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/rules", summary="List all alert rules")
async def list_rules():
    return alert_engine.active_rules_summary()


@router.post("/rules", summary="Create a new alert rule")
async def create_rule(body: RuleCreateRequest):
    try:
        op = Operator(body.operator)
        sev = Severity(body.severity)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    rule = AlertRule(
        rule_id=body.rule_id,
        name=body.name,
        description=body.description,
        metric_key=body.metric_key,
        operator=op,
        threshold=body.threshold,
        severity=sev,
        cooldown_seconds=body.cooldown_seconds,
        labels=body.labels,
    )
    alert_engine.add_rule(rule)
    return {"message": "Rule created", "rule_id": rule.rule_id}


@router.patch("/rules/{rule_id}/threshold", summary="Update a rule threshold")
async def update_threshold(rule_id: str, body: ThresholdUpdateRequest):
    ok = alert_engine.update_threshold(rule_id, body.threshold)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Rule '{rule_id}' not found")
    return {"message": "Threshold updated", "rule_id": rule_id, "new_threshold": body.threshold}


@router.delete("/rules/{rule_id}", summary="Remove an alert rule")
async def delete_rule(rule_id: str):
    ok = alert_engine.remove_rule(rule_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Rule '{rule_id}' not found")
    return {"message": "Rule removed", "rule_id": rule_id}


@router.get("/history", summary="Alert event history")
async def alert_history(limit: int = Query(100, ge=1, le=500)):
    return alert_engine.get_history(limit=limit)


@router.get("/notifications", summary="Notification delivery receipts")
async def notification_receipts(limit: int = Query(100, ge=1, le=500)):
    return dispatcher.get_receipts(limit=limit)


@router.post("/test/{rule_id}", summary="Fire a test alert for a rule")
async def test_alert(rule_id: str):
    """Manually trigger a rule to test notification delivery."""
    rule = alert_engine.get_rule(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail=f"Rule '{rule_id}' not found")

    from alerting.alert_engine import AlertEvent
    from datetime import datetime, timezone

    fake_event = AlertEvent(
        rule_id=rule.rule_id,
        rule_name=rule.name,
        severity=rule.severity,
        metric_key=rule.metric_key,
        metric_value=rule.threshold + 1.0,
        threshold=rule.threshold,
        operator=rule.operator.value,
        message=f"[TEST] {rule.name}: manually triggered",
        labels=rule.labels,
    )
    receipts = await dispatcher.dispatch(fake_event)
    return {
        "message": "Test alert fired",
        "rule_id": rule_id,
        "receipts": [
            {"channel": r.channel_name, "success": r.success, "status_code": r.status_code}
            for r in receipts
        ],
    }
