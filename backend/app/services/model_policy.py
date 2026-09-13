"""Which models this system will run, and what it does with the rest.

The generators are expensive to run and the content they write is sold, so
there is no economy in a small model: a guide that comes back wrong four
passes running costs more than the model that would have got it right. And
a model nobody chose must never run by accident. gpt-4o-mini sat in a dozen
fallbacks — the router's unbound-stage default, the normaliser's empty-name
default, the console's bootstrap button, the Celery worker with no bindings
loaded — and for two days runs on it were compared with runs on the model
the console showed as if they were one pipeline.

One list per provider, one default per provider, and a rule: a retired id
becomes the provider's default, with a warning, wherever it is met.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger("cbc-model-policy")

# The advanced models, newest first. The first is the provider's default
# unless the environment says otherwise (OPENAI_DEFAULT_MODEL / _LIGHT_MODEL).
OPENAI: tuple[str, ...] = (
    "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.6-sol", "gpt-5.5", "gpt-5.4",
)
ANTHROPIC: tuple[str, ...] = (
    "claude-sonnet-5", "claude-opus-5", "claude-fable-5-1", "claude-haiku-4-5-20251001",
)
GEMINI: tuple[str, ...] = ("gemini-2.5-pro", "gemini-2.5-flash")

# Anything from these families is retired: a stage bound to one runs on the
# provider's default instead.
_RETIRED = re.compile(
    r"^(gpt-?4|gpt-?3|4o|3\.5|35$|chatgpt|o1(-|$)|o3(-|$)|o4-mini|claude-3|claude-2"
    r"|claude-instant|gemini-1\.|gemini-2\.0|gemini-pro$|gemini-flash$)", re.I)


def is_retired(model: str) -> bool:
    return bool(_RETIRED.match((model or "").strip().lower()))


def default_for(provider: str) -> str:
    """The provider's default model."""
    provider = (provider or "").strip().lower()
    if provider == "openai":
        from ..settings import settings

        return settings.openai_default_model
    if provider == "anthropic":
        return ANTHROPIC[0]
    if provider == "gemini":
        return GEMINI[0]
    return ""


def advanced_for(provider: str) -> tuple[str, ...]:
    provider = (provider or "").strip().lower()
    if provider == "openai":
        from ..settings import settings

        # The configured defaults first, then the rest of the family.
        chosen = [settings.openai_default_model, settings.openai_light_model]
        return tuple(dict.fromkeys([*chosen, *OPENAI]))
    if provider == "anthropic":
        return ANTHROPIC
    if provider == "gemini":
        return GEMINI
    return ()


def enforce(provider: str, model: str, *, where: str = "") -> str:
    """The model to actually use: the one given, unless it is empty or
    retired, in which case the provider's default — and a line in the log."""
    provider = (provider or "").strip().lower()
    wanted = (model or "").strip()
    if provider not in ("openai", "anthropic", "gemini"):
        return wanted
    if not wanted or wanted.lower() in {"null", "undefined", "default", "none"}:
        return default_for(provider)
    if is_retired(wanted):
        chosen = default_for(provider)
        logger.warning("%s: %r is retired here; using %s.", where or provider, wanted, chosen)
        return chosen
    return wanted
