"""
Automated Root-Cause Explanation System.

Analyses trace data and alert events to produce structured root-cause
explanations with remediation suggestions.

Categories handled:
  - High latency (network, model, prompt length)
  - Elevated error rates (API errors, timeouts, validation)
  - Hallucination spikes (context quality, prompt issues)
  - Cost anomalies (prompt bloat, model selection, volume)
  - Cascading failures (error chains across requests)
"""
import logging
import statistics
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from storage.trace_storage import trace_storage
from alerting.alert_engine import AlertEvent

logger = logging.getLogger("llm_observability.root_cause")


@dataclass
class RootCauseHypothesis:
    category: str       # "latency" | "error" | "hallucination" | "cost"
    description: str    # Human-readable explanation
    confidence: float   # 0.0 – 1.0
    evidence: List[str] = field(default_factory=list)
    remediation: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RootCauseReport:
    trace_id: Optional[str]
    alert_event: Optional[str]   # serialised alert rule_id
    analysis_type: str
    hypotheses: List[RootCauseHypothesis] = field(default_factory=list)
    top_hypothesis: Optional[RootCauseHypothesis] = None
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    raw_metrics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "alert_event": self.alert_event,
            "analysis_type": self.analysis_type,
            "top_hypothesis": self.top_hypothesis.to_dict() if self.top_hypothesis else None,
            "all_hypotheses": [h.to_dict() for h in self.hypotheses],
            "generated_at": self.generated_at,
            "raw_metrics": self.raw_metrics,
        }


