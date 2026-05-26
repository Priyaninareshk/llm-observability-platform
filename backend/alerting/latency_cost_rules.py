import os
import logging

from alerting.alert_engine import AlertRule, AlertRuleEngine, Operator, Severity, alert_engine
from alerting.notification_channels import dispatcher

logger = logging.getLogger("llm_observability.alerting.rules")


# ---------------------------------------------------------------------------
# Thresholds (overridable via env vars)
# ---------------------------------------------------------------------------

LATENCY_P50_WARN_MS   = float(os.getenv("ALERT_LATENCY_P50_WARN_MS",  "1000"))
LATENCY_P95_WARN_MS   = float(os.getenv("ALERT_LATENCY_P95_WARN_MS",  "3000"))
LATENCY_P99_CRIT_MS   = float(os.getenv("ALERT_LATENCY_P99_CRIT_MS",  "6000"))

COST_PER_QUERY_WARN   = float(os.getenv("ALERT_COST_PER_QUERY_WARN",  "0.05"))
COST_PER_QUERY_CRIT   = float(os.getenv("ALERT_COST_PER_QUERY_CRIT",  "0.20"))
COST_HOURLY_WARN      = float(os.getenv("ALERT_COST_HOURLY_WARN",     "1.00"))
COST_HOURLY_CRIT      = float(os.getenv("ALERT_COST_HOURLY_CRIT",     "5.00"))

ERROR_RATE_WARN       = float(os.getenv("ALERT_ERROR_RATE_WARN",      "0.05"))   # 5 %
ERROR_RATE_CRIT       = float(os.getenv("ALERT_ERROR_RATE_CRIT",      "0.20"))   # 20 %

HALLUCINATION_WARN    = float(os.getenv("ALERT_HALLUCINATION_RATE_WARN", "0.10"))  # 10 %
HALLUCINATION_CRIT    = float(os.getenv("ALERT_HALLUCINATION_RATE_CRIT", "0.30"))  # 30 %


# ---------------------------------------------------------------------------
# Rule definitions
# ---------------------------------------------------------------------------

LATENCY_RULES = [
    AlertRule(
        rule_id="latency_p50_warning",
        name="High P50 Latency",
        description="Median response latency is above warning threshold.",
        metric_key="latency.p50_ms",
        operator=Operator.GT,
        threshold=LATENCY_P50_WARN_MS,
        severity=Severity.WARNING,
        cooldown_seconds=300,
        labels={"category": "latency", "percentile": "p50"},
    ),
    AlertRule(
        rule_id="latency_p95_warning",
        name="High P95 Latency",
        description="95th percentile response latency exceeded.",
        metric_key="latency.p95_ms",
        operator=Operator.GT,
        threshold=LATENCY_P95_WARN_MS,
        severity=Severity.WARNING,
        cooldown_seconds=180,
        labels={"category": "latency", "percentile": "p95"},
    ),
    AlertRule(
        rule_id="latency_p99_critical",
        name="Critical P99 Latency",
        description="99th percentile latency is critically high.",
        metric_key="latency.p99_ms",
        operator=Operator.GT,
        threshold=LATENCY_P99_CRIT_MS,
        severity=Severity.CRITICAL,
        cooldown_seconds=60,
        labels={"category": "latency", "percentile": "p99"},
    ),
]

