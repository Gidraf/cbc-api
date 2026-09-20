"""Settings an operator changes from the console, not from a shell.

Every knob here used to be an environment variable: the address the
platform is reached at, the name printed on every paper, how long logs are
kept, where to send a webhook. An environment variable is set by whoever
deploys, once, by editing a file on the box — which is the wrong person and
the wrong place for "what name goes on the papers".

Each key has an environment variable it falls back to, so a deployment that
already sets them keeps working, and the console shows which is in force.
Values are read from the table with a short cache; the console's save
takes effect within seconds in every process.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("cbc-platform-settings")

_TTL_SECONDS = 20.0


@dataclass(frozen=True)
class Setting:
    key: str
    env: str
    kind: str            # "string" | "int" | "bool" | "list" | "secret"
    title: str
    help: str
    default: Any = ""
    group: str = "General"


SETTINGS: tuple[Setting, ...] = (
    Setting("public_base_url", "PUBLIC_BASE_URL", "string", "Public address",
            "Where this platform is reached from outside — e.g. https://papers.example.co.ke. It is written "
            "into links the platform creates when no browser is asking: the QR code on a paper frozen by a "
            "queued order, the print links in an order's result, webhook payloads. A request from the console "
            "uses the address it arrived on; a background job has no such address, and without this it "
            "writes http://localhost.",
            "", "Papers"),
    Setting("paper_series_name", "PAPER_SERIES_NAME", "string", "Series name on papers",
            "Printed at the head and foot of every paper composed from the bank — your brand.", "", "Papers"),
    Setting("paper_default_count", "", "int", "Questions per paper",
            "The default item count the composer and orders start from.", 30, "Papers"),
    Setting("log_retention_days", "LOG_RETENTION_DAYS", "int", "Log retention (days)",
            "Service log lines older than this are pruned every hour.", 7, "Operations"),
    Setting("log_keep_rows", "LOG_KEEP_ROWS", "int", "Log rows to keep",
            "At most this many log lines are kept, whatever their age.", 20000, "Operations"),
    Setting("byom_step_timeout_seconds", "BYOM_STEP_TIMEOUT_SECONDS", "int", "Agent step timeout (seconds)",
            "How long a station driven by an outside agent waits for one prompt to be answered.",
            2700, "Agents"),
    Setting("users_may_generate", "USERS_MAY_GENERATE", "bool", "User accounts may generate",
            "When on, a signed-up user can ask the builder to write new questions and to run an AI review — "
            "both spend this platform's provider tokens. Off, users compose from the bank only.",
            False, "Builder"),
    Setting("auto_ingest_enabled", "AUTO_INGEST_ENABLED", "bool", "Auto-ingest from Langfuse",
            "When on, every grade's dataset is synced from Langfuse on a schedule and any design not yet "
            "ingested is queued, with strands and sub-strands built behind it — the same pass as the "
            "Datasets screen's Ingest everything, without the press.", False, "Datasets"),
    Setting("auto_ingest_interval_minutes", "AUTO_INGEST_INTERVAL_MINUTES", "int", "Auto-ingest every (minutes)",
            "How often the watch looks at Langfuse. Five at the least.", 30, "Datasets"),
    Setting("webhook_url", "WEBHOOK_URL", "string", "Webhook URL",
            "Where to POST an event when something finishes: a job, an order, a frozen paper, an agent task. "
            "Empty means no webhooks.", "", "Webhooks"),
    Setting("webhook_secret", "WEBHOOK_SECRET", "secret", "Webhook secret",
            "Each delivery carries X-CBC-Signature: sha256=HMAC(secret, body). Verify it on your side.",
            "", "Webhooks"),
    Setting("webhook_events", "WEBHOOK_EVENTS", "list", "Webhook events",
            "Which events to send: job.done, job.failed, order.done, paper.frozen, agent_task.done, "
            "agent_task.failed. Empty means all.", [], "Webhooks"),
)
_BY_KEY = {s.key: s for s in SETTINGS}

_cache: dict[str, Any] = {}
_cache_at = 0.0
_lock = threading.Lock()


def _coerce(setting: Setting, value: Any) -> Any:
    if value is None:
        return setting.default
    if setting.kind == "int":
        try:
            return int(value)
        except (TypeError, ValueError):
            return setting.default
    if setting.kind == "bool":
        return str(value).strip().lower() in ("1", "true", "yes", "on")
    if setting.kind == "list":
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        return [v.strip() for v in str(value).split(",") if v.strip()]
    return str(value)


def _from_env(setting: Setting) -> Any | None:
    if not setting.env:
        return None
    raw = os.getenv(setting.env)
    if raw is None or raw == "":
        return None
    return _coerce(setting, raw)


def _load() -> dict[str, Any]:
    global _cache_at
    with _lock:
        if time.time() - _cache_at < _TTL_SECONDS:
            return _cache
        try:
            from ..infra.db import fetch_all

            rows = fetch_all("SELECT key, value FROM platform_settings")
            _cache.clear()
            for row in rows:
                _cache[str(row["key"])] = row.get("value")
        except Exception as exc:  # noqa: BLE001
            logger.debug("platform_settings not readable (%s); using the environment", exc)
        _cache_at = time.time()
        return _cache


def get(key: str, default: Any = None) -> Any:
    """The value in force: the console's, else the environment's, else the default."""
    setting = _BY_KEY.get(key)
    stored = _load().get(key)
    if stored is not None and stored != "":
        return _coerce(setting, stored) if setting else stored
    if setting is None:
        return default
    from_env = _from_env(setting)
    if from_env is not None:
        return from_env
    return setting.default if default is None else default


def source_of(key: str) -> str:
    setting = _BY_KEY.get(key)
    stored = _load().get(key)
    if stored is not None and stored != "":
        return "console"
    if setting is not None and _from_env(setting) is not None:
        return "environment"
    return "default"


def set_many(values: dict[str, Any], *, updated_by: str = "") -> dict[str, Any]:
    """Store what the console sent. An empty value clears the console's
    setting so the environment or the default applies again."""
    from ..infra.db import execute, to_json

    written: dict[str, Any] = {}
    for key, value in values.items():
        setting = _BY_KEY.get(key)
        if setting is None:
            continue
        if value is None or value == "" or value == []:
            execute("DELETE FROM platform_settings WHERE key = :key", {"key": key})
            written[key] = None
            continue
        clean = _coerce(setting, value)
        execute(
            """
            INSERT INTO platform_settings (key, value, updated_by, updated_at)
            VALUES (:key, CAST(:value AS jsonb), :by, NOW())
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_by = EXCLUDED.updated_by,
                                            updated_at = NOW()
            """,
            {"key": key, "value": to_json(clean), "by": updated_by},
        )
        written[key] = clean
    global _cache_at
    _cache_at = 0.0
    return written


def describe() -> list[dict[str, Any]]:
    """Every setting with its value in force, where it comes from, and its help."""
    out = []
    for setting in SETTINGS:
        value = get(setting.key)
        shown = ("••••••" if setting.kind == "secret" and value else value)
        out.append({"key": setting.key, "title": setting.title, "help": setting.help,
                    "kind": setting.kind, "group": setting.group, "env": setting.env,
                    "value": shown, "source": source_of(setting.key), "default": setting.default})
    return out


_INTERNAL_HOST = ("api", "backend", "localhost", "127.0.0.1", "0.0.0.0", "web", "frontend", "nginx")


def _reachable(host: str) -> bool:
    """A host a person's machine could resolve: not a compose service
    name, not the loopback. `api:8000` is what the console's proxy calls
    the API and nothing outside the box can."""
    name = host.split(":")[0].strip().lower()
    if not name or name in _INTERNAL_HOST:
        return False
    return "." in name


def public_base_url(request: Any = None) -> str:
    """The address to write into a link.

    The configured public address first — it exists for exactly this. Then
    what the request can tell us, most trustworthy first: the forwarded
    host a proxy set, the browser's Origin or Referer, and only then the
    bare Host — which behind the console's proxy is `api:8000`, and was
    written into a download link nobody could use.
    """
    configured = str(get("public_base_url") or "").rstrip("/")
    if configured:
        return configured
    if request is not None:
        try:
            headers = request.headers
            forwarded_proto = headers.get("x-forwarded-proto", "").split(",")[0].strip()
            forwarded_host = headers.get("x-forwarded-host", "").split(",")[0].strip()
            if forwarded_host and _reachable(forwarded_host):
                return f"{forwarded_proto or request.url.scheme}://{forwarded_host}".rstrip("/")
            for header in ("origin", "referer"):
                value = str(headers.get(header) or "").strip()
                if value.startswith(("http://", "https://")):
                    scheme, rest = value.split("://", 1)
                    host = rest.split("/", 1)[0]
                    if _reachable(host):
                        return f"{scheme}://{host}"
            host = headers.get("host", "") or request.url.netloc
            if host and _reachable(host):
                return f"{request.url.scheme}://{host}".rstrip("/")
        except Exception:  # noqa: BLE001
            pass
    return "http://localhost:8000"
