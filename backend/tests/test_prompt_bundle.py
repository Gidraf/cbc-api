"""Prompts as a project: download the folder, edit it anywhere, upload it back.

The console could only ever show one prompt at a time, and the work that
matters most is work across the whole set — making the chemistry fragment agree
with the notation block, making every authoring prompt use the same register
language. That work does not get done one textarea at a time.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from app.services import prompt_bundle

FRONTEND = Path(__file__).resolve().parents[2] / "frontend-web"


# ── the shape of the folder ──────────────────────────────────────────────────


def test_the_path_is_the_prompt_name() -> None:
    """Langfuse has no folders — a slash in the NAME is what the console renders
    as one — so the file tree and the prompt store are the same tree."""
    assert prompt_bundle.path_for("generate/lesson-plan") == "prompts/generate/lesson-plan.md"
    assert prompt_bundle.name_for("prompts/generate/lesson-plan.md") == "generate/lesson-plan"
    assert prompt_bundle.name_for("prompts/fragment/chemistry-equations.md") == "fragment/chemistry-equations"


def test_a_re_zipped_download_still_reads() -> None:
    """Unzipping a bundle and zipping the folder back up is what most people
    will do, and it adds a wrapping directory."""
    assert prompt_bundle.name_for("cbc-prompts/prompts/generate/diagrams.md") == "generate/diagrams"
    assert prompt_bundle.name_for("./prompts/BECF.md") == "BECF"


def test_nothing_outside_the_bundle_is_treated_as_a_prompt() -> None:
    """A zip can carry any path at all, including one that walks out of the
    directory it was extracted into."""
    for hostile in [
        "../../etc/passwd",
        "prompts/../../secrets.md",
        "/etc/passwd",
        "__MACOSX/prompts/._notes.md",
        "prompts/",
        "README.md",
        "manifest.json",
        "prompts/notes.txt",
    ]:
        assert prompt_bundle.name_for(hostile) == "", hostile


# ── the round trip ───────────────────────────────────────────────────────────


def test_every_prompt_appears_exactly_once() -> None:
    """A prompt is written under both a flat name and a foldered one, which is
    two names for one thing. Two identical files in the bundle is two files
    whose edits can disagree, and whichever was read first would win silently.
    """
    files = prompt_bundle.collect()
    assert files, "there are prompts to export"

    paths = [f.path for f in files]
    assert len(paths) == len(set(paths))

    texts = [f.text for f in files if len(f.text) > 400]
    assert len(texts) == len(set(texts)), "the same prompt was exported twice"

    # The foldered name is the one of record, and the flat one rides along.
    plan_file = next(f for f in files if f.name == "generate/lesson-plan")
    assert "note-generator" in plan_file.aliases


def test_the_bundle_round_trips_through_a_zip() -> None:
    blob = prompt_bundle.write_zip()
    back = prompt_bundle.read_zip(blob)

    for entry in prompt_bundle.collect():
        assert back[entry.name] == entry.text


def test_the_bundle_explains_the_slots_before_anyone_edits_them() -> None:
    """A renamed {{ slot }} does not fail loudly — it renders as nothing and the
    instruction that depended on it disappears."""
    archive = zipfile.ZipFile(io.BytesIO(prompt_bundle.write_zip()))
    # Normalised: these sentences are wrapped in the file, and a test that
    # breaks on a re-wrap is a test that gets deleted.
    readme = " ".join(archive.read("README.md").decode().split())

    assert "{{ level_register }}" in readme
    assert "does not fail loudly" in readme
    assert "A prompt is never deleted by an upload" in readme
    manifest = archive.read("manifest.json").decode()
    assert "generate/lesson-plan" in manifest


def test_a_bundle_that_is_not_prompts_is_refused_before_it_is_read() -> None:
    with pytest.raises(ValueError, match="not a readable zip"):
        prompt_bundle.read_zip(b"this is not a zip")

    empty = io.BytesIO()
    with zipfile.ZipFile(empty, "w") as z:
        z.writestr("holiday.jpg", "not a prompt")
    with pytest.raises(ValueError, match="No prompts found"):
        prompt_bundle.read_zip(empty.getvalue())


# ── what an upload will and will not do ──────────────────────────────────────


def _current() -> dict[str, str]:
    return {f.name: f.text for f in prompt_bundle.collect()}


def test_an_unchanged_bundle_writes_nothing() -> None:
    """Re-uploading what you downloaded should not add a version to every
    prompt in the store and make the version history useless."""
    result = prompt_bundle.plan(_current())

    assert result["summary"]["changed"] == 0
    assert result["summary"]["unchanged"] == len(_current())


def test_a_missing_file_is_never_a_deletion() -> None:
    """Half a bundle is a normal accident. A wiped prompt store is not a
    recoverable one."""
    current = _current()
    partial = {k: v for k, v in list(current.items())[:2]}

    result = prompt_bundle.plan(partial)

    assert result["summary"]["absent"] == len(current) - 2
    assert "left exactly as they are" in result["absent_note"]
    assert "never deletes" in result["absent_note"]
    for change in result["changes"]:
        assert change["action"] != "deleted"


def test_an_edit_that_loses_a_slot_is_saved_but_not_promoted() -> None:
    """The failure this exists for: {{ level_register }} renamed offline. The
    prompt still looks fine and comes back days later as output written for the
    wrong age."""
    current = _current()
    name = "generate/lesson-plan"
    broken = current[name].replace("{{ level_register }}", "{{ reading_level }}")
    assert broken != current[name], "the fixture must actually change the prompt"

    result = prompt_bundle.plan({name: broken})
    change = next(c for c in result["changes"] if c["name"] == name)

    assert change["action"] == "changed"
    assert change["promotable"] is False
    assert change["errors"], "the validator must say what broke"
    assert "staging" in change["note"] and "production keeps" in change["note"]
    assert result["summary"]["blocked"] == 1


def test_an_emptied_file_is_skipped_rather_than_obeyed() -> None:
    """An empty prompt removes a step's instructions entirely, and the
    generation carries on producing something."""
    result = prompt_bundle.plan({"generate/diagrams": "   \n"})
    change = result["changes"][0]

    assert change["action"] == "empty"
    assert change["promotable"] is False


def test_an_unrecognised_name_is_reported_not_created() -> None:
    """Nearly always a typo in a folder name — and accepting it creates an
    orphan in Langfuse while the real prompt keeps serving its old text."""
    result = prompt_bundle.plan({"generate/lesson-plans": "x" * 500})
    change = result["changes"][0]

    assert change["action"] == "unknown"
    assert "typo" in change["note"]

    allowed = prompt_bundle.plan({"generate/lesson-plans": "x" * 500}, allow_new=True)
    assert allowed["changes"][0]["action"] == "new"


def test_nothing_is_written_until_the_plan_has_been_read() -> None:
    """Same two-step as every other destructive path here: the first call says
    what would happen, the second does it."""
    current = _current()
    name = "generate/diagrams"
    edited = {name: current[name] + "\n\nOne more rule.\n"}

    dry = prompt_bundle.apply_bundle(edited)
    assert dry["applied"] is False
    assert "written" not in dry
    assert dry["confirm_with"] == "APPLY"
    assert dry["summary"]["changed"] == 1


def test_a_failed_write_is_never_reported_as_a_success(monkeypatch) -> None:
    """Recording a push that did not happen is how a rewritten prompt silently
    keeps serving the old text."""
    from app.services import prompt_sync

    def explode(name, text, *, promote=True):
        raise RuntimeError("Langfuse is down")

    monkeypatch.setattr(prompt_sync, "push_one", explode)

    current = _current()
    name = "generate/diagrams"
    result = prompt_bundle.apply_bundle(
        {name: current[name] + "\n\nOne more rule.\n"}, confirm="APPLY"
    )

    assert result["written"] == []
    assert result["failed"], "a failure must be reported as one"
    assert "still serve the old text" in result["message"]


def test_both_names_are_written_so_the_pair_cannot_drift(monkeypatch) -> None:
    """A prompt lives under a flat name and a foldered one. Writing only one
    leaves whichever the reader tries first winning silently."""
    from app.services import prompt_sync

    pushed: list[str] = []
    monkeypatch.setattr(
        prompt_sync, "push_one",
        lambda name, text, *, promote=True: pushed.append(name) or {"prompt": name},
    )

    current = _current()
    name = "generate/lesson-plan"
    prompt_bundle.apply_bundle(
        {name: current[name] + "\n\nOne more rule.\n"}, confirm="APPLY"
    )

    assert "generate/lesson-plan" in pushed
    assert "note-generator" in pushed


# ── the route ────────────────────────────────────────────────────────────────


def test_the_bundle_routes_are_reachable() -> None:
    """`/prompts/export` must be registered before `/{grade}`, or the board's
    catch-all swallows it and the download returns a project."""
    from app.routes.pipelines import router

    paths = [getattr(r, "path", "") for r in router.routes]
    assert "/api/v1/pipelines/prompts/export" in paths
    assert "/api/v1/pipelines/prompts/import" in paths
    assert paths.index("/api/v1/pipelines/prompts/export") < paths.index(
        "/api/v1/pipelines/{grade}"
    )


# ── the console ──────────────────────────────────────────────────────────────


def test_the_console_offers_the_round_trip_in_both_directions() -> None:
    screen = " ".join((FRONTEND / "src/views/PromptFragments.tsx").read_text().split())

    assert "Download all prompts" in screen
    assert "See what would change" in screen
    # The download must be honest about what it contains, or somebody edits a
    # file expecting it to be their last edit and it is the built-in default.
    assert "currently serving, not the built-in defaults" in screen


def test_the_upload_shows_the_plan_before_it_writes() -> None:
    """Prompts are the behaviour of every generator in the system."""
    screen = " ".join((FRONTEND / "src/views/PromptFragments.tsx").read_text().split())

    assert "Nothing has been written yet" in screen
    assert "confirm: plan.confirm_with" in screen
    # Choosing a different file must throw the plan away, or the confirm button
    # applies a bundle nobody read the plan for.
    assert "setPlan(null)" in screen


def test_a_prompt_that_would_break_production_is_shown_as_such() -> None:
    screen = " ".join((FRONTEND / "src/views/PromptFragments.tsx").read_text().split())

    assert "staging only" in screen
    assert "would break production" in screen


def test_the_validator_checks_the_foldered_name_too() -> None:
    """Bindings are keyed on the flat name, so validating `generate/lesson-plan`
    found none and it passed every check by not being checked — it could lose
    {{ level_register }} and be promoted to production clean."""
    from app.services import prompt_validators

    assert prompt_validators.flat_name("generate/lesson-plan") == "note-generator"
    assert prompt_validators.flat_name("note-generator") == "note-generator"
    assert prompt_validators.flat_name("fragment/chemistry-equations") == "fragment/chemistry-equations"

    from app.services.prompt_sync import _all_prompts

    text = _all_prompts()["generate/lesson-plan"]
    broken = text.replace("{{ level_register }}", "{{ reading_level }}")
    report = prompt_validators.validate("generate/lesson-plan", broken)
    assert not report.promotable
    assert any("reading_level" in f.message for f in report.errors)
