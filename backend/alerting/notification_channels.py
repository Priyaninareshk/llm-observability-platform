import asyncio
import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from alerting.alert_engine import AlertEvent, Severity

logger = logging.getLogger("llm_observability.alerting.notifications")


# ---------------------------------------------------------------------------
# Delivery receipt
# ---------------------------------------------------------------------------

@dataclass
class DeliveryReceipt:
    channel_name: str
    success: bool
    status_code: Optional[int] = None
    error: Optional[str] = None
    sent_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ---------------------------------------------------------------------------
# Base channel
# ---------------------------------------------------------------------------

class NotificationChannel(ABC):
    name: str = "base"

    @abstractmethod
    async def send(self, event: AlertEvent) -> DeliveryReceipt:
        ...


# ---------------------------------------------------------------------------
# Console / log channel
# ---------------------------------------------------------------------------

class ConsoleChannel(NotificationChannel):
    name = "console"

    async def send(self, event: AlertEvent) -> DeliveryReceipt:
        logger.warning(
            "🚨 ALERT [%s] %s | metric=%s value=%.4f threshold=%s",
            event.severity.upper(),
            event.rule_name,
            event.metric_key,
            event.metric_value,
            event.threshold,
        )
        return DeliveryReceipt(channel_name=self.name, success=True, status_code=0)


# ---------------------------------------------------------------------------
# Generic webhook (Slack / Teams / custom)
# ---------------------------------------------------------------------------

class WebhookChannel(NotificationChannel):
    """
    Posts a JSON payload to a webhook URL.
    Set ALERT_WEBHOOK_URL env var or pass url directly.
    """

    name = "webhook"

    SEVERITY_EMOJI = {
        Severity.INFO: "ℹ️",
        Severity.WARNING: "⚠️",
        Severity.CRITICAL: "🔴",
    }

    def __init__(self, url: Optional[str] = None, timeout: float = 5.0):
        self.url = url or os.getenv("ALERT_WEBHOOK_URL", "")
        self.timeout = timeout

    def _build_payload(self, event: AlertEvent) -> Dict[str, Any]:
        emoji = self.SEVERITY_EMOJI.get(event.severity, "⚠️")
        return {
            "text": f"{emoji} *{event.rule_name}*",
            "attachments": [
                {
                    "color": "danger" if event.severity == Severity.CRITICAL else "warning",
                    "fields": [
                        {"title": "Severity",   "value": event.severity, "short": True},
                        {"title": "Metric",     "value": event.metric_key, "short": True},
                        {"title": "Value",      "value": f"{event.metric_value:.4f}", "short": True},
                        {"title": "Threshold",  "value": str(event.threshold), "short": True},
                        {"title": "Message",    "value": event.message, "short": False},
                        {"title": "Fired at",   "value": event.fired_at, "short": True},
                    ],
                }
            ],
        }

    async def send(self, event: AlertEvent) -> DeliveryReceipt:
        if not self.url:
            logger.debug("WebhookChannel: no URL configured, skipping.")
            return DeliveryReceipt(channel_name=self.name, success=False, error="No webhook URL configured")

        payload = self._build_payload(event)
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(self.url, json=payload)
            success = 200 <= resp.status_code < 300
            if not success:
                logger.warning("Webhook delivery failed: HTTP %d", resp.status_code)
            return DeliveryReceipt(
                channel_name=self.name,
                success=success,
                status_code=resp.status_code,
            )
        except Exception as exc:
            logger.error("Webhook send error: %s", exc)
            return DeliveryReceipt(channel_name=self.name, success=False, error=str(exc))


# ---------------------------------------------------------------------------
# PagerDuty Events API v2
# ---------------------------------------------------------------------------

