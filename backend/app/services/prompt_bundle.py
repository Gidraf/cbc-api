"""Every prompt as a folder of files, and back again.

Prompts are the part of this system that most needs editing and is worst served
by editing it one textarea at a time. There are thirty-odd of them, they refer
to each other, and the interesting work — making the chemistry fragment agree
with the notation block, making every authoring prompt use the same register
language — is work across the whole set at once. A console that only ever shows
one is a console in which that work does not get done.

So: download the lot as a folder of Markdown files, open it as a project in
whatever tool you actually write in, and bring it back as one upload.

Three decisions the round-trip depends on:

*   **One file per prompt, not one per name.** A prompt is written to Langfuse
    under both a flat name (`note-generator`) and a foldered one
    (`generate/lesson-plan`), which is two names for one thing. Exporting both
    would hand the editor two identical files whose edits could disagree, and
    whichever was read first would win silently. The bundle carries the
    foldered name, and the import writes back to every alias.

*   **A missing file is not a deletion.** Bundles get partially copied,
    filtered, and hand-assembled. Treating absence as intent would let a
    mis-zipped folder wipe the prompt store, so absence is reported and
    nothing else.

*   **A prompt that fails validation is written but not promoted.** An offline
    edit that renames `{{ level_register }}` still *looks* fine — it fails at
    generation time, days later, as output that quietly lost its register. The
    validator catches it here, the text is saved so the editing is not lost,
    and production keeps serving the version that works.
"""
from __future__ import annotations

import io
import json
import logging
import posixpath
import zipfile
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("cbc-prompt-bundle")

ROOT = "prompts"
SUFFIX = ".md"

# A bundle is text. Anything near this is not a set of prompts.
MAX_ZIP_BYTES = 8 * 1024 * 1024
MAX_FILE_BYTES = 512 * 1024
MAX_FILES = 500

# The word, not a boolean: a boolean is too easy to send by accident from a
# form or a retried request. Same shape as the pipeline reset.
CONFIRM = "APPLY"

# Two names for one prompt, where the pair is not in FOLDERS.
_EXTRA_ALIASES: dict[str, str] = {"BECF": "cbc-master-context"}


@dataclass(slots=True)
class BundleFile:
    """One prompt, as it will appear in the folder."""

    path: str
    name: str
    text: str
    aliases: list[str] = field(default_factory=list)
    source: str = "built-in"
    version: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "name": self.name,
            "aliases": self.aliases,
            "source": self.source,
            "version": self.version,
            "characters": len(self.text),
        }


def _canonical(name: str) -> str:
    """The one name this prompt is filed under."""
    from .langfuse_context import langfuse_context_service

    if name in _EXTRA_ALIASES:
        return _EXTRA_ALIASES[name]
    return langfuse_context_service.FOLDERS.get(name, name)


def path_for(name: str) -> str:
    return f"{ROOT}/{name}{SUFFIX}"


