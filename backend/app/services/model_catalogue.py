"""Ask a provider which models it actually offers.

A stage was bound to a Gemini model and the run failed with

    Model 'gemini-1.5-pro' not found on gemini

after the job had already been queued, claimed and paid for up to the call.
Two things had gone wrong and neither was visible until then: the name had been
rewritten by the router's alias table, and the model it was rewritten to had
been retired by Google.

A hardcoded list of model names is wrong the moment a vendor ships or retires
one, and this repository has now been wrong in both directions. The provider
knows. Ask it.

Used before a run rather than during one, so a dead binding costs a request
instead of a job.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger("cbc-model-catalogue")

TIMEOUT = 15.0


def _openai(base: str, key: str) -> list[str]:
    r = httpx.get(f"{base.rstrip('/')}/v1/models",
                  headers={"Authorization": f"Bearer {key}"}, timeout=TIMEOUT)
    r.raise_for_status()
    return [m["id"] for m in r.json().get("data", []) if m.get("id")]


def _anthropic(base: str, key: str) -> list[str]:
    r = httpx.get(f"{base.rstrip('/')}/v1/models",
                  headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                  timeout=TIMEOUT)
    r.raise_for_status()
    return [m["id"] for m in r.json().get("data", []) if m.get("id")]


def _gemini(base: str, key: str) -> list[str]:
    r = httpx.get(f"{base.rstrip('/')}/v1beta/models",
                  params={"key": key}, timeout=TIMEOUT)
    r.raise_for_status()
    out = []
    for m in r.json().get("models", []):
        name = str(m.get("name") or "").removeprefix("models/")
        # Only what can actually serve a generation; the list also carries
        # embedding and vision-only models that would 400 on generateContent.
        if name and "generateContent" in (m.get("supportedGenerationMethods") or []):
            out.append(name)
    return out


def _ollama(base: str, _key: str) -> list[str]:
    r = httpx.get(f"{base.rstrip('/')}/api/tags", timeout=TIMEOUT)
    r.raise_for_status()
    return [m["name"] for m in r.json().get("models", []) if m.get("name")]


_LISTERS = {
    "openai": _openai,
    "anthropic": _anthropic,
    "gemini": _gemini,
    "ollama": _ollama,
}


def live_models(provider: str) -> dict[str, Any]:
    """What this provider will actually serve, with this key, right now."""
    from ..state import runtime_state

    lister = _LISTERS.get(provider)
    if not lister:
        return {"provider": provider, "ok": False,
                "error": f"No model listing is defined for '{provider}'."}

    config = runtime_state.provider_credentials.get(provider)
    base = getattr(config, "base_url", "") or _DEFAULT_BASE.get(provider, "")
    key = ""
    try:
        key = runtime_state.decrypt_api_key(provider) or ""
    except Exception as exc:  # noqa: BLE001
        logger.warning("No usable key for %s: %s", provider, exc)

    if not base:
        return {"provider": provider, "ok": False,
                "error": "No base URL is configured for this provider."}
    if not key and provider != "ollama":
        return {"provider": provider, "ok": False,
                "error": "No API key is configured for this provider."}

    try:
        models = sorted(lister(base, key))
    except Exception as exc:  # noqa: BLE001
        return {"provider": provider, "ok": False, "error": str(exc)[:300]}
    return {"provider": provider, "ok": True, "models": models}


_DEFAULT_BASE = {
    "openai": "https://api.openai.com",
    "anthropic": "https://api.anthropic.com",
    "gemini": "https://generativelanguage.googleapis.com",
    "ollama": "http://localhost:11434",
}


def check_bindings() -> dict[str, Any]:
    """Every stage binding, and whether its provider still serves that model.

    The point is the timing. A binding checked here fails on a request; the
    same binding checked by running the pipeline fails after the queue, the
    claim and whatever was spent reaching the call.
    """
    from ..state import runtime_state

    cache: dict[str, dict[str, Any]] = {}
    rows = []
    for stage, binding in sorted(runtime_state.stage_bindings.items()):
        provider = str(getattr(binding, "provider", "") or "")
        raw = str(getattr(binding, "model", "") or "")
        if not (provider and raw):
            continue
        # Check the name that will actually be SENT, not the one that was
        # typed. The two differed, and that difference is half this bug.
        from .provider_router import normalize_model_name
        model = normalize_model_name(provider, raw)
        if provider not in cache:
            cache[provider] = live_models(provider)
        listed = cache[provider]

        if not listed.get("ok"):
            status, detail = "UNKNOWN", listed.get("error", "")
        elif model in listed["models"]:
            status, detail = "OK", ""
        else:
            near = [m for m in listed["models"] if m.split("-")[0] == model.split("-")[0]]
            status = "NOT SERVED"
            detail = (f"{provider} does not offer '{model}'. "
                      f"It does offer: {', '.join(near[:6]) or 'nothing similar'}")
        row = {"stage": stage, "provider": provider, "model": model,
               "status": status, "detail": detail}
        if model != raw:
            row["typed"] = raw
            row["detail"] = (f"typed as '{raw}', sent as '{model}'. "
                             + detail).strip()
        rows.append(row)

    return {"ok": not any(r["status"] == "NOT SERVED" for r in rows),
            "bindings": rows}
