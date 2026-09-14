"""Global settings, from the console: GET/PUT /api/v1/admin/settings."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..errors import raise_api_error
from ..services import platform_settings, webhooks
from ..services.auth import AuthContext, require_roles

router = APIRouter(prefix="/api/v1/admin/settings", tags=["Admin Settings"])


class SettingsUpdate(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)


@router.get("")
def read_settings(_: AuthContext = Depends(require_roles("admin"))) -> dict[str, Any]:
    return {"settings": platform_settings.describe(), "webhook_events": list(webhooks.EVENTS)}


@router.put("")
def write_settings(payload: SettingsUpdate,
                   auth: AuthContext = Depends(require_roles("admin"))) -> dict[str, Any]:
    unknown = [k for k in payload.values if k not in platform_settings._BY_KEY]
    if unknown:
        raise_api_error("SCHEMA_VALIDATION_FAILED", f"Unknown setting(s): {', '.join(unknown)}")
    written = platform_settings.set_many(payload.values, updated_by=auth.subject)
    return {"written": {k: ("••••••" if platform_settings._BY_KEY[k].kind == "secret" and v else v)
                        for k, v in written.items()},
            "settings": platform_settings.describe()}


@router.post("/webhook/test")
def test_webhook(_: AuthContext = Depends(require_roles("admin"))) -> dict[str, Any]:
    """Send a test event now, and say what the receiver answered."""
    url, secret, _events = webhooks.configured()
    if not url:
        raise_api_error("SCHEMA_VALIDATION_FAILED", "No webhook URL is set.")
    body = webhooks.body_for("test", {"message": "This is a test delivery from the CBC platform."})
    return {"url": url, **webhooks.deliver(url, "test", body, secret, attempts=1)}