COST_RULES = [
    AlertRule(
        rule_id="cost_per_query_warning",
        name="High Cost Per Query",
        description="Single query cost exceeded warning threshold.",
        metric_key="cost.last_query_usd",
        operator=Operator.GT,
        threshold=COST_PER_QUERY_WARN,
        severity=Severity.WARNING,
        cooldown_seconds=60,
        labels={"category": "cost", "scope": "per_query"},
    ),
    AlertRule(
        rule_id="cost_per_query_critical",
        name="Critical Cost Per Query",
        description="Single query cost is critically high.",
        metric_key="cost.last_query_usd",
        operator=Operator.GT,
        threshold=COST_PER_QUERY_CRIT,
        severity=Severity.CRITICAL,
        cooldown_seconds=30,
        labels={"category": "cost", "scope": "per_query"},
    ),
    AlertRule(
        rule_id="cost_hourly_warning",
        name="High Hourly Cost",
        description="Hourly API spend exceeded warning threshold.",
        metric_key="cost.hourly_usd",
        operator=Operator.GT,
        threshold=COST_HOURLY_WARN,
        severity=Severity.WARNING,
        cooldown_seconds=600,
        labels={"category": "cost", "scope": "hourly"},
    ),
    AlertRule(
        rule_id="cost_hourly_critical",
        name="Critical Hourly Cost",
        description="Hourly API spend is critically high – risk of budget overrun.",
        metric_key="cost.hourly_usd",
        operator=Operator.GT,
        threshold=COST_HOURLY_CRIT,
        severity=Severity.CRITICAL,
        cooldown_seconds=300,
        labels={"category": "cost", "scope": "hourly"},
    ),
]

ERROR_RATE_RULES = [
    AlertRule(
        rule_id="error_rate_warning",
        name="Elevated Error Rate",
        description="Application error rate exceeded warning level.",
        metric_key="errors.rate",
        operator=Operator.GT,
        threshold=ERROR_RATE_WARN,
        severity=Severity.WARNING,
        cooldown_seconds=300,
        labels={"category": "errors"},
    ),
    AlertRule(
        rule_id="error_rate_critical",
        name="Critical Error Rate",
        description="Application error rate is critically high.",
        metric_key="errors.rate",
        operator=Operator.GT,
        threshold=ERROR_RATE_CRIT,
        severity=Severity.CRITICAL,
        cooldown_seconds=60,
        labels={"category": "errors"},
    ),
]

HALLUCINATION_RULES = [
    AlertRule(
        rule_id="hallucination_rate_warning",
        name="Elevated Hallucination Rate",
        description="Fraction of hallucinated responses exceeded warning threshold.",
        metric_key="hallucination.rate",
        operator=Operator.GT,
        threshold=HALLUCINATION_WARN,
        severity=Severity.WARNING,
        cooldown_seconds=300,
        labels={"category": "hallucination"},
    ),
    AlertRule(
        rule_id="hallucination_rate_critical",
        name="Critical Hallucination Rate",
        description="Hallucination rate is critically high – response quality degraded.",
        metric_key="hallucination.rate",
        operator=Operator.GT,
        threshold=HALLUCINATION_CRIT,
        severity=Severity.CRITICAL,
        cooldown_seconds=120,
        labels={"category": "hallucination"},
    ),
]


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

def register_all_rules(engine: AlertRuleEngine = alert_engine) -> None:
    """Register all pre-configured rules and wire up the notification dispatcher."""
    all_rules = LATENCY_RULES + COST_RULES + ERROR_RATE_RULES + HALLUCINATION_RULES
    for rule in all_rules:
        engine.add_rule(rule)

    engine.register_handler(dispatcher.sync_dispatch)

    logger.info(
        "Alert rules registered: %d rules across latency/cost/error/hallucination categories",
        len(all_rules),
    )


def build_metrics_snapshot(
    latency_stats: dict,
    cost_stats: dict,
    error_stats: dict,
    hallucination_stats: dict,
) -> dict:
    """
    Assemble a flat/nested metrics dict from the platform's various stats
    sources so alert_engine.evaluate() can resolve metric keys.

    Expected inputs (all values in appropriate units):
      latency_stats:      {"p50_ms": ..., "p95_ms": ..., "p99_ms": ...}
      cost_stats:         {"last_query_usd": ..., "hourly_usd": ...}
      error_stats:        {"rate": ...}
      hallucination_stats:{"rate": ...}
    """
    return {
        "latency":      latency_stats,
        "cost":         cost_stats,
        "errors":       error_stats,
        "hallucination": hallucination_stats,
    }
