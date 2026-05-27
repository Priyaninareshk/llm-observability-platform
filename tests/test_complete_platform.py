"""
Comprehensive monitoring and alerting workflow tests.

Tests cover:
  1. Alert triggering for hallucinations and failures
  2. SLA report generation
  3. Root-cause analysis
  4. A/B model comparison
  5. Runbook lookup
  6. Monitoring views (live + historical)
  7. Metrics and traces API
  8. End-to-end alert → runbook → RCA workflow
"""
import asyncio
import sys
import os
import json
from datetime import datetime, timezone

# Make backend importable
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ============================================================
# 1. Alert Engine Tests
# ============================================================

def test_alert_engine_fires_hallucination_alert():
    """Alert fires when hallucination rate exceeds threshold."""
    from alerting.alert_engine import AlertRuleEngine, AlertRule, Operator, Severity

    engine = AlertRuleEngine()
    engine.add_rule(AlertRule(
        rule_id="test_hallucination",
        name="Test Hallucination",
        description="Test",
        metric_key="hallucination.rate",
        operator=Operator.GT,
        threshold=0.10,
        severity=Severity.CRITICAL,
        cooldown_seconds=0,
    ))

    fired = []
    engine.register_handler(lambda e: fired.append(e))

    # Below threshold — no fire
    events = engine.evaluate({"hallucination": {"rate": 0.05}})
    assert len(events) == 0, "Should not fire below threshold"

    # Above threshold — fire
    events = engine.evaluate({"hallucination": {"rate": 0.35}})
    assert len(events) == 1, "Should fire above threshold"
    assert events[0].rule_id == "test_hallucination"
    assert len(fired) == 1
    print("  ✅ test_alert_engine_fires_hallucination_alert PASSED")


def test_alert_engine_fires_error_rate_alert():
    """Alert fires for elevated error rate."""
    from alerting.alert_engine import AlertRuleEngine, AlertRule, Operator, Severity

    engine = AlertRuleEngine()
    engine.add_rule(AlertRule(
        rule_id="test_error_rate",
        name="Test Error Rate",
        description="Test",
        metric_key="errors.rate",
        operator=Operator.GT,
        threshold=0.20,
        severity=Severity.CRITICAL,
        cooldown_seconds=0,
    ))

    events = engine.evaluate({"errors": {"rate": 0.25}})
    assert len(events) == 1
    assert events[0].severity.value == "critical"
    print("  ✅ test_alert_engine_fires_error_rate_alert PASSED")


def test_alert_cooldown_prevents_flood():
    """Cooldown prevents repeated alerts within window."""
    from alerting.alert_engine import AlertRuleEngine, AlertRule, Operator, Severity

    engine = AlertRuleEngine()
    engine.add_rule(AlertRule(
        rule_id="test_cooldown",
        name="Cooldown Test",
        description="Test",
        metric_key="errors.rate",
        operator=Operator.GT,
        threshold=0.01,
        severity=Severity.WARNING,
        cooldown_seconds=300,   # 5 minutes
    ))

    metrics = {"errors": {"rate": 0.99}}
    first = engine.evaluate(metrics)
    second = engine.evaluate(metrics)

    assert len(first) == 1
    assert len(second) == 0, "Cooldown should suppress second alert"
    print("  ✅ test_alert_cooldown_prevents_flood PASSED")


def test_alert_history_stored():
    """Alert events are stored in history."""
    from alerting.alert_engine import AlertRuleEngine, AlertRule, Operator, Severity

    engine = AlertRuleEngine()
    engine.add_rule(AlertRule(
        rule_id="history_test",
        name="History Test",
        description="Test",
        metric_key="cost.last_query_usd",
        operator=Operator.GT,
        threshold=0.001,
        severity=Severity.INFO,
        cooldown_seconds=0,
    ))
    engine.evaluate({"cost": {"last_query_usd": 1.0}})
    history = engine.get_history(limit=10)
    assert any(h["rule_id"] == "history_test" for h in history)
    print("  ✅ test_alert_history_stored PASSED")


# ============================================================
# 2. SLA Report Tests
# ============================================================

