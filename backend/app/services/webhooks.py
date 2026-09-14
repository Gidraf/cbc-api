"""Tell another system when something here finishes.

A paper frozen by an order, a job done or failed, an agent task finished:
each is an event a shop, a printer's queue, a Slack channel or a script
may want to hear about without polling. Configured on the Settings page;
delivered as a POST with a signature the receiver can check.

    POST <webhook_url>
    X-CBC-Event: paper.frozen
    X-CBC-Signature: sha256=<hmac of the body with the secret>
    {"event": "paper.frozen", "at": "...", "payload": {...}}

Delivery is best effort from a background thread with two retries: a
webhook that cannot be reached must never fail the job that fired it.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
import time
from typing import Any

logger = logging.getLogger("cbc-webhooks")

EVENTS = ("job.done", "job.failed", "order.done", "paper.frozen", "agent_task.done", "agent_task.failed")


def configured() -> tuple[str, str, list[str]]:
    from . import platform_settings

    url = str(platform_settings.get("webhook_url") or "").strip()
    secret = str(platform_settings.get("webhook_secret") or "")
    events = list(platform_settings.get("webhook_events") or [])
    return url, secret, events


def body_for(event: str, payload: dict[str, Any]) -> bytes:
    from ..models import now_iso

    return json.dumps({"event": event, "at": now_iso(), "payload": payload},
                      ensure_ascii=False, default=str).encode("utf-8")


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def deliver(url: str, event: str, body: bytes, secret: str, *, attempts: int = 3) -> dict[str, Any]:
    """POST once, with retries. Returns what happened, for the test button."""
    import httpx

    headers = {"Content-Type": "application/json", "X-CBC-Event": event, "User-Agent": "cbc-webhook/1"}
    if secret:
        headers["X-CBC-Signature"] = sign(secret, body)
    last: dict[str, Any] = {"ok": False, "status": 0, "error": ""}
    for attempt in range(1, attempts + 1):
        try:
            response = httpx.post(url, content=body, headers=headers, timeout=15)
            last = {"ok": 200 <= response.status_code < 300, "status": response.status_code,
                    "error": "" if 200 <= response.status_code < 300 else response.text[:200]}
            if last["ok"]:
                return last
        except Exception as exc:  # noqa: BLE001
            last = {"ok": False, "status": 0, "error": str(exc)[:200]}
        if attempt < attempts:
            time.sleep(2 * attempt)
    return last


def emit(event: str, payload: dict[str, Any]) -> bool:
    """Send in the background if a webhook is configured for this event."""
    url, secret, events = configured()
    if not url or (events and event not in events):
        return False
    body = body_for(event, payload)

    def _send() -> None:
        outcome = deliver(url, event, body, secret)
        if outcome["ok"]:
            logger.info("Webhook %s delivered to %s (%s).", event, url, outcome["status"])
        else:
            logger.warning("Webhook %s to %s failed: %s %s", event, url, outcome["status"], outcome["error"])

    threading.Thread(target=_send, name=f"webhook-{event}", daemon=True).start()
    return True
