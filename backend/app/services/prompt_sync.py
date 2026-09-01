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

# A push lands here first. Every prompt used to carry all five labels, so
# `production` and `dev` always pointed at the same version and there was no
# moment at which a bad edit could be caught — it was live the instant it was
# written.
STAGING_LABELS = ["latest", "staging", "dev"]

# And is promoted to these only once the validators pass. A prompt that fails
# stays readable in staging while the previous version keeps serving, which is
# the behaviour a failed deploy should have.
PRODUCTION_LABELS = ["production", "prod"]


@dataclass(slots=True)
class SyncReport:
    checked: int = 0
    pushed: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    staged: list[str] = field(default_factory=list)
    failed: list[dict[str, str]] = field(default_factory=list)
    validation: dict[str, Any] = field(default_factory=dict)
    skipped: str = ""

    @property
    def status(self) -> str:
        if self.skipped:
            return "skipped"
        if self.failed:
            return "error"
        # A staged prompt is not a failure — it was written — but production is
        # still serving the old text, so "ok" would be a lie.
        return "staged" if self.staged else "ok"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "checked": self.checked,
            "pushed": self.pushed,
            "unchanged": self.unchanged,
            "staged": self.staged,
            "validation": self.validation,
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
        parts = []
        if self.pushed:
            parts.append(f"{len(self.pushed)} promoted: {', '.join(self.pushed)}")
        if self.staged:
            parts.append(
                f"{len(self.staged)} written to staging but NOT promoted "
                f"(production still serves the previous version): "
                f"{', '.join(self.staged)}"
            )
        if not parts:
            return f"All {self.checked} prompt(s) already current."
        return ". ".join(parts) + "."


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def _all_prompts() -> dict[str, str]:
    """Every prompt to write, under both its flat name and its folder.

    Langfuse has no folders — a prompt's NAME is its path, and a slash is what
    the console renders as one. Nineteen prompts in a flat list is a list
    nobody edits.

    Both are written, and the reader prefers the foldered one. Writing only the
    folder would orphan every edit already made against the flat name, which is
    the work this is meant to make easier, thrown away to make it tidier.
    """
    from .langfuse_context import langfuse_context_service
    from .langfuse_seed import SEED_AGENT_PROMPTS, SEED_MASTER_CONTEXT

    prompts: dict[str, str] = {
        "BECF": SEED_MASTER_CONTEXT,
        "cbc-master-context": SEED_MASTER_CONTEXT,
    }
    prompts.update(SEED_AGENT_PROMPTS)
    for name, text in list(SEED_AGENT_PROMPTS.items()):
        foldered = langfuse_context_service.FOLDERS.get(name)
        if foldered:
            prompts[foldered] = text

    # Each domain fragment as its own prompt, under `fragment/<name>`.
    # Education is wide, and a prompt that must serve every subject is a prompt
    # nobody improves: change the paragraph about balancing equations and you
    # have edited the prompt that writes a PP1 singing lesson. Separate, small
    # and individually editable is the only way somebody who knows chemistry
    # will touch the chemistry.
    from .prompt_fragments import seed_prompts

    prompts.update(seed_prompts())
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

    from .prompt_validators import validate

    report.unchanged = sorted(set(prompts) - set(pending))
    for name, text in pending.items():
        check = validate(name, text)
        report.validation[name] = check.to_dict()

        # Staging first, always: even a prompt that passes should exist as a
        # version before it serves, so a rollback has something to roll back to.
        labels = list(STAGING_LABELS)
        if check.promotable:
            labels += PRODUCTION_LABELS
        else:
            logger.error(
                "Prompt '%s' FAILED validation and will not be promoted: %s",
                name, "; ".join(f.message for f in check.errors),
            )

        try:
            created = client.create_prompt(
                name=name, prompt=text, type="text", labels=labels,
            )
            version = getattr(created, "version", None)
            _record(name, content_hash(text), version)
            entry = f"{name} v{version}" if version else name
            if check.promotable:
                report.pushed.append(entry)
                logger.info("Prompt '%s' updated and promoted (version %s).", name, version)
            else:
                report.staged.append(entry)
                logger.warning(
                    "Prompt '%s' is in staging at version %s; production still serves "
                    "the previous version.", name, version,
                )
        except Exception as exc:  # noqa: BLE001
            # Recording this as pushed is how a rewritten prompt silently keeps
            # serving the old text.
            logger.error("Prompt '%s' was NOT written: %s", name, exc)
            report.failed.append({"prompt": name, "error": str(exc)[:300]})

    return report


def promote(name: str) -> dict[str, Any]:
    """Move `production` and `prod` onto a prompt's latest version.

    Used after a staged prompt's failures are fixed, or deliberately by an
    operator who has read the staged version and accepts it.
    """
    from ..errors import raise_api_error
    from ..settings import settings
    from .prompt_validators import validate

    prompts = _all_prompts()
    if name not in prompts:
        raise_api_error("DATASET_ITEM_NOT_FOUND", f"No seeded prompt named '{name}'.")

    check = validate(name, prompts[name])
    if not check.promotable:
        raise_api_error(
            "VALIDATION_FAILED",
            f"'{name}' still fails validation: "
            + "; ".join(f.message for f in check.errors),
            detail=check.to_dict(),
        )

    from langfuse import Langfuse

    client = Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        host=settings.langfuse_host,
    )
    created = client.create_prompt(
        name=name, prompt=prompts[name], type="text",
        labels=list(STAGING_LABELS) + list(PRODUCTION_LABELS),
    )
    version = getattr(created, "version", None)
    _record(name, content_hash(prompts[name]), version)
    return {"status": "promoted", "prompt": name, "version": version}


def push_one(name: str, text: str) -> dict[str, Any]:
    """Write one prompt, now, with whatever text a person has just improved.

    Distinct from `sync_prompts`, which writes the built-in text for everything
    that has changed since it was last written. This is the console's edit
    path: a person has rewritten one domain fragment and expects that one
    fragment to change, and nothing else.
    """
    from langfuse import Langfuse

    from ..settings import settings

    if not text.strip():
        raise ValueError("Refusing to write an empty prompt.")

    client = Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        host=settings.langfuse_host,
    )
    created = client.create_prompt(
        name=name, prompt=text, type="text",
        labels=list(STAGING_LABELS) + list(PRODUCTION_LABELS),
    )
    version = getattr(created, "version", None)
    _record(name, content_hash(text), version)
    logger.info("Prompt '%s' written at version %s.", name, version)
    return {"prompt": name, "version": version}