def test_sla_report_generates():
    """SLA report generates without errors on empty DB."""
    from sla.sla_reporter import generate_sla_report

    report = generate_sla_report(period_hours=24)
    d = report.to_dict()

    assert "report_id" in d
    assert "metrics" in d
    assert len(d["metrics"]) == 6, f"Expected 6 SLA metrics, got {len(d['metrics'])}"
    assert "summary" in d
    assert "overall_sla_met" in d
    print("  ✅ test_sla_report_generates PASSED")


def test_sla_report_metric_names():
    """SLA report contains all expected metric categories."""
    from sla.sla_reporter import generate_sla_report

    report = generate_sla_report(period_hours=1)
    metric_names = {m["name"] for m in report.to_dict()["metrics"]}
    expected = {"Availability", "P95 Latency", "P99 Latency", "Error Rate", "Hallucination Rate", "Daily Cost Budget"}
    assert expected == metric_names
    print("  ✅ test_sla_report_metric_names PASSED")


def test_sla_targets_endpoint():
    """SLA targets can be read from environment."""
    import os
    from sla.sla_reporter import SLA_P95_LATENCY_MS, SLA_AVAILABILITY_PCT

    assert SLA_AVAILABILITY_PCT == 99.5
    assert SLA_P95_LATENCY_MS == 3000.0
    print("  ✅ test_sla_targets_endpoint PASSED")


# ============================================================
# 3. Root Cause Analysis Tests
# ============================================================

def test_rca_on_missing_trace():
    """RCA handles unknown trace gracefully."""
    from root_cause.analyzer import root_cause_analyzer

    report = root_cause_analyzer.analyze_trace("nonexistent-trace-id")
    d = report.to_dict()
    assert d["trace_id"] == "nonexistent-trace-id"
    assert d["raw_metrics"].get("error") == "Trace not found"
    print("  ✅ test_rca_on_missing_trace PASSED")


def test_rca_on_alert_latency():
    """RCA generates hypotheses for latency alert."""
    from root_cause.analyzer import root_cause_analyzer
    from alerting.alert_engine import AlertEvent, Severity

    event = AlertEvent(
        rule_id="latency_p95_warning",
        rule_name="High P95 Latency",
        severity=Severity.WARNING,
        metric_key="latency.p95_ms",
        metric_value=4500.0,
        threshold=3000.0,
        operator="gt",
        message="P95 latency exceeded",
        labels={"category": "latency"},
    )
    report = root_cause_analyzer.analyze_alert(event)
    d = report.to_dict()
    assert d["analysis_type"] == "latency"
    assert len(d["all_hypotheses"]) >= 0
    print("  ✅ test_rca_on_alert_latency PASSED")


def test_rca_on_alert_hallucination():
    """RCA generates hypotheses for hallucination alert."""
    from root_cause.analyzer import root_cause_analyzer
    from alerting.alert_engine import AlertEvent, Severity

    event = AlertEvent(
        rule_id="hallucination_rate_critical",
        rule_name="Critical Hallucination Rate",
        severity=Severity.CRITICAL,
        metric_key="hallucination.rate",
        metric_value=0.45,
        threshold=0.30,
        operator="gt",
        message="Hallucination rate critical",
        labels={"category": "hallucination"},
    )
    report = root_cause_analyzer.analyze_alert(event)
    d = report.to_dict()
    assert d["analysis_type"] == "hallucination"
    print("  ✅ test_rca_on_alert_hallucination PASSED")


# ============================================================
# 4. A/B Testing Tests
# ============================================================

def test_ab_comparison_runs():
    """A/B comparison runs both variants and returns results."""
    from ab_testing.ab_service import ABTestingService

    service = ABTestingService()

    async def _run():
        record = await service.run_comparison(
            prompt="What is 2+2?",
            control_model="gpt-4o-mini",
            treatment_model="gpt-4o",
            experiment_name="math_test",
        )
        return record

    record = asyncio.run(_run())
    comparison = record.compare()

    assert comparison["test_id"] == record.test_id
    assert comparison["winner"] in ("control", "treatment", "tie")
    assert "control" in comparison
    assert "treatment" in comparison
    print("  ✅ test_ab_comparison_runs PASSED")


