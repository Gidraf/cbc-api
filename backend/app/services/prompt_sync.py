"""Push prompt changes the way migrations push schema changes.

Prompt text is deployed code. It drifted from the database exactly the way a
schema drifts: the note generator gained {{ design_extract }} and
{{ time_allocation }}, and every generation ran with those slots stripped until
somebody remembered to press Seed. Nothing failed; the notes were simply
written without the design's own detail, and looked fine.

So the seed is now a startup step keyed on the content hash. A prompt whose
text has not changed is not rewritten — pushing all fifteen on every boot would
add fifteen versions a day to Langfuse and make the version history useless.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("cbc-prompt-sync")

# Every label get_prompt() tries. "production" and "latest" are tried BEFORE
# "prod", so a version missing them stays invisible however new it is.
LABELS = ["production", "latest", "prod", "staging", "dev"]


@dataclass(slots=True)
class SyncReport:
    checked: int = 0
    pushed: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    failed: list[dict[str, str]] = field(default_factory=list)
    skipped: str = ""

    @property
    def status(self) -> str:
        if self.skipped:
            return "skipped"
        return "error" if self.failed else "ok"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "checked": self.checked,
            "pushed": self.pushed,
            "unchanged": self.unchanged,
            "failed": self.failed,
            "skipped": self.skipped,
            "message": self._message(),
        }

    def _message(self) -> str:
        if self.skipped:
            return self.skipped
        if self.failed:
            return (
                f"{len(self.failed)} prompt(s) could not be written. The old text is "
                "still being served for those, so the changes have NOT taken effect."
            )
        if not self.pushed:
            return f"All {self.checked} prompt(s) already current."
        return f"{len(self.pushed)} prompt(s) updated: {', '.join(self.pushed)}."


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def _all_prompts() -> dict[str, str]:
    from .langfuse_seed import SEED_AGENT_PROMPTS, SEED_MASTER_CONTEXT

    prompts: dict[str, str] = {
        "BECF": SEED_MASTER_CONTEXT,
        "cbc-master-context": SEED_MASTER_CONTEXT,
    }
    prompts.update(SEED_AGENT_PROMPTS)
    return prompts


def _applied() -> dict[str, str]:
    from ..infra.db import fetch_all

    try:
        rows = fetch_all("SELECT name, content_hash FROM prompt_versions") or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read prompt_versions: %s", exc)
        return {}
    return {str(r["name"]): str(r["content_hash"]) for r in rows}


def _record(name: str, digest: str, version: Any) -> None:
    from ..infra.db import execute

    try:
        execute(
            """
            INSERT INTO prompt_versions (name, content_hash, remote_version, applied_at)
            VALUES (:name, :hash, :version, NOW())
            ON CONFLICT (name) DO UPDATE SET
                content_hash = EXCLUDED.content_hash,
                remote_version = EXCLUDED.remote_version,
                applied_at = NOW()
            """,
            {"name": name, "hash": digest,
             "version": int(version) if isinstance(version, int) else None},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not record prompt '%s': %s", name, exc)


def sync_prompts(force: bool = False) -> SyncReport:
    """Write every prompt whose text has changed since it was last written."""
    from ..settings import settings

    report = SyncReport()
    prompts = _all_prompts()
    report.checked = len(prompts)

    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        report.skipped = "Langfuse credentials not configured; local fallback in use."
        return report

    applied = {} if force else _applied()
    pending = {
        name: text for name, text in prompts.items()
        if applied.get(name) != content_hash(text)
    }
    if not pending:
        report.unchanged = sorted(prompts)
        logger.info("Prompts already current (%d checked).", report.checked)
        return report

    try:
        from langfuse import Langfuse

        client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
    except Exception as exc:  # noqa: BLE001
        report.skipped = f"Could not connect to Langfuse: {exc}"
        logger.warning("%s", report.skipped)
        return report

    report.unchanged = sorted(set(prompts) - set(pending))
    for name, text in pending.items():
        try:
            created = client.create_prompt(
                name=name, prompt=text, type="text", labels=list(LABELS),
            )
            version = getattr(created, "version", None)
            _record(name, content_hash(text), version)
            report.pushed.append(f"{name} v{version}" if version else name)
            logger.info("Prompt '%s' updated (version %s).", name, version)
        except Exception as exc:  # noqa: BLE001
            # Recording this as pushed is how a rewritten prompt silently keeps
            # serving the old text.
            logger.error("Prompt '%s' was NOT written: %s", name, exc)
            report.failed.append({"prompt": name, "error": str(exc)[:300]})

    return report
