import time

from fastapi import APIRouter, Depends, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.core.config import get_settings
from app.dependencies import get_cost_tracker, get_llm_service
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    CostPayload,
    CostReportPayload,
    LangSmithStatusPayload,
    LatencyPayload,
    TokenUsagePayload,
)
from app.services.llm_service import LLMService
from app.telemetry.base import CostTrackerPort
from app.telemetry.cost_tracker import CostTracker


from monitoring.error_tracker import error_tracker


from hallucination.async_pipeline import hallucination_pipeline, ScoringJob
from storage.trace_storage import trace_storage, TraceRecord


from alerting.alert_engine import alert_engine
from alerting.latency_cost_rules import build_metrics_snapshot

router = APIRouter(tags=["system"])


@router.get("/")
async def root() -> dict[str, str]:
    """Root endpoint for basic service discovery."""
    return {
        "service": "llm-observability-platform",
        "message": "Service is running",
    }


@router.get("/health")
async def health_check() -> dict[str, str]:
    """Health endpoint used by orchestrators and monitoring checks."""
    return {
        "status": "ok",
        "service": "llm-observability-platform",
    }


@router.get("/metrics", tags=["system"])
async def metrics() -> Response:
    """Prometheus scrape endpoint — includes error metrics from US-08."""
    data = generate_latest().decode("utf-8")
    # Append error rate metrics in Prometheus text format (US-08)
    data += "\n" + error_tracker.prometheus_text()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


@router.get("/reports/cost", response_model=CostReportPayload, tags=["system"])
async def cost_report(cost_tracker: CostTrackerPort = Depends(get_cost_tracker)) -> CostReportPayload:
    """Aggregated in-process cost report for observability validation."""
    if isinstance(cost_tracker, CostTracker):
        report = cost_tracker.report()
    else:
        report = {
            "total_requests": 0,
            "total_cost_usd": 0.0,
            "avg_cost_per_request_usd": 0.0,
            "alert_threshold_usd": 0.0,
            "by_model": {},
            "recent_records": [],
        }
    return CostReportPayload(**report)


@router.get("/observability/langsmith", response_model=LangSmithStatusPayload, tags=["system"])
async def langsmith_status() -> LangSmithStatusPayload:
    """LangSmith integration readiness status."""
    settings = get_settings()
    return LangSmithStatusPayload(
        enabled=settings.langchain_tracing_v2,
        api_key_configured=bool(settings.langchain_api_key),
        project=settings.langchain_project,
    )


@router.post("/chat", response_model=ChatResponse, tags=["chat"])
async def chat(
    request: ChatRequest,
    http_request: Request,
    llm_service: LLMService = Depends(get_llm_service),
) -> ChatResponse:
    """Chat endpoint with automatic tracing, metrics, and LangSmith callback hooks."""

    endpoint = "/chat"

    
    error_tracker.record_request(endpoint)

    try:
        result = await llm_service.chat(request.prompt)

        route_finished_at = time.perf_counter()
        started_at = getattr(http_request.state, "middleware_started_at", None)
        middleware_latency_ms = float(getattr(http_request.state, "middleware_latency_ms", 0.0))
        if started_at is not None and middleware_latency_ms == 0.0:
            middleware_latency_ms = (route_finished_at - float(started_at)) * 1000

        # Save trace to storage ─────────────────────────────────
        response_dict = {
            "response": result.response,
            "latency": {
                "total_ms": result.latency.total_ms,
                "llm_ms":   result.latency.llm_ms,
            },
            "token_usage": {
                "prompt_tokens":     result.token_usage.prompt_tokens,
                "completion_tokens": result.token_usage.completion_tokens,
                "total_tokens":      result.token_usage.total_tokens,
                "model_name":        result.token_usage.model_name,
            },
            "cost": {
                "prompt_cost":     result.cost.prompt_cost,
                "completion_cost": result.cost.completion_cost,
                "total_cost":      result.cost.total_cost,
            },
        }
        trace_record = TraceRecord.from_chat_response(
            trace_id=result.trace_id,
            prompt=request.prompt,
            response_data=response_dict,
        )
        trace_storage.save_trace(trace_record)

        # ── Submit async hallucination scoring ─────────────────────
    
        await hallucination_pipeline.submit(ScoringJob(
            trace_id=result.trace_id,
            query=request.prompt,
            response=result.response,
            context=request.prompt,
        ))

    
        metrics_snapshot = build_metrics_snapshot(
            latency_stats={
                "p50_ms": result.latency.total_ms,
                "p95_ms": result.latency.total_ms,  # replace with real percentiles when available
                "p99_ms": result.latency.total_ms,
            },
            cost_stats={
                "last_query_usd": result.cost.total_cost,
                "hourly_usd":     0,                 # wire to CostTracker.hourly_total() if available
            },
            error_stats={
                "rate": error_tracker.error_rate(endpoint),
            },
            hallucination_stats={
                "rate": 0,                           # updated async once hallucination scoring completes
            },
        )
        alert_engine.evaluate(metrics_snapshot)

        return ChatResponse(
            response=result.response,
            latency=LatencyPayload(
                total_ms=result.latency.total_ms,
                llm_ms=result.latency.llm_ms,
                callback_ms=result.latency.callback_ms,
                middleware_ms=middleware_latency_ms,
            ),
            token_usage=TokenUsagePayload(
                prompt_tokens=result.token_usage.prompt_tokens,
                completion_tokens=result.token_usage.completion_tokens,
                total_tokens=result.token_usage.total_tokens,
                model_name=result.token_usage.model_name,
                timestamp=result.token_usage.timestamp,
                request_id=result.token_usage.request_id,
                trace_id=result.token_usage.trace_id,
            ),
            cost=CostPayload(
                prompt_cost=result.cost.prompt_cost,
                completion_cost=result.cost.completion_cost,
                total_cost=result.cost.total_cost,
                model_name=result.cost.model_name,
                pricing_found=result.cost.pricing_found,
            ),
            trace_id=result.trace_id,
        )

    except Exception as exc:
     
        error_tracker.record_error(exc, endpoint=endpoint, trace_id=None)
        raise
