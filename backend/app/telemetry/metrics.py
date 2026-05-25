import logging
import re
from collections.abc import Mapping
from typing import Any

from opentelemetry.metrics import get_meter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import ConsoleMetricExporter, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from prometheus_client import Counter, Gauge, Histogram

from app.telemetry.config import TelemetryConfig
from app.telemetry.base import MetricsPort

logger = logging.getLogger(__name__)


class OpenTelemetryMetricsCollector(MetricsPort):
    """MetricsPort adapter backed by OpenTelemetry metrics SDK.

    This keeps request count, latency, token usage, and cost tracking as reusable
    placeholders for future Prometheus and dashboard integrations.
    """

    def __init__(self, meter_name: str = "app.telemetry.metrics") -> None:
        meter = get_meter(meter_name)
        self._counters: dict[str, Any] = {}
        self._histograms: dict[str, Any] = {}
        self._prom_counters: dict[tuple[str, tuple[str, ...]], Counter] = {}
        self._prom_histograms: dict[tuple[str, tuple[str, ...]], Histogram] = {}
        self._prom_gauges: dict[tuple[str, tuple[str, ...]], Gauge] = {}
        self._meter = meter

    def increment(self, name: str, value: float = 1.0, labels: Mapping[str, str] | None = None) -> None:
        if name not in self._counters:
            self._counters[name] = self._meter.create_counter(name=name)
        attrs = dict(labels or {})
        self._counters[name].add(value, attributes=attrs)
        prom = self._get_prom_counter(name, attrs)
        prom.labels(**attrs).inc(value) if attrs else prom.inc(value)

    def observe(self, name: str, value: float, labels: Mapping[str, str] | None = None) -> None:
        if name not in self._histograms:
            self._histograms[name] = self._meter.create_histogram(name=name)
        attrs = dict(labels or {})
        self._histograms[name].record(value, attributes=attrs)
        prom = self._get_prom_histogram(name, attrs)
        prom.labels(**attrs).observe(value) if attrs else prom.observe(value)

    def set_gauge(self, name: str, value: float, labels: Mapping[str, str] | None = None) -> None:
        attrs = dict(labels or {})
        prom = self._get_prom_gauge(name, attrs)
        prom.labels(**attrs).set(value) if attrs else prom.set(value)

    def _normalize(self, name: str) -> str:
        metric = re.sub(r"[^a-zA-Z0-9_]", "_", name).lower()
        if not metric[0].isalpha() and metric[0] != "_":
            metric = f"m_{metric}"
        return metric

    def _get_prom_counter(self, name: str, labels: Mapping[str, str]) -> Counter:
        key = (self._normalize(name), tuple(sorted(labels.keys())))
        if key not in self._prom_counters:
            self._prom_counters[key] = Counter(
                name=key[0],
                documentation=f"Application counter for {name}",
                labelnames=list(key[1]),
            )
        return self._prom_counters[key]

    def _get_prom_histogram(self, name: str, labels: Mapping[str, str]) -> Histogram:
        key = (self._normalize(name), tuple(sorted(labels.keys())))
        if key not in self._prom_histograms:
            self._prom_histograms[key] = Histogram(
                name=key[0],
                documentation=f"Application histogram for {name}",
                labelnames=list(key[1]),
            )
        return self._prom_histograms[key]

    def _get_prom_gauge(self, name: str, labels: Mapping[str, str]) -> Gauge:
        key = (self._normalize(name), tuple(sorted(labels.keys())))
        if key not in self._prom_gauges:
            self._prom_gauges[key] = Gauge(
                name=key[0],
                documentation=f"Application gauge for {name}",
                labelnames=list(key[1]),
            )
        return self._prom_gauges[key]


class NoOpMetricsCollector(MetricsPort):
    """Fallback metrics collector used if metrics SDK isn't initialized yet."""

    def increment(self, name: str, value: float = 1.0, labels: Mapping[str, str] | None = None) -> None:
        logger.debug("Increment metric", extra={"name": name, "value": value, "labels": dict(labels or {})})

    def observe(self, name: str, value: float, labels: Mapping[str, str] | None = None) -> None:
        logger.debug("Observe metric", extra={"name": name, "value": value, "labels": dict(labels or {})})

    def set_gauge(self, name: str, value: float, labels: Mapping[str, str] | None = None) -> None:
        logger.debug("Set gauge metric", extra={"name": name, "value": value, "labels": dict(labels or {})})


def initialize_meter_provider(config: TelemetryConfig) -> None:
    """Initialize process-wide meter provider.

    For now we export to console to keep setup simple and production-safe.
    Future stories can swap this exporter for OTLP/Prometheus exporters.
    """
    resource = Resource.create({"service.name": config.service_name})
    reader = PeriodicExportingMetricReader(ConsoleMetricExporter())
    provider = MeterProvider(resource=resource, metric_readers=[reader])
    from opentelemetry.metrics import set_meter_provider

    set_meter_provider(provider)
    logger.info("OpenTelemetry meter provider initialized")
