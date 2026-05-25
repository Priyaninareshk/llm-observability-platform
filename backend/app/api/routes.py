import time

from fastapi import APIRouter, Depends, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.dependencies import get_llm_service
from app.schemas.chat import ChatRequest, ChatResponse, CostPayload, LatencyPayload, TokenUsagePayload
from app.services.llm_service import LLMService

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
    """Prometheus scrape endpoint placeholder for dashboard/alert integrations."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.post("/chat", response_model=ChatResponse, tags=["chat"])
async def chat(request: ChatRequest, http_request: Request, llm_service: LLMService = Depends(get_llm_service)) -> ChatResponse:
    """Chat endpoint with automatic tracing, metrics, and LangSmith callback hooks."""
    result = await llm_service.chat(request.prompt)
    route_finished_at = time.perf_counter()
    started_at = getattr(http_request.state, "middleware_started_at", None)
    middleware_latency_ms = float(getattr(http_request.state, "middleware_latency_ms", 0.0))
    if started_at is not None and middleware_latency_ms == 0.0:
        # Middleware finalizes after route return, so we estimate from request start.
        middleware_latency_ms = (route_finished_at - float(started_at)) * 1000
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
