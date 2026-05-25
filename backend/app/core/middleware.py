import logging
import time

from fastapi import Request
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from starlette.middleware.base import BaseHTTPMiddleware

from app.telemetry.base import LatencyTrackerPort
from app.telemetry.helpers import current_trace_id

logger = logging.getLogger(__name__)


class RequestLatencyMiddleware(BaseHTTPMiddleware):
    """Middleware that times request lifecycle and enriches observability signals."""

    def __init__(self, app, latency_tracker: LatencyTrackerPort):
        super().__init__(app)
        self._latency_tracker = latency_tracker

    async def dispatch(self, request: Request, call_next):
        started_at = time.perf_counter()
        trace_id = current_trace_id()
        endpoint = request.url.path
        request.state.middleware_started_at = started_at

        logger.info("api.request.start", extra={"trace_id": trace_id, "endpoint": endpoint, "method": request.method})
        try:
            response = await call_next(request)
            middleware_latency_ms = (time.perf_counter() - started_at) * 1000
            request.state.middleware_latency_ms = middleware_latency_ms

            self._latency_tracker.track_stage(
                operation="middleware_latency",
                duration_ms=middleware_latency_ms,
                trace_id=current_trace_id(),
                endpoint=endpoint,
            )

            span = trace.get_current_span()
            span.set_attribute("latency.middleware_ms", middleware_latency_ms)
            span.set_attribute("latency.total_request_ms", middleware_latency_ms)
            span.set_attribute("http.endpoint", endpoint)

            logger.info(
                "api.request.success",
                extra={
                    "trace_id": current_trace_id(),
                    "endpoint": endpoint,
                    "status_code": response.status_code,
                    "latency_total_ms": middleware_latency_ms,
                    "middleware_latency_ms": middleware_latency_ms,
                },
            )
            return response
        except Exception as exc:
            middleware_latency_ms = (time.perf_counter() - started_at) * 1000
            self._latency_tracker.track_stage(
                operation="middleware_latency",
                duration_ms=middleware_latency_ms,
                trace_id=current_trace_id(),
                endpoint=endpoint,
            )
            span = trace.get_current_span()
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            logger.exception(
                "api.request.failure",
                extra={
                    "trace_id": current_trace_id(),
                    "endpoint": endpoint,
                    "method": request.method,
                    "latency_total_ms": middleware_latency_ms,
                },
            )
            raise
