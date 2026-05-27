"""
Runbook Registry — structured operational procedures for every alert type.

Each runbook entry maps an alert rule_id to:
  - Severity
  - Triage steps
  - Diagnostic commands / API calls
  - Escalation path
  - Resolution verification
"""
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict


@dataclass
class RunbookStep:
    order: int
    title: str
    action: str
    expected_outcome: str
    tool_or_endpoint: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Runbook:
    alert_rule_id: str
    alert_name: str
    severity: str
    category: str
    description: str
    impact: str
    triage_steps: List[RunbookStep] = field(default_factory=list)
    escalation_path: List[str] = field(default_factory=list)
    resolution_check: str = ""
    references: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["triage_steps"] = [s.to_dict() for s in self.triage_steps]
        return d


# ---------------------------------------------------------------------------
# Runbook definitions
# ---------------------------------------------------------------------------

RUNBOOKS: Dict[str, Runbook] = {

    # ── LATENCY ────────────────────────────────────────────────────────────

    "latency_p50_warning": Runbook(
        alert_rule_id="latency_p50_warning",
        alert_name="High P50 Latency",
        severity="warning",
        category="latency",
        description="Median (P50) response latency exceeded 1000ms threshold.",
        impact="Most users are experiencing slower than normal responses.",
        triage_steps=[
            RunbookStep(1, "Check current trace stats", "GET /traces/stats", "Review avg_latency_ms field", "/traces/stats"),
            RunbookStep(2, "Identify slow traces", "GET /traces/search/slow?threshold_ms=1000", "List traces above threshold", "/traces/search/slow"),
            RunbookStep(3, "Run root-cause analysis", "GET /root-cause/trace/{trace_id}", "Get top hypothesis for slowest trace", "/root-cause/trace/"),
            RunbookStep(4, "Check model distribution", "Review model_name in recent traces", "Identify if a slow model is being used", "/traces"),
            RunbookStep(5, "Check prompt lengths", "Look for prompts > 2000 chars in slow traces", "Long prompts increase token processing time", None),
        ],
        escalation_path=["On-call engineer", "LLM platform team"],
        resolution_check="GET /traces/stats — avg_latency_ms should drop below 1000ms",
        references=["https://console.groq.com/docs/rate-limits", "Internal: model-routing-guide.md"],
    ),

    "latency_p95_warning": Runbook(
        alert_rule_id="latency_p95_warning",
        alert_name="High P95 Latency",
        severity="warning",
        category="latency",
        description="95th percentile latency exceeded 3000ms — tail latency is degraded.",
        impact="1 in 20 users are experiencing very slow responses.",
        triage_steps=[
            RunbookStep(1, "Identify P95 outliers", "GET /traces/search/slow?threshold_ms=3000", "Inspect slow traces", "/traces/search/slow"),
            RunbookStep(2, "Check upstream API status", "Visit https://status.groq.com", "Confirm no active incidents", None),
            RunbookStep(3, "Root-cause slowest trace", "GET /root-cause/trace/{trace_id}", "Get remediation suggestions", "/root-cause/trace/"),
            RunbookStep(4, "Review prompt complexity", "Check token counts in slow traces", "High completion_tokens drives latency", "/traces"),
            RunbookStep(5, "Consider streaming", "Enable streaming in LLMService if not active", "Reduces perceived latency for end users", None),
        ],
        escalation_path=["On-call engineer", "LLM platform team"],
        resolution_check="Monitor /traces/stats — p95 latency should return below 3000ms",
        references=[],
    ),

    "latency_p99_critical": Runbook(
        alert_rule_id="latency_p99_critical",
        alert_name="Critical P99 Latency",
        severity="critical",
        category="latency",
        description="P99 latency exceeded 6000ms — critical tail latency degradation.",
        impact="1 in 100 users are timing out or experiencing extreme slowness.",
        triage_steps=[
            RunbookStep(1, "IMMEDIATE: Check LLM provider status", "Visit https://status.groq.com", "Look for active incidents", None),
            RunbookStep(2, "List critical slow traces", "GET /traces/search/slow?threshold_ms=6000", "Find affected traces", "/traces/search/slow"),
            RunbookStep(3, "Check error rate correlation", "GET /traces/search/errors", "High errors + latency = possible cascade failure", "/traces/search/errors"),
            RunbookStep(4, "Enable request timeout", "Set LLM_TIMEOUT=5000 in env", "Fail fast instead of hanging", None),
            RunbookStep(5, "Consider fallback model", "Route to faster model (llama3-8b-8192)", "Temporary mitigation while investigating", None),
            RunbookStep(6, "Notify stakeholders", "Post to #incidents channel", "Communicate impact and ETA", None),
        ],
        escalation_path=["On-call engineer (immediate)", "Engineering manager", "CTO if >30 min"],
        resolution_check="P99 latency drops below 6000ms for at least 5 consecutive minutes",
        references=["Internal: incident-response-playbook.md"],
    ),

    # ── COST ───────────────────────────────────────────────────────────────

    "cost_per_query_warning": Runbook(
        alert_rule_id="cost_per_query_warning",
        alert_name="High Cost Per Query",
        severity="warning",
        category="cost",
        description="A single query cost >$0.05.",
        impact="Budget burn rate is higher than expected.",
        triage_steps=[
            RunbookStep(1, "Review cost report", "GET /reports/cost", "Check avg_cost_per_request_usd", "/reports/cost"),
            RunbookStep(2, "Find expensive traces", "GET /traces?order_by=total_cost&order_dir=DESC", "Identify outlier requests", "/traces"),
            RunbookStep(3, "Check token counts", "Look for high total_tokens in expensive traces", "Prompt or completion bloat", "/traces"),
            RunbookStep(4, "Run cost root-cause", "GET /root-cause/trace/{expensive_trace_id}", "Get remediation", "/root-cause/trace/"),
        ],
        escalation_path=["On-call engineer", "Product owner (if sustained)"],
        resolution_check="GET /reports/cost — avg_cost_per_request_usd below $0.05",
        references=[],
    ),

    "cost_per_query_critical": Runbook(
        alert_rule_id="cost_per_query_critical",
        alert_name="Critical Cost Per Query",
        severity="critical",
        category="cost",
        description="A single query cost >$0.20 — abnormally expensive.",
        impact="Potential runaway cost. May exhaust API budget quickly.",
        triage_steps=[
            RunbookStep(1, "Identify the expensive query", "GET /traces?order_by=total_cost&limit=1", "Find the most expensive trace", "/traces"),
            RunbookStep(2, "Check prompt length", "Review prompt in trace detail", "Likely huge context window usage", None),
            RunbookStep(3, "Enforce max_tokens", "Set MAX_COMPLETION_TOKENS=1000 in env", "Prevent runaway completions", None),
            RunbookStep(4, "Add rate limiting", "Enforce per-user request quotas", "Prevent abuse", None),
        ],
        escalation_path=["On-call engineer (immediate)", "Finance team alert"],
        resolution_check="No queries above $0.20 for 15 minutes",
        references=[],
    ),

    "cost_hourly_warning": Runbook(
        alert_rule_id="cost_hourly_warning",
        alert_name="High Hourly Cost",
        severity="warning",
        category="cost",
        description="Hourly API spend exceeded $1.00.",
        impact="Projected daily spend may exceed budget.",
        triage_steps=[
            RunbookStep(1, "Review SLA cost report", "GET /sla/report?period_hours=1", "Check cost budget adherence", "/sla/report"),
            RunbookStep(2, "Check request volume", "GET /traces/stats", "High volume may be expected or abuse", "/traces/stats"),
            RunbookStep(3, "Check A/B test for cost", "GET /ab/experiments", "A/B tests with expensive models inflate costs", "/ab/experiments"),
        ],
        escalation_path=["On-call engineer"],
        resolution_check="Hourly cost returns below $1.00",
        references=[],
    ),

    "cost_hourly_critical": Runbook(
        alert_rule_id="cost_hourly_critical",
        alert_name="Critical Hourly Cost",
        severity="critical",
        category="cost",
        description="Hourly API spend exceeded $5.00 — budget overrun risk.",
        impact="Daily budget will be exhausted in <10 hours at this rate.",
        triage_steps=[
            RunbookStep(1, "IMMEDIATE: Check for abuse", "GET /traces?order_by=created_at&limit=50", "Look for bot traffic or repeated queries", "/traces"),
            RunbookStep(2, "Enable rate limiting", "Set per-IP and per-user request limits", "Stop the bleed", None),
            RunbookStep(3, "Switch to cheaper model", "Route all requests to llama3-8b-8192 temporarily", "Reduce per-query cost 10x", None),
            RunbookStep(4, "Alert finance", "Send cost alert to finance team", "Budget awareness", None),
        ],
        escalation_path=["On-call engineer (immediate)", "Engineering manager", "Finance"],
        resolution_check="Hourly spend drops below $1.00",
        references=[],
    ),

    # ── ERRORS ─────────────────────────────────────────────────────────────

    "error_rate_warning": Runbook(
        alert_rule_id="error_rate_warning",
        alert_name="Elevated Error Rate",
        severity="warning",
        category="errors",
        description="Application error rate exceeded 5% in the sliding window.",
        impact="~1 in 20 user requests is failing.",
        triage_steps=[
            RunbookStep(1, "Review recent errors", "GET /traces/search/errors", "See error types and messages", "/traces/search/errors"),
            RunbookStep(2, "Check metrics endpoint", "GET /metrics", "Look for error counters", "/metrics"),
            RunbookStep(3, "Root-cause errors", "GET /root-cause/latest-errors", "Get ranked hypotheses", "/root-cause/latest-errors"),
            RunbookStep(4, "Check LLM provider status", "https://status.groq.com", "External outage?", None),
        ],
        escalation_path=["On-call engineer"],
        resolution_check="Error rate drops below 5% for 5 consecutive minutes",
        references=[],
    ),

    "error_rate_critical": Runbook(
        alert_rule_id="error_rate_critical",
        alert_name="Critical Error Rate",
        severity="critical",
        category="errors",
        description="Error rate exceeded 20% — major service degradation.",
        impact="1 in 5 user requests is failing. Service is degraded.",
        triage_steps=[
            RunbookStep(1, "IMMEDIATE: Assess blast radius", "GET /traces/stats", "How many total users affected?", "/traces/stats"),
            RunbookStep(2, "Identify error pattern", "GET /root-cause/latest-errors?limit=20", "Find dominant error type", "/root-cause/latest-errors"),
            RunbookStep(3, "Check upstream health", "https://status.groq.com", "External dependency failure", None),
            RunbookStep(4, "Enable circuit breaker", "Set CIRCUIT_BREAKER_ENABLED=true", "Return 503 instead of propagating failures", None),
            RunbookStep(5, "Page on-call engineer", "PagerDuty / OpsGenie escalation", "Human required", None),
            RunbookStep(6, "Post incident update", "#incidents Slack channel", "Communicate status", None),
        ],
        escalation_path=["On-call engineer (immediate)", "Engineering manager", "CTO"],
        resolution_check="Error rate stays below 10% for 10 minutes",
        references=["Internal: incident-response-playbook.md"],
    ),

    # ── HALLUCINATION ──────────────────────────────────────────────────────

    "hallucination_rate_warning": Runbook(
        alert_rule_id="hallucination_rate_warning",
        alert_name="Elevated Hallucination Rate",
        severity="warning",
        category="hallucination",
        description="Hallucination rate exceeded 10% of scored responses.",
        impact="~1 in 10 responses may contain fabricated information.",
        triage_steps=[
            RunbookStep(1, "View hallucinated traces", "GET /traces/search/hallucinated", "Inspect response content", "/traces/search/hallucinated"),
            RunbookStep(2, "Root-cause analysis", "GET /root-cause/latest-hallucinations", "Identify pattern", "/root-cause/latest-hallucinations"),
            RunbookStep(3, "Review prompts", "Check prompt templates for ambiguity", "Vague prompts produce hallucinations", None),
            RunbookStep(4, "Check faithfulness scores", "GET /traces?faithfulness_label=hallucinated", "Filter by score < 0.4", "/traces"),
        ],
        escalation_path=["On-call engineer", "ML/AI team"],
        resolution_check="Hallucination rate drops below 10% over 30 minutes",
        references=["https://arxiv.org/abs/2305.11747 — Survey of hallucinations in LLMs"],
    ),

    "hallucination_rate_critical": Runbook(
        alert_rule_id="hallucination_rate_critical",
        alert_name="Critical Hallucination Rate",
        severity="critical",
        category="hallucination",
        description="Hallucination rate exceeded 30% — response quality severely degraded.",
        impact="Nearly 1 in 3 responses is hallucinated. Users cannot trust responses.",
        triage_steps=[
            RunbookStep(1, "IMMEDIATE: Review recent hallucinated responses", "GET /traces/search/hallucinated?limit=20", "Assess severity and pattern", "/traces/search/hallucinated"),
            RunbookStep(2, "Run full root-cause", "GET /root-cause/latest-hallucinations?limit=20", "Get recommendations", "/root-cause/latest-hallucinations"),
            RunbookStep(3, "Reduce model temperature", "Set MODEL_TEMPERATURE=0.1 in env", "Lower temperature reduces hallucinations", None),
            RunbookStep(4, "Add factuality disclaimer", "Update system prompt with grounding instructions", "Tell the model to only state facts it is certain about", None),
            RunbookStep(5, "Consider disabling feature", "Route to fallback or disable affected endpoint", "Protect users until fixed", None),
            RunbookStep(6, "Notify product team", "Alert product owner about quality issue", "User trust at risk", None),
        ],
        escalation_path=["On-call engineer (immediate)", "ML team lead", "Product owner"],
        resolution_check="Hallucination rate stays below 10% for 30 consecutive minutes",
        references=[],
    ),
}


class RunbookRegistry:
    """Lookup and list runbooks."""

    def get(self, rule_id: str) -> Optional[Runbook]:
        return RUNBOOKS.get(rule_id)

    def list_all(self) -> List[Dict[str, Any]]:
        return [rb.to_dict() for rb in RUNBOOKS.values()]

    def list_by_severity(self, severity: str) -> List[Dict[str, Any]]:
        return [rb.to_dict() for rb in RUNBOOKS.values() if rb.severity == severity]

    def list_by_category(self, category: str) -> List[Dict[str, Any]]:
        return [rb.to_dict() for rb in RUNBOOKS.values() if rb.category == category]


runbook_registry = RunbookRegistry()
