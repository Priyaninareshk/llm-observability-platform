import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("llm_observability.alerting")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class Operator(str, Enum):
    GT = "gt"    # >
    GTE = "gte"  # >=
    LT = "lt"    # <
    LTE = "lte"  # <=
    EQ = "eq"    # ==


@dataclass
class AlertRule:
    rule_id: str
    name: str
    description: str
    metric_key: str          # dotted path into the metrics dict, e.g. "latency.p95_ms"
    operator: Operator
    threshold: float
    severity: Severity = Severity.WARNING
    enabled: bool = True
    cooldown_seconds: int = 300   # minimum seconds between repeated fires
    labels: Dict[str, str] = field(default_factory=dict)

    def evaluate(self, value: float) -> bool:
        ops = {
            Operator.GT:  lambda v, t: v > t,
            Operator.GTE: lambda v, t: v >= t,
            Operator.LT:  lambda v, t: v < t,
            Operator.LTE: lambda v, t: v <= t,
            Operator.EQ:  lambda v, t: v == t,
        }
        return ops[self.operator](value, self.threshold)


@dataclass
class AlertEvent:
    rule_id: str
    rule_name: str
    severity: Severity
    metric_key: str
    metric_value: float
    threshold: float
    operator: str
    message: str
    labels: Dict[str, str] = field(default_factory=dict)
    fired_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    resolved: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class AlertRuleEngine:
    """
    Evaluates a set of AlertRules against a metrics snapshot.

    Usage
    -----
    engine = AlertRuleEngine()
    engine.add_rule(AlertRule(...))
    fired = engine.evaluate(metrics_dict)
    """

    def __init__(self):
        self._rules: Dict[str, AlertRule] = {}
        self._last_fired: Dict[str, float] = {}   # rule_id -> epoch
        self._history: List[AlertEvent] = []       # last 500 events
        self._handlers: List[Callable[[AlertEvent], None]] = []

    # ------------------------------------------------------------------
    # Rule management
    # ------------------------------------------------------------------

    def add_rule(self, rule: AlertRule) -> None:
        self._rules[rule.rule_id] = rule
        logger.info("Alert rule registered: %s (%s)", rule.rule_id, rule.name)

    def remove_rule(self, rule_id: str) -> bool:
        if rule_id in self._rules:
            del self._rules[rule_id]
            return True
        return False

    def get_rules(self) -> List[AlertRule]:
        return list(self._rules.values())

    def get_rule(self, rule_id: str) -> Optional[AlertRule]:
        return self._rules.get(rule_id)

    def update_threshold(self, rule_id: str, threshold: float) -> bool:
        if rule_id in self._rules:
            self._rules[rule_id].threshold = threshold
            return True
        return False

    # ------------------------------------------------------------------
    # Handler registration
    # ------------------------------------------------------------------

    def register_handler(self, fn: Callable[[AlertEvent], None]) -> None:
        """Register a sync callback to receive fired AlertEvents."""
        self._handlers.append(fn)

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def evaluate(self, metrics: Dict[str, Any]) -> List[AlertEvent]:
        """
        Evaluate all enabled rules against a flat or nested metrics dict.
        Returns list of AlertEvents that fired in this pass.
        """
        fired: List[AlertEvent] = []

        for rule in self._rules.values():
            if not rule.enabled:
                continue

            value = self._resolve_metric(metrics, rule.metric_key)
            if value is None:
                continue

            if not rule.evaluate(value):
                continue

            # Cooldown check
            last = self._last_fired.get(rule.rule_id, 0)
            if time.time() - last < rule.cooldown_seconds:
                continue

            self._last_fired[rule.rule_id] = time.time()

            event = AlertEvent(
                rule_id=rule.rule_id,
                rule_name=rule.name,
                severity=rule.severity,
                metric_key=rule.metric_key,
                metric_value=value,
                threshold=rule.threshold,
                operator=rule.operator.value,
                message=(
                    f"[{rule.severity.upper()}] {rule.name}: "
                    f"{rule.metric_key} = {value:.4f} "
                    f"{rule.operator.value} {rule.threshold}"
                ),
                labels=rule.labels,
            )

            self._history.append(event)
            if len(self._history) > 500:
                self._history.pop(0)

            logger.warning("ALERT FIRED: %s", event.message)
            fired.append(event)

            for handler in self._handlers:
                try:
                    handler(event)
                except Exception as exc:
                    logger.error("Alert handler error: %s", exc)

        return fired

    # ------------------------------------------------------------------
    # History & status
    # ------------------------------------------------------------------

    def get_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        return [e.to_dict() for e in self._history[-limit:]]

    def active_rules_summary(self) -> List[Dict[str, Any]]:
        return [
            {
                "rule_id": r.rule_id,
                "name": r.name,
                "metric_key": r.metric_key,
                "operator": r.operator.value,
                "threshold": r.threshold,
                "severity": r.severity.value,
                "enabled": r.enabled,
                "cooldown_seconds": r.cooldown_seconds,
            }
            for r in self._rules.values()
        ]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_metric(metrics: Dict[str, Any], key: str) -> Optional[float]:
        """Resolve dotted key path through a nested dict, e.g. 'latency.p95_ms'."""
        parts = key.split(".")
        obj: Any = metrics
        for part in parts:
            if not isinstance(obj, dict):
                return None
            obj = obj.get(part)
        try:
            return float(obj) if obj is not None else None
        except (TypeError, ValueError):
            return None


# Singleton
alert_engine = AlertRuleEngine()