def name_for(path: str) -> str:
    """The prompt name a bundle path refers to, or "" if it is not one."""
    clean = path.replace("\\", "/").strip()
    # Editors and zip tools add these; they are not prompts.
    if not clean or clean.endswith("/"):
        return ""
    parts = [p for p in clean.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        return ""
    if "__MACOSX" in parts or any(p.startswith("._") for p in parts):
        return ""
    # Tolerate a wrapping directory, which is what unzipping and re-zipping a
    # download produces, and what most editors hand back.
    if ROOT in parts:
        parts = parts[parts.index(ROOT) + 1:]
    else:
        return ""
    if not parts or not parts[-1].endswith(SUFFIX):
        return ""
    parts[-1] = parts[-1][: -len(SUFFIX)]
    return posixpath.join(*parts)


def _live_text(name: str, built_in: str) -> tuple[str, str, Any]:
    """What is actually being served, and where it came from.

    Exporting the built-in text for a prompt somebody edited in Langfuse would
    hand them a file that silently reverts their edit the moment it is uploaded
    back — the round-trip has to start from what is in use.
    """
    from .langfuse_context import langfuse_context_service

    try:
        found = langfuse_context_service.get_prompt(name)
    except Exception as exc:  # noqa: BLE001
        logger.debug("No stored prompt for %s (%s); exporting the built-in text.", name, exc)
        return built_in, "built-in", None
    text = getattr(found, "prompt", "") or ""
    if not text.strip():
        return built_in, "built-in", None
    if text.strip() == built_in.strip():
        return built_in, "built-in", getattr(found, "version", None)
    return text, "langfuse", getattr(found, "version", None)


def collect() -> list[BundleFile]:
    """Every prompt, once, with the text currently in use."""
    from .prompt_sync import _all_prompts

    everything = _all_prompts()
    grouped: dict[str, list[str]] = {}
    for name in everything:
        grouped.setdefault(_canonical(name), []).append(name)

    files: list[BundleFile] = []
    for canonical, names in sorted(grouped.items()):
        built_in = everything.get(canonical) or everything[names[0]]
        text, source, version = _live_text(canonical, built_in)
        files.append(
            BundleFile(
                path=path_for(canonical),
                name=canonical,
                text=text,
                aliases=sorted(n for n in names if n != canonical),
                source=source,
                version=version,
            )
        )
    return files


README = """# CBC prompts

Every prompt this system runs on, one file each. Edit them here, zip the folder,
and upload it on the Domain prompts screen.

## What you are looking at

`prompts/generate/lesson-plan.md` is the prompt named `generate/lesson-plan`.
The path IS the name — Langfuse has no folders, so a slash in the name is what
the console renders as one. Renaming a file renames the prompt, which is almost
never what you meant: the pipeline asks for prompts by name, and a renamed one
is a missing one.

Some prompts are stored under a second, older name as well. `manifest.json`
lists those. You do not need to do anything about them — the upload writes both,
so they cannot drift apart.

## The `{{ slots }}`

`{{ level_register }}`, `{{ design_extract }}`, `{{ faith_scope }}` and the rest
are filled in by the code at generation time. **Renaming or deleting one does
not fail loudly.** It renders as an empty string, and the instruction that
depended on it silently disappears — a lesson plan that lost `{{ level_register }}`
still comes back looking like a lesson plan, written for the wrong age.

The upload checks every slot against what the code actually supplies. A prompt
that fails is still saved, so your editing is not lost, but it is left in
staging and production keeps serving the previous version until you fix it.

## What the upload will and will not do

*   Files you changed are written as new versions.
*   Files you did not change are skipped — no version churn.
*   **Files you deleted are left alone.** A prompt is never deleted by an
    upload. Half a bundle is a normal accident; a wiped prompt store is not a
    recoverable one.
*   Files whose name matches no known prompt are reported and skipped, unless
    you explicitly allow new ones. That is almost always a typo in a folder
    name, and accepting it would create an orphan while the real prompt keeps
    serving its old text.

Nothing is written until you have seen the list of what would change and
confirmed it.
"""


def write_zip(files: list[BundleFile] | None = None) -> bytes:
    """The folder, as one download."""
    files = collect() if files is None else files
    buffer = io.BytesIO()
    manifest = {
        "prompts": [f.to_dict() for f in files],
        "count": len(files),
        "root": ROOT,
        "note": "The path is the prompt name. See README.md before editing.",
    }
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("README.md", README)
        archive.writestr("manifest.json", json.dumps(manifest, indent=2))
        for entry in files:
            archive.writestr(entry.path, entry.text)
    return buffer.getvalue()


def read_zip(blob: bytes) -> dict[str, str]:
    """The prompts in an uploaded bundle, by name.

    Everything a zip can carry that is not a prompt — directories, the editor's
    dotfiles, a traversal path, a file large enough to be a mistake — is
    dropped here rather than defended against later.
    """
    if len(blob) > MAX_ZIP_BYTES:
        raise ValueError(
            f"That bundle is {len(blob) // 1024}KB. Prompts are text; something "
            "else is in there."
        )
    try:
        archive = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile as exc:
        raise ValueError(f"That is not a readable zip file ({exc}).") from exc

    found: dict[str, str] = {}
    for info in archive.infolist():
        if info.is_dir() or len(found) >= MAX_FILES:
            continue
        name = name_for(info.filename)
        if not name:
            continue
        if info.file_size > MAX_FILE_BYTES:
            raise ValueError(
                f"'{info.filename}' is {info.file_size // 1024}KB, which is not a prompt."
            )
        found[name] = archive.read(info).decode("utf-8", errors="replace")
    if not found:
        raise ValueError(
            f"No prompts found. Files must be under '{ROOT}/' and end in "
            f"'{SUFFIX}' — the same shape the download has."
        )
    return found


@dataclass(slots=True)
class Change:
    name: str
    action: str          # changed | new | unchanged | unknown | empty
    aliases: list[str] = field(default_factory=list)
    was: int = 0
    now: int = 0
    promotable: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "action": self.action, "aliases": self.aliases,
            "was": self.was, "now": self.now, "promotable": self.promotable,
            "errors": self.errors, "warnings": self.warnings, "note": self.note,
        }