class PagerDutyChannel(NotificationChannel):
    """
    Triggers PagerDuty incidents via Events API v2.
    Set PAGERDUTY_INTEGRATION_KEY env var.
    In simulation mode (no key set) the payload is logged instead.
    """

    name = "pagerduty"
    EVENTS_URL = "https://events.pagerduty.com/v2/enqueue"

    SEVERITY_MAP = {
        Severity.INFO:     "info",
        Severity.WARNING:  "warning",
        Severity.CRITICAL: "critical",
    }

    def __init__(self, integration_key: Optional[str] = None, simulate: bool = False):
        self.integration_key = integration_key or os.getenv("PAGERDUTY_INTEGRATION_KEY", "")
        self.simulate = simulate or not self.integration_key

    def _build_payload(self, event: AlertEvent) -> Dict[str, Any]:
        return {
            "routing_key": self.integration_key,
            "event_action": "trigger",
            "dedup_key": event.rule_id,
            "payload": {
                "summary": event.message,
                "source": "llm-observability-platform",
                "severity": self.SEVERITY_MAP.get(event.severity, "warning"),
                "timestamp": event.fired_at,
                "custom_details": {
                    "metric_key":   event.metric_key,
                    "metric_value": event.metric_value,
                    "threshold":    event.threshold,
                    "labels":       event.labels,
                },
            },
        }

    async def send(self, event: AlertEvent) -> DeliveryReceipt:
        payload = self._build_payload(event)

        if self.simulate:
            logger.warning(
                "[PagerDuty SIMULATION] Would send: %s",
                json.dumps(payload, indent=2),
            )
            return DeliveryReceipt(channel_name=self.name, success=True, status_code=202)

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(self.EVENTS_URL, json=payload)
            success = resp.status_code in (200, 202)
            return DeliveryReceipt(
                channel_name=self.name,
                success=success,
                status_code=resp.status_code,
            )
        except Exception as exc:
            logger.error("PagerDuty send error: %s", exc)
            return DeliveryReceipt(channel_name=self.name, success=False, error=str(exc))


# ---------------------------------------------------------------------------
# Notification dispatcher
# ---------------------------------------------------------------------------

class NotificationDispatcher:
    """
    Holds a list of channels and fans out AlertEvents to all of them asynchronously.
    Register it as an alert_engine handler to wire up the pipeline end-to-end.
    """

    def __init__(self):
        self._channels: List[NotificationChannel] = []
        self._receipts: List[Dict[str, Any]] = []   # last 500

    def add_channel(self, channel: NotificationChannel) -> None:
        self._channels.append(channel)
        logger.info("Notification channel registered: %s", channel.name)

    async def dispatch(self, event: AlertEvent) -> List[DeliveryReceipt]:
        """Send event to all channels concurrently."""
        tasks = [ch.send(event) for ch in self._channels]
        receipts: List[DeliveryReceipt] = await asyncio.gather(*tasks, return_exceptions=False)

        for r in receipts:
            entry = {
                "channel": r.channel_name,
                "success": r.success,
                "status_code": r.status_code,
                "error": r.error,
                "sent_at": r.sent_at,
                "rule_id": event.rule_id,
                "severity": event.severity,
            }
            self._receipts.append(entry)
            if len(self._receipts) > 500:
                self._receipts.pop(0)

        return receipts

    def sync_dispatch(self, event: AlertEvent) -> None:
        """
        Sync wrapper so the dispatcher can be registered as an alert_engine handler
        (which expects a sync callable).  Fires-and-forgets on the running event loop.
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self.dispatch(event))
            else:
                loop.run_until_complete(self.dispatch(event))
        except Exception as exc:
            logger.error("Notification dispatch error: %s", exc)

    def get_receipts(self, limit: int = 100) -> List[Dict[str, Any]]:
        return self._receipts[-limit:]


# ---------------------------------------------------------------------------
# Singleton setup
# ---------------------------------------------------------------------------

dispatcher = NotificationDispatcher()
dispatcher.add_channel(ConsoleChannel())
dispatcher.add_channel(WebhookChannel())
dispatcher.add_channel(PagerDutyChannel(simulate=True))
