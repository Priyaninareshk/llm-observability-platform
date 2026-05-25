import logging
import os
import time
from dataclasses import dataclass

from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from app.core.config import Settings
from app.telemetry.base import CostTrackerPort, LatencyTrackerPort, MetricsPort, TokenTrackerPort, TracerPort
from app.telemetry.cost_tracker import CostBreakdown
from app.telemetry.helpers import current_trace_id
from app.telemetry.langsmith_callback import LangSmithObservabilityCallback
from app.telemetry.latency_tracker import LatencyBreakdown
from app.telemetry.token_tracker import TokenUsageRecord
from app.telemetry.token_utils import estimate_tokens

logger = logging.getLogger(__name__)


@dataclass
class LLMExecutionResult:
    """Normalized LLM execution output for API handlers."""

    response: str
    latency: LatencyBreakdown
    token_usage: TokenUsageRecord
    cost: CostBreakdown
    trace_id: str


class LLMService:
    """Async LangChain execution service with tracing and metrics hooks."""

    def __init__(
        self,
        settings: Settings,
        tracer: TracerPort,
        metrics: MetricsPort,
        token_tracker: TokenTrackerPort,
        cost_tracker: CostTrackerPort,
        latency_tracker: LatencyTrackerPort,
    ) -> None:
        self._settings = settings
        self._tracer = tracer
        self._metrics = metrics
        self._token_tracker = token_tracker
        self._cost_tracker = cost_tracker
        self._latency_tracker = latency_tracker
        self._configure_langsmith_environment()

    async def chat(self, prompt: str) -> LLMExecutionResult:
        """Run one chat request and capture observability signals."""
        started_at = time.perf_counter()
        callback = LangSmithObservabilityCallback(
            metrics=self._metrics,
            token_tracker=self._token_tracker,
            cost_tracker=self._cost_tracker,
            latency_tracker=self._latency_tracker,
            trace_id_getter=current_trace_id,
        )

        with trace.get_tracer(__name__).start_as_current_span("llm.request.lifecycle") as lifecycle_span:
            lifecycle_span.set_attribute("llm.prompt_length", len(prompt))
            self._metrics.increment("api_request_count", labels={"endpoint": "/chat"})
            api_span = self._tracer.start_span("api.request.handling", attributes={"endpoint": "/chat", "operation": "chat"})

            logger.info("chat.request.start", extra={"trace_id": current_trace_id()})
            try:
                if not self._settings.openai_api_key:
                    # Safe local fallback keeps endpoint operational in dev environments.
                    response_text = f"Mock response: {prompt}"
                    prompt_tokens = estimate_tokens(prompt)
                    completion_tokens = estimate_tokens(response_text)
                    token_usage = self._token_tracker.track_usage(
                        model_name=self._settings.default_llm_model,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        trace_id=current_trace_id(),
                        request_id="mock-local-request",
                        request_latency_ms=0.0,
                    )
                    cost = self._cost_tracker.calculate_and_track(token_usage)
                    callback_latency_ms = 0.0
                    llm_latency_ms = 0.0
                else:
                    model = ChatOpenAI(
                        model=self._settings.default_llm_model,
                        api_key=self._settings.openai_api_key,
                        temperature=0,
                    )
                    result = await model.ainvoke(prompt, config=RunnableConfig(callbacks=[callback]))
                    response_text = result.content if isinstance(result.content, str) else str(result.content)
                    token_usage, cost = callback.latest_usage()
                    callback_latency = callback.latest_latency()
                    callback_latency_ms = callback_latency.callback_processing_ms if callback_latency else 0.0
                    llm_latency_ms = callback_latency.llm_inference_ms if callback_latency else 0.0

                if token_usage is None:
                    token_usage = self._token_tracker.track_usage(
                        model_name=self._settings.default_llm_model,
                        prompt_tokens=0,
                        completion_tokens=0,
                        trace_id=current_trace_id(),
                        request_id="missing-usage",
                        request_latency_ms=0.0,
                    )
                if cost is None:
                    cost = self._cost_tracker.calculate_and_track(token_usage)

                total_latency_ms = (time.perf_counter() - started_at) * 1000
                middleware_latency_ms = 0.0
                if llm_latency_ms == 0.0:
                    llm_latency_ms = total_latency_ms

                self._latency_tracker.track_stage("total_request_latency", total_latency_ms, current_trace_id(), "/chat")
                self._latency_tracker.track_stage("llm_inference_latency", llm_latency_ms, current_trace_id(), "/chat")
                self._latency_tracker.track_stage("callback_processing_latency", callback_latency_ms, current_trace_id(), "/chat")

                self._metrics.observe("api_latency_ms", total_latency_ms, labels={"endpoint": "/chat"})
                self._metrics.increment("api_success_count", labels={"endpoint": "/chat"})
                lifecycle_span.set_attribute("latency.total_ms", total_latency_ms)
                lifecycle_span.set_attribute("latency.llm_ms", llm_latency_ms)
                lifecycle_span.set_attribute("latency.callback_ms", callback_latency_ms)
                lifecycle_span.set_attribute("latency.middleware_ms", middleware_latency_ms)
                lifecycle_span.set_attribute("tokens.prompt", token_usage.prompt_tokens)
                lifecycle_span.set_attribute("tokens.completion", token_usage.completion_tokens)
                lifecycle_span.set_attribute("tokens.total", token_usage.total_tokens)
                lifecycle_span.set_attribute("cost.prompt", cost.prompt_cost)
                lifecycle_span.set_attribute("cost.completion", cost.completion_cost)
                lifecycle_span.set_attribute("cost.total", cost.total_cost)
                logger.info(
                    "chat.request.success",
                    extra={
                        "trace_id": current_trace_id(),
                        "endpoint": "/chat",
                        "latency_total_ms": total_latency_ms,
                        "latency_llm_ms": llm_latency_ms,
                        "latency_callback_ms": callback_latency_ms,
                        "latency_middleware_ms": middleware_latency_ms,
                    },
                )

                # Placeholder hook: future persistence layer can store full trace metadata here.
                self._persist_placeholder(
                    trace_id=current_trace_id(),
                    prompt=prompt,
                    response=response_text,
                    latency_ms=total_latency_ms,
                )
                return LLMExecutionResult(
                    response=response_text,
                    latency=LatencyBreakdown(
                        total_ms=total_latency_ms,
                        llm_ms=llm_latency_ms,
                        callback_ms=callback_latency_ms,
                        middleware_ms=middleware_latency_ms,
                    ),
                    token_usage=token_usage,
                    cost=cost,
                    trace_id=current_trace_id(),
                )
            except Exception as exc:
                self._metrics.increment("api_error_count", labels={"endpoint": "/chat"})
                lifecycle_span.record_exception(exc)
                lifecycle_span.set_status(Status(StatusCode.ERROR, str(exc)))
                logger.exception("chat.request.failure", extra={"trace_id": current_trace_id()})
                raise
            finally:
                self._tracer.end_span(api_span)

    def _persist_placeholder(self, trace_id: str, prompt: str, response: str, latency_ms: float) -> None:
        """Placeholder for future DB persistence of traces, prompts, and outputs."""
        logger.debug(
            "chat.persistence.placeholder",
            extra={"trace_id": trace_id, "prompt_size": len(prompt), "response_size": len(response), "latency_ms": latency_ms},
        )

    def _configure_langsmith_environment(self) -> None:
        """Configure LangSmith tracing vars consumed by LangChain runtime."""
        if self._settings.langchain_api_key:
            os.environ["LANGCHAIN_API_KEY"] = self._settings.langchain_api_key
        os.environ["LANGCHAIN_TRACING_V2"] = "true" if self._settings.langchain_tracing_v2 else "false"
        os.environ["LANGCHAIN_PROJECT"] = self._settings.langchain_project