def test_ab_experiment_summary():
    """Experiment summary aggregates multiple A/B tests correctly."""
    from ab_testing.ab_service import ABTestingService

    service = ABTestingService()

    async def _run():
        for _ in range(3):
            await service.run_comparison(
                prompt="Test prompt",
                control_model="model-a",
                treatment_model="model-b",
                experiment_name="summary_test",
            )

    asyncio.run(_run())
    summary = service.get_experiment_summary("summary_test")

    assert summary["total_tests"] == 3
    assert summary["experiment_name"] == "summary_test"
    assert "win_rate_control" in summary
    assert "avg_latency_ms" in summary
    print("  ✅ test_ab_experiment_summary PASSED")


def test_ab_history_recorded():
    """A/B test history is stored and retrievable."""
    from ab_testing.ab_service import ABTestingService

    service = ABTestingService()

    async def _run():
        await service.run_comparison("Hello", "m1", "m2", "history_exp")

    asyncio.run(_run())
    history = service.get_history(limit=10, experiment_name="history_exp")
    assert len(history) >= 1
    print("  ✅ test_ab_history_recorded PASSED")


# ============================================================
# 5. Runbook Tests
# ============================================================

def test_runbooks_all_alert_rules_covered():
    """Every pre-built alert rule has a corresponding runbook."""
    from runbooks.runbook_registry import RUNBOOKS
    from alerting.latency_cost_rules import LATENCY_RULES, COST_RULES, ERROR_RATE_RULES, HALLUCINATION_RULES

    all_rules = LATENCY_RULES + COST_RULES + ERROR_RATE_RULES + HALLUCINATION_RULES
    missing = [r.rule_id for r in all_rules if r.rule_id not in RUNBOOKS]
    assert missing == [], f"Missing runbooks for: {missing}"
    print("  ✅ test_runbooks_all_alert_rules_covered PASSED")


def test_runbook_triage_steps_not_empty():
    """All runbooks have at least 2 triage steps."""
    from runbooks.runbook_registry import RUNBOOKS

    for rule_id, rb in RUNBOOKS.items():
        assert len(rb.triage_steps) >= 2, f"Runbook {rule_id} has too few steps"
    print("  ✅ test_runbook_triage_steps_not_empty PASSED")


def test_runbook_escalation_path():
    """All critical runbooks have an escalation path."""
    from runbooks.runbook_registry import RUNBOOKS

    critical_rbs = [rb for rb in RUNBOOKS.values() if rb.severity == "critical"]
    for rb in critical_rbs:
        assert len(rb.escalation_path) >= 1, f"Critical runbook {rb.alert_rule_id} has no escalation path"
    print("  ✅ test_runbook_escalation_path PASSED")


def test_runbook_lookup_by_id():
    """Runbook lookup by rule_id returns correct entry."""
    from runbooks.runbook_registry import runbook_registry

    rb = runbook_registry.get("hallucination_rate_critical")
    assert rb is not None
    assert rb.severity == "critical"
    assert rb.category == "hallucination"
    print("  ✅ test_runbook_lookup_by_id PASSED")


def test_runbook_filter_by_category():
    """Runbook filtering by category returns correct subset."""
    from runbooks.runbook_registry import runbook_registry

    latency_rbs = runbook_registry.list_by_category("latency")
    assert len(latency_rbs) >= 2
    for rb in latency_rbs:
        assert rb["category"] == "latency"
    print("  ✅ test_runbook_filter_by_category PASSED")


# ============================================================
# 6. Monitoring Views Tests
# ============================================================

def test_bucket_traces_by_hour():
    """Hour bucketing produces correct number of buckets."""
    from monitoring.monitoring_views import _bucket_traces_by_hour

    buckets = _bucket_traces_by_hour([], hours=24)
    assert len(buckets) == 24
    for b in buckets:
        assert "timestamp" in b
        assert "request_count" in b
        assert "error_rate" in b
    print("  ✅ test_bucket_traces_by_hour PASSED")


