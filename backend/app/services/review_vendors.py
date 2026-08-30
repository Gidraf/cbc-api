"""Which vendors and models can act as a reviewer, and which pairings count.

Layer 2 exists to be a SECOND opinion. Two models from one vendor share
training data, tokenisation, RLHF and therefore blind spots — asking gpt-4o to
check gpt-4o-mini is closer to asking the same model twice than to independent
review. So the vendor of each layer is recorded, and an approval that rests on
one vendor reviewing itself is refused rather than quietly granted.

Ollama is included deliberately: a locally hosted reviewer costs nothing per
call and shares no training data with any hosted vendor, which makes it a
genuinely independent third opinion even when it is the weaker model.
"""
from __future__ import annotations

from typing import Any

# Models known to work for structured JSON review, per vendor. The list is a
# default offered in the console, not a restriction — a vendor's newer model
# can be typed in, and provider_router normalises what it can.
REVIEW_MODELS: dict[str, dict[str, Any]] = {
    "anthropic": {
        "label": "Anthropic",
        "models": [
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
            "claude-3-opus-20240229",
        ],
        "default": "claude-3-5-sonnet-20241022",
        "notes": "Strong on instruction adherence and on saying what it is unsure of.",
    },
    "openai": {
        "label": "OpenAI",
        "models": ["gpt-4o", "gpt-4o-mini", "o3-mini", "o1-mini"],
        "default": "gpt-4o",
        "notes": "Reliable JSON. Usually the generator here, so prefer it on a "
                 "different layer from the one that wrote the content.",
    },
    "gemini": {
        "label": "Google Gemini",
        # gemini-1.5-pro and gemini-1.5-flash were listed here and are retired:
        # the API answers 404, and the run fails after paying to reach the call.
        "models": ["gemini-2.0-flash", "gemini-2.5-pro", "gemini-2.5-flash"],
        "default": "gemini-2.0-flash",
        "notes": "Long context, useful when the whole design must be re-read.",
    },
    "ollama": {
        "label": "Ollama (self-hosted)",
        "models": ["llama3.1", "qwen2.5:7b", "mistral"],
        "default": "llama3.1",
        "notes": "Runs locally: no per-call cost and no shared training data "
                 "with the hosted vendors, so genuinely independent.",
    },
}


def catalogue(configured_only: bool = False) -> list[dict[str, Any]]:
    """Vendors offered for review, and whether each is actually usable here."""
    from ..state import runtime_state

    out: list[dict[str, Any]] = []
    for vendor, meta in REVIEW_MODELS.items():
        config = runtime_state.provider_credentials.get(vendor)
        has_key = bool(getattr(config, "encrypted_api_key", None) or
                       getattr(config, "api_key", None))
        # A self-hosted runtime needs a reachable base URL, not a key.
        available = bool(config) if vendor == "ollama" else has_key
        if configured_only and not available:
            continue

        models = list(meta["models"])
        if vendor == "ollama" and config is not None:
            models = list(getattr(config, "ollama_models", None) or models)

        out.append({
            "provider": vendor, "label": meta["label"], "models": models,
            "default": meta["default"], "notes": meta["notes"],
            "available": available,
        })
    return out


def independent_of(generator_provider: str) -> list[str]:
    """The vendors that would be a real second opinion on this generator."""
    return [v for v in REVIEW_MODELS if v != (generator_provider or "").lower()]


def suggest(generator_provider: str) -> dict[str, str]:
    """A default layer-2 reviewer: configured, and from a different vendor."""
    candidates = [
        entry for entry in catalogue()
        if entry["available"] and entry["provider"] != (generator_provider or "").lower()
    ]
    if not candidates:
        return {}
    chosen = candidates[0]
    return {"provider": chosen["provider"], "model": chosen["default"]}


def is_known(provider: str) -> bool:
    return (provider or "").lower() in REVIEW_MODELS