def plan(incoming: dict[str, str], *, allow_new: bool = False) -> dict[str, Any]:
    """What an upload would do, before it does any of it."""
    from .prompt_validators import validate

    current = {f.name: f for f in collect()}
    changes: list[Change] = []

    for name in sorted(incoming):
        text = incoming[name]
        known = current.get(name)
        if known is None:
            changes.append(Change(
                name=name,
                action="new" if allow_new else "unknown",
                now=len(text),
                note=(
                    "Not a prompt this system asks for. Nothing reads it, so it "
                    "would sit in Langfuse doing nothing — check the folder name "
                    "for a typo."
                    if not allow_new else
                    "New prompt. Nothing reads it until code asks for it by name."
                ),
            ))
            continue
        if not text.strip():
            changes.append(Change(
                name=name, action="empty", was=len(known.text), promotable=False,
                errors=["The file is empty."],
                note="An empty prompt removes this step's instructions entirely. "
                     "Skipped — delete the prompt deliberately if that is the intent.",
            ))
            continue
        if text.strip() == known.text.strip():
            changes.append(Change(name=name, action="unchanged",
                                  was=len(known.text), now=len(text),
                                  aliases=known.aliases))
            continue

        report = validate(name, text)
        changes.append(Change(
            name=name, action="changed", aliases=known.aliases,
            was=len(known.text), now=len(text),
            promotable=report.promotable,
            errors=[f.message for f in report.errors],
            warnings=[f.message for f in report.warnings],
            note="" if report.promotable else
                 "Will be saved to staging; production keeps the current version "
                 "until this is fixed.",
        ))

    absent = sorted(set(current) - set(incoming))
    changed = [c for c in changes if c.action == "changed"]
    return {
        "changes": [c.to_dict() for c in changes],
        "absent": absent,
        "absent_note": (
            f"{len(absent)} prompt(s) are not in the bundle and have been left "
            "exactly as they are. An upload never deletes a prompt."
        ) if absent else "",
        "summary": {
            "changed": len(changed),
            "promotable": len([c for c in changed if c.promotable]),
            "blocked": len([c for c in changed if not c.promotable]),
            "unchanged": len([c for c in changes if c.action == "unchanged"]),
            "new": len([c for c in changes if c.action == "new"]),
            "unknown": len([c for c in changes if c.action == "unknown"]),
            "empty": len([c for c in changes if c.action == "empty"]),
            "absent": len(absent),
        },
        "applied": False,
        "confirm_with": CONFIRM,
    }


def apply_bundle(
    incoming: dict[str, str], *, allow_new: bool = False, confirm: str = ""
) -> dict[str, Any]:
    """Write what the plan said, once somebody has read the plan."""
    from .prompt_sync import push_one

    result = plan(incoming, allow_new=allow_new)
    if confirm != CONFIRM:
        return result

    current = {f.name: f for f in collect()}
    written: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []

    for change in result["changes"]:
        if change["action"] not in ("changed", "new"):
            continue
        name = change["name"]
        text = incoming[name]
        # Every alias, or the pair drifts and whichever the reader tries first
        # wins silently.
        targets = [name] + list(current.get(name).aliases if name in current else [])
        for target in targets:
            try:
                push_one(target, text, promote=bool(change["promotable"]))
                written.append({"prompt": target, "promoted": change["promotable"]})
            except Exception as exc:  # noqa: BLE001
                logger.error("Prompt '%s' was NOT written: %s", target, exc)
                failed.append({"prompt": target, "error": str(exc)[:300]})

    result["applied"] = True
    result["written"] = written
    result["failed"] = failed
    result["message"] = _message(result, written, failed)
    return result


def _message(result: dict[str, Any], written: list, failed: list) -> str:
    summary = result["summary"]
    parts = []
    if written:
        parts.append(f"{len(written)} prompt version(s) written")
    if summary["blocked"]:
        parts.append(
            f"{summary['blocked']} left in staging because production would "
            "break — the previous version is still serving those"
        )
    if failed:
        parts.append(f"{len(failed)} could NOT be written, so those still serve the old text")
    if summary["unchanged"]:
        parts.append(f"{summary['unchanged']} unchanged")
    if summary["absent"]:
        parts.append(f"{summary['absent']} not in the bundle and left alone")
    return ". ".join(parts) + "." if parts else "Nothing to do."
