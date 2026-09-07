"""Prefer what somebody has edited in the console over what the code shipped.

Three modules had grown their own copy of the same eight lines: try Langfuse,
fall back to the built-in, never raise. `prompt_fragments` had it, `notation`
had it through the fragments, and the level and teacher registers had none at
all — which is why the one block a head of department would most want to argue
with was the one block that needed a deploy to change.

The shape is deliberate in both directions. The CODE holds the default, so a
fresh deployment works with no prompt store at all and nobody has to seed
before they can generate. LANGFUSE holds the improvement, so a professional
judgement — "you cannot assume a Grade 7 teacher can run an investigation" —
is a person editing a page rather than an engineer editing a file.

An empty stored value is ignored rather than honoured. Blanking a prompt is
almost always an accident or a half-finished edit, and honouring it removes the
rules silently, at generation time, from every station at once.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("cbc-prompt-store")


def stored(name: str) -> str:
    """What the console holds under this name, or "" — never raises."""
    try:
        from .langfuse_context import langfuse_context_service

        found = langfuse_context_service.get_prompt(name)
        text = getattr(found, "prompt", "") or ""
        return text if text.strip() else ""
    except Exception as exc:  # noqa: BLE001
        logger.debug("No stored prompt %s (%s); using the built-in.", name, exc)
        return ""


def stored_or(name: str, default: str) -> str:
    """The edited text where there is one, the shipped text where there is not."""
    return stored(name) or default


def render(name: str, default: str, **slots: object) -> str:
    """Stored-or-default text with `{{ slot }}` filled in.

    The assembly stays in Python because it is per call — how many modules this
    sub-strand is funded for, how long each one runs. Only the WORDS move, and
    the words are the part somebody wants to improve at four in the afternoon
    without waiting for a deploy.
    """
    text = stored_or(name, default)
    for slot, value in slots.items():
        text = text.replace("{{ " + slot + " }}", "" if value is None else str(value))
    return text