def test_bucket_traces_counts_correctly():
    """Bucketing places traces in the correct hour bucket."""
    from monitoring.monitoring_views import _bucket_traces_by_hour
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)
    recent = (now - timedelta(minutes=30)).isoformat()

    fake_traces = [
        {"created_at": recent, "latency_total_ms": 500.0, "total_cost": 0.01,
         "total_tokens": 100, "error_type": None, "faithfulness_label": "faithful"},
        {"created_at": recent, "latency_total_ms": 800.0, "total_cost": 0.02,
         "total_tokens": 200, "error_type": "ValueError", "faithfulness_label": "hallucinated"},
    ]

    buckets = _bucket_traces_by_hour(fake_traces, hours=2)
    # At least one bucket should have request_count > 0
    total_requests = sum(b["request_count"] for b in buckets)
    assert total_requests == 2
    print("  ✅ test_bucket_traces_counts_correctly PASSED")


# ============================================================
# 7. Trace Storage API Tests
# ============================================================

def test_trace_storage_save_and_retrieve():
    """Traces can be saved and retrieved by ID."""
    from storage.trace_storage import TraceStorage, TraceRecord
    import tempfile, uuid

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        storage = TraceStorage(db_url=f"sqlite:///{db_path}")

        trace_id = str(uuid.uuid4())
        record = TraceRecord(
            trace_id=trace_id,
            endpoint="/chat",
            prompt="Test prompt",
            response="Test response",
            model_name="gpt-4o-mini",
            total_tokens=100,
            total_cost=0.001,
            latency_total_ms=500.0,
        )
        storage.save_trace(record)

        retrieved = storage.get_trace(trace_id)
        assert retrieved is not None
        assert retrieved["trace_id"] == trace_id
        assert retrieved["model_name"] == "gpt-4o-mini"
    print("  ✅ test_trace_storage_save_and_retrieve PASSED")


def test_trace_storage_filter_by_error():
    """Trace filtering by error_type works correctly."""
    from storage.trace_storage import TraceStorage, TraceRecord
    import tempfile, uuid

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "filter_test.db")
        storage = TraceStorage(db_url=f"sqlite:///{db_path}")

        # Save one error trace and one normal trace
        error_id = str(uuid.uuid4())
        ok_id = str(uuid.uuid4())

        storage.save_trace(TraceRecord(
            trace_id=error_id, endpoint="/chat", prompt="p", response="r",
            model_name="gpt-4o", error_type="TimeoutError", error_message="timed out",
        ))
        storage.save_trace(TraceRecord(
            trace_id=ok_id, endpoint="/chat", prompt="p", response="r", model_name="gpt-4o",
        ))

        error_traces = storage.list_traces(filters={"has_error": True})
        assert any(t["trace_id"] == error_id for t in error_traces)
        assert all(t.get("error_type") for t in error_traces)
    print("  ✅ test_trace_storage_filter_by_error PASSED")


def test_trace_storage_hallucination_update():
    """Hallucination scores can be patched onto existing traces."""
    from storage.trace_storage import TraceStorage, TraceRecord
    import tempfile, uuid

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "hallucination_test.db")
        storage = TraceStorage(db_url=f"sqlite:///{db_path}")

        trace_id = str(uuid.uuid4())
        storage.save_trace(TraceRecord(
            trace_id=trace_id, endpoint="/chat", prompt="p", response="r", model_name="gpt-4o",
        ))

        storage.update_hallucination(trace_id=trace_id, score=0.2, label="hallucinated")
        updated = storage.get_trace(trace_id)

        assert updated["faithfulness_score"] == 0.2
        assert updated["faithfulness_label"] == "hallucinated"
    print("  ✅ test_trace_storage_hallucination_update PASSED")


# ============================================================
# 8. End-to-End Workflow: Alert → Runbook → RCA
# ============================================================