class RootCauseAnalyzer:
    """
    Rule-based root cause analyzer.  For each alert category, inspects
    recent trace data and generates ranked hypotheses.
    """

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def analyze_alert(self, alert_event: AlertEvent) -> RootCauseReport:
        """Produce a root-cause report for a fired alert."""
        category = alert_event.labels.get("category", "unknown")
        hypotheses: List[RootCauseHypothesis] = []
        raw_metrics: Dict[str, Any] = {}

        recent = trace_storage.list_traces(limit=100)

        if category == "latency":
            hypotheses, raw_metrics = self._analyze_latency(recent, alert_event)
        elif category == "errors":
            hypotheses, raw_metrics = self._analyze_errors(recent, alert_event)
        elif category == "hallucination":
            hypotheses, raw_metrics = self._analyze_hallucination(recent, alert_event)
        elif category == "cost":
            hypotheses, raw_metrics = self._analyze_cost(recent, alert_event)
        else:
            hypotheses = [RootCauseHypothesis(
                category="unknown",
                description=f"Alert category '{category}' has no dedicated analyzer.",
                confidence=0.3,
                evidence=["Unknown category"],
                remediation=["Review alert definition and add a custom analyzer."],
            )]

        hypotheses.sort(key=lambda h: h.confidence, reverse=True)
        top = hypotheses[0] if hypotheses else None

        return RootCauseReport(
            trace_id=None,
            alert_event=alert_event.rule_id,
            analysis_type=category,
            hypotheses=hypotheses,
            top_hypothesis=top,
            raw_metrics=raw_metrics,
        )

    def analyze_trace(self, trace_id: str) -> RootCauseReport:
        """Produce a root-cause report for a specific trace."""
        trace = trace_storage.get_trace(trace_id)
        if not trace:
            return RootCauseReport(
                trace_id=trace_id,
                alert_event=None,
                analysis_type="trace",
                raw_metrics={"error": "Trace not found"},
            )

        hypotheses: List[RootCauseHypothesis] = []
        recent = trace_storage.list_traces(limit=100)

        if trace.get("error_type"):
            hyps, _ = self._analyze_single_error(trace, recent)
            hypotheses.extend(hyps)

        if trace.get("latency_total_ms", 0) > 3000:
            hyps = self._latency_hypotheses_for_trace(trace, recent)
            hypotheses.extend(hyps)

        if trace.get("faithfulness_label") == "hallucinated":
            hypotheses.append(RootCauseHypothesis(
                category="hallucination",
                description="This trace was scored as hallucinated by the NLI pipeline.",
                confidence=0.9,
                evidence=[
                    f"faithfulness_score={trace.get('faithfulness_score', 'N/A')}",
                    "Label: hallucinated",
                ],
                remediation=[
                    "Review prompt for ambiguity or missing context.",
                    "Add retrieval-augmented generation (RAG) to ground responses.",
                    "Lower model temperature for factual queries.",
                ],
            ))

        if not hypotheses:
            hypotheses.append(RootCauseHypothesis(
                category="unknown",
                description="No obvious root cause detected for this trace.",
                confidence=0.2,
                evidence=[],
                remediation=["Inspect full trace payload for anomalies."],
            ))

        hypotheses.sort(key=lambda h: h.confidence, reverse=True)
        return RootCauseReport(
            trace_id=trace_id,
            alert_event=None,
            analysis_type="trace",
            hypotheses=hypotheses,
            top_hypothesis=hypotheses[0],
            raw_metrics=trace,
        )

    # ------------------------------------------------------------------ #
    # Category analyzers                                                   #
    # ------------------------------------------------------------------ #

    def _analyze_latency(self, traces, alert_event: AlertEvent):
        latencies = [t["latency_total_ms"] for t in traces if t.get("latency_total_ms")]
        llm_latencies = [t.get("latency_llm_ms", 0) for t in traces if t.get("latency_llm_ms")]
        avg_lat = statistics.mean(latencies) if latencies else 0
        avg_llm = statistics.mean(llm_latencies) if llm_latencies else 0
        long_prompts = [t for t in traces if len(t.get("prompt", "")) > 2000]
        models = [t.get("model_name", "unknown") for t in traces]
        model_counts = {m: models.count(m) for m in set(models)}

        hypotheses = []
        raw = {"avg_latency_ms": avg_lat, "avg_llm_ms": avg_llm, "long_prompts_count": len(long_prompts)}

        # Hypothesis 1: LLM inference is the bottleneck
        if avg_llm and avg_llm / avg_lat > 0.7:
            hypotheses.append(RootCauseHypothesis(
                category="latency",
                description="LLM inference accounts for >70% of total latency — model is the bottleneck.",
                confidence=0.85,
                evidence=[f"avg_llm_ms={avg_llm:.0f}", f"avg_total_ms={avg_lat:.0f}"],
                remediation=[
                    "Switch to a faster/cheaper model for non-critical requests.",
                    "Enable streaming to improve perceived latency.",
                    "Implement prompt caching for repeated queries.",
                ],
            ))

        # Hypothesis 2: Long prompts
        if len(long_prompts) > len(traces) * 0.2:
            hypotheses.append(RootCauseHypothesis(
                category="latency",
                description="Over 20% of recent requests have very long prompts (>2000 chars).",
                confidence=0.75,
                evidence=[f"long_prompt_count={len(long_prompts)}", f"total_traces={len(traces)}"],
                remediation=[
                    "Truncate or summarise context before sending to the LLM.",
                    "Use a model with faster throughput for long-context tasks.",
                    "Consider chunking large documents.",
                ],
            ))

        # Hypothesis 3: Slow model selected
        slow_models = [m for m, c in model_counts.items() if "groq" in m.lower() or "llama" in m.lower() and c > 5]
        if slow_models:
            hypotheses.append(RootCauseHypothesis(
                category="latency",
                description=f"High-latency model(s) in use: {slow_models}.",
                confidence=0.65,
                evidence=[f"model_distribution={model_counts}"],
                remediation=[
                    "Route simple queries to llama3-8b-8192 or a local model.",
                    "Use model routing based on prompt complexity.",
                ],
            ))

        return hypotheses, raw

    def _analyze_errors(self, traces, alert_event: AlertEvent):
        error_traces = [t for t in traces if t.get("error_type")]
        error_types = [t["error_type"] for t in error_traces]
        type_counts = {et: error_types.count(et) for et in set(error_types)}
        rate = len(error_traces) / len(traces) if traces else 0

        hypotheses = []
        raw = {"error_rate": rate, "error_types": type_counts, "total_errors": len(error_traces)}

        if "TimeoutError" in type_counts or "asyncio.TimeoutError" in type_counts:
            hypotheses.append(RootCauseHypothesis(
                category="errors",
                description="Timeout errors dominate — upstream LLM API is slow or unreachable.",
                confidence=0.88,
                evidence=[f"TimeoutError count={type_counts.get('TimeoutError', 0)}"],
                remediation=[
                    "Increase request timeout limits.",
                    "Add retry logic with exponential backoff.",
                    "Check OpenAI/LLM provider status page.",
                    "Implement circuit breaker to fail fast during outages.",
                ],
            ))

        if "AuthenticationError" in type_counts or "InvalidRequestError" in type_counts:
            hypotheses.append(RootCauseHypothesis(
                category="errors",
                description="API authentication or request validation failures detected.",
                confidence=0.90,
                evidence=[f"auth_errors={type_counts}"],
                remediation=[
                    "Verify GROQ_API_KEY is set and valid.",
                    "Check API key quotas and billing status.",
                    "Review request payload for invalid parameters.",
                ],
            ))

        if len(error_traces) > 0:
            hypotheses.append(RootCauseHypothesis(
                category="errors",
                description=f"General error spike: {len(error_traces)} errors in last 100 requests.",
                confidence=0.60,
                evidence=[f"error_breakdown={type_counts}"],
                remediation=[
                    "Review application logs for stack traces.",
                    "Check upstream service health.",
                    "Add input validation to catch malformed requests early.",
                ],
            ))

        return hypotheses, raw

    def _analyze_hallucination(self, traces, alert_event: AlertEvent):
        scored = [t for t in traces if t.get("faithfulness_label")]
        hallucinated = [t for t in scored if t["faithfulness_label"] == "hallucinated"]
        rate = len(hallucinated) / len(scored) if scored else 0
        avg_score = statistics.mean([t["faithfulness_score"] for t in scored if t.get("faithfulness_score")]) if scored else 0
        short_prompts = [t for t in hallucinated if len(t.get("prompt", "")) < 100]

        hypotheses = []
        raw = {"hallucination_rate": rate, "avg_faithfulness": avg_score, "total_scored": len(scored)}

        if len(short_prompts) > len(hallucinated) * 0.5:
            hypotheses.append(RootCauseHypothesis(
                category="hallucination",
                description="Many hallucinated responses came from very short/vague prompts.",
                confidence=0.80,
                evidence=[f"short_prompt_hallucinations={len(short_prompts)}"],
                remediation=[
                    "Add system prompt with grounding instructions.",
                    "Require users to provide context with their questions.",
                    "Use chain-of-thought prompting to reduce hallucinations.",
                ],
            ))

        hypotheses.append(RootCauseHypothesis(
            category="hallucination",
            description=f"Hallucination rate {rate:.1%} exceeds threshold — response quality degraded.",
            confidence=0.75,
            evidence=[f"hallucination_rate={rate:.3f}", f"avg_faithfulness={avg_score:.3f}"],
            remediation=[
                "Implement RAG to ground responses in retrieved facts.",
                "Lower model temperature (try 0.0–0.3 for factual tasks).",
                "Add a post-generation factuality check before returning response.",
                "Consider fine-tuning on domain-specific data.",
            ],
        ))

        return hypotheses, raw

    def _analyze_cost(self, traces, alert_event: AlertEvent):
        costs = [t["total_cost"] for t in traces if t.get("total_cost")]
        tokens = [t["total_tokens"] for t in traces if t.get("total_tokens")]
        avg_cost = statistics.mean(costs) if costs else 0
        avg_tokens = statistics.mean(tokens) if tokens else 0
        expensive = [t for t in traces if t.get("total_cost", 0) > 0.1]

        hypotheses = []
        raw = {"avg_cost_usd": avg_cost, "avg_tokens": avg_tokens, "expensive_traces": len(expensive)}

        if avg_tokens > 3000:
            hypotheses.append(RootCauseHypothesis(
                category="cost",
                description=f"Average token usage is high ({avg_tokens:.0f} tokens/request).",
                confidence=0.82,
                evidence=[f"avg_tokens={avg_tokens:.0f}"],
                remediation=[
                    "Implement prompt compression or summarisation.",
                    "Set max_tokens limits on completion responses.",
                    "Cache frequent queries to avoid redundant LLM calls.",
                ],
            ))

        if expensive:
            hypotheses.append(RootCauseHypothesis(
                category="cost",
                description=f"{len(expensive)} requests cost >$0.10 each — outlier queries driving spend.",
                confidence=0.78,
                evidence=[f"expensive_traces_count={len(expensive)}"],
                remediation=[
                    "Route complex queries to cheaper models when possible.",
                    "Set per-user cost budgets and rate limits.",
                    "Review whether expensive requests are necessary.",
                ],
            ))

        return hypotheses, raw

    def _analyze_single_error(self, trace, recent_traces):
        error_type = trace.get("error_type", "UnknownError")
        similar = [t for t in recent_traces if t.get("error_type") == error_type]
        is_spike = len(similar) > 5

        hyps = [RootCauseHypothesis(
            category="errors",
            description=f"{error_type} occurred on this trace.",
            confidence=0.80 if is_spike else 0.60,
            evidence=[
                f"error_message={trace.get('error_message', 'N/A')[:200]}",
                f"similar_errors_recently={len(similar)}",
            ],
            remediation=[
                "Review stack trace in trace detail.",
                "Check if error is reproducible with the same prompt.",
                "Verify upstream API health.",
            ],
        )]
        return hyps, {}

    def _latency_hypotheses_for_trace(self, trace, recent_traces):
        latencies = [t["latency_total_ms"] for t in recent_traces if t.get("latency_total_ms")]
        avg = statistics.mean(latencies) if latencies else 0
        this_lat = trace.get("latency_total_ms", 0)
        prompt_len = len(trace.get("prompt", ""))

        hyps = []
        if this_lat > avg * 2:
            hyps.append(RootCauseHypothesis(
                category="latency",
                description=f"Trace latency ({this_lat:.0f}ms) is >2x the recent average ({avg:.0f}ms).",
                confidence=0.70,
                evidence=[f"this_latency={this_lat:.0f}ms", f"recent_avg={avg:.0f}ms"],
                remediation=[
                    "Check if prompt is unusually long.",
                    "Verify model API had no degradation at this time.",
                ],
            ))
        if prompt_len > 3000:
            hyps.append(RootCauseHypothesis(
                category="latency",
                description=f"Very long prompt ({prompt_len} chars) likely caused high latency.",
                confidence=0.75,
                evidence=[f"prompt_length={prompt_len}"],
                remediation=["Truncate prompt context.", "Use embeddings-based retrieval instead of full context."],
            ))
        return hyps


# Singleton
root_cause_analyzer = RootCauseAnalyzer()
