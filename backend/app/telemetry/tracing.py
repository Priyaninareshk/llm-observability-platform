import logging
from collections.abc import Mapping
from typing import Any

from app.telemetry.base import TracerPort

logger = logging.getLogger(__name__)


class NoOpTracer(TracerPort):
    """Safe default tracer.

    This implementation logs tracing events without external dependencies so local
    development works before OpenTelemetry exporters are configured.
    """

    def start_span(self, name: str, attributes: Mapping[str, Any] | None = None) -> dict[str, Any]:
        span = {"name": name, "attributes": dict(attributes or {})}
        logger.debug("Start span", extra={"span": span})
        return span

    def end_span(self, span: Any) -> None:
        logger.debug("End span", extra={"span": span})