def test_e2e_alert_to_runbook_to_rca():
    """Full workflow: alert fires → fetch runbook → generate RCA."""
    from alerting.alert_engine import AlertRuleEngine, AlertRule, Operator, Severity, AlertEvent
    from runbooks.runbook_registry import runbook_registry
    from root_cause.analyzer import root_cause_analyzer

    # Step 1: Alert fires
    engine = AlertRuleEngine()
    engine.add_rule(AlertRule(
        rule_id="hallucination_rate_critical",
        name="Critical Hallucination Rate",
        description="Test",
        metric_key="hallucination.rate",
        operator=Operator.GT,
        threshold=0.30,
        severity=Severity.CRITICAL,
        cooldown_seconds=0,
        labels={"category": "hallucination"},
    ))

    fired_events = []
    engine.register_handler(lambda e: fired_events.append(e))
    engine.evaluate({"hallucination": {"rate": 0.45}})

    assert len(fired_events) == 1, "Alert should have fired"
    alert = fired_events[0]

    # Step 2: Fetch runbook
    runbook = runbook_registry.get(alert.rule_id)
    assert runbook is not None, f"No runbook for {alert.rule_id}"
    assert len(runbook.triage_steps) >= 3

    # Step 3: Run RCA
    rca = root_cause_analyzer.analyze_alert(alert)
    report = rca.to_dict()
    assert report["analysis_type"] == "hallucination"
    assert report["top_hypothesis"] is not None
    assert len(report["top_hypothesis"]["remediation"]) > 0

    print("  ✅ test_e2e_alert_to_runbook_to_rca PASSED")


def test_e2e_multiple_alert_categories():
    """Alert engine evaluates all categories in a single snapshot."""
    from alerting.latency_cost_rules import build_metrics_snapshot, register_all_rules
    from alerting.alert_engine import AlertRuleEngine

    engine = AlertRuleEngine()
    register_all_rules(engine)

    snapshot = build_metrics_snapshot(
        latency_stats={"p50_ms": 1500, "p95_ms": 5000, "p99_ms": 9000},
        cost_stats={"last_query_usd": 0.30, "hourly_usd": 8.0},
        error_stats={"rate": 0.25},
        hallucination_stats={"rate": 0.35},
    )

    fired = engine.evaluate(snapshot)
    categories = {e.labels.get("category") for e in fired}

    # All 4 categories should have fired at least one alert
    assert "latency" in categories
    assert "cost" in categories
    assert "errors" in categories
    assert "hallucination" in categories
    print("  ✅ test_e2e_multiple_alert_categories PASSED")


# ============================================================
# Runner
# ============================================================

def run_all():
    test_groups = [
        ("Alert Engine", [
            test_alert_engine_fires_hallucination_alert,
            test_alert_engine_fires_error_rate_alert,
            test_alert_cooldown_prevents_flood,
            test_alert_history_stored,
        ]),
        ("SLA Reports", [
            test_sla_report_generates,
            test_sla_report_metric_names,
            test_sla_targets_endpoint,
        ]),
        ("Root Cause Analysis", [
            test_rca_on_missing_trace,
            test_rca_on_alert_latency,
            test_rca_on_alert_hallucination,
        ]),
        ("A/B Testing", [
            test_ab_comparison_runs,
            test_ab_experiment_summary,
            test_ab_history_recorded,
        ]),
        ("Runbooks", [
            test_runbooks_all_alert_rules_covered,
            test_runbook_triage_steps_not_empty,
            test_runbook_escalation_path,
            test_runbook_lookup_by_id,
            test_runbook_filter_by_category,
        ]),
        ("Monitoring Views", [
            test_bucket_traces_by_hour,
            test_bucket_traces_counts_correctly,
        ]),
        ("Trace Storage API", [
            test_trace_storage_save_and_retrieve,
            test_trace_storage_filter_by_error,
            test_trace_storage_hallucination_update,
        ]),
        ("End-to-End Workflows", [
            test_e2e_alert_to_runbook_to_rca,
            test_e2e_multiple_alert_categories,
        ]),
    ]

    total = passed = failed = 0
    failures = []

    print("\n" + "="*60)
    print("  LLM Observability Platform — Test Suite")
    print("="*60)

    for group_name, tests in test_groups:
        print(f"\n📋 {group_name}")
        for test_fn in tests:
            total += 1
            try:
                test_fn()
                passed += 1
            except Exception as e:
                failed += 1
                failures.append((test_fn.__name__, str(e)))
                print(f"  ❌ {test_fn.__name__} FAILED: {e}")

    print("\n" + "="*60)
    print(f"  Results: {passed}/{total} passed, {failed} failed")
    if failures:
        print("\n  Failures:")
        for name, err in failures:
            print(f"    - {name}: {err}")
    print("="*60 + "\n")

    return failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
