"""One model per station, not one model for six stations at once.

Six stages did the work of fourteen: `notes_generation` resolved the notes AND
the strand generator, the sub-strand generator, the design ingest, the
grade-scope derivation and the profile writer. Moving the notes to a stronger
model moved six other things with them — including two that read a 296-page
document and are billed by the page.
"""
from __future__ import annotations

import pathlib
import re

from app.services import stages

BACKEND = pathlib.Path(__file__).resolve().parents[1]
FRONTEND = BACKEND.parent / "frontend-web"


def _call_sites() -> dict[str, list[str]]:
    """Which stage each generation route resolves."""
    found: dict[str, list[str]] = {}
    for path in ("app/routes/curriculum.py", "app/routes/questions.py",
                 "app/services/content_type_classifier.py"):
        source = (BACKEND / path).read_text()
        for stage in re.findall(r'resolve_for_stage\("([a-z_]+)"\)', source):
            found.setdefault(stage, []).append(path)
    return found


def test_the_notes_stage_drives_only_the_notes():
    """It drove seven call sites, so the notes could not be moved to a better
    model on their own."""
    sites = _call_sites()
    assert len(sites.get("notes_generation", [])) == 1


def test_every_station_has_its_own_stage():
    sites = _call_sites()
    for stage in ("structure_generation", "ingest_extraction", "media_generation",
                  "simulation_generation", "profile_generation",
                  "diagram_generation", "activity_generation", "question_generation"):
        assert stage in sites, stage
        assert stage in stages.NAMES, f"{stage} is resolved but not declared"


def test_every_resolved_stage_is_a_declared_one():
    """A stage nobody declared cannot be bound through the admin API, so it
    would silently fall through to the hardcoded default for ever."""
    for stage in _call_sites():
        assert stage in stages.NAMES, stage


def test_an_unbound_stage_inherits_rather_than_downgrading():
    """Splitting one stage into six would otherwise drop every new one to the
    hardcoded fallback the moment the code shipped — a silent downgrade on the
    run after a deploy."""
    assert stages.chain("structure_generation") == [
        "structure_generation", "notes_generation",
    ]
    assert stages.chain("ingest_extraction") == [
        "ingest_extraction", "structure_generation", "notes_generation",
    ]
    assert stages.chain("media_generation") == [
        "media_generation", "diagram_generation",
    ]

    source = (BACKEND / "app/services/provider_router.py").read_text()
    resolve = source[source.index("def resolve_for_stage"):]
    assert "for candidate in chain(stage):" in resolve


def test_the_fallback_chain_cannot_loop():
    """A mis-edited fallback pointing at itself would hang the first request
    that touched it."""
    for stage in stages.STAGES:
        walked = stages.chain(stage.name)
        assert len(walked) == len(set(walked)), stage.name


def test_the_admin_api_and_the_router_share_one_list():
    """Two lists drift, and the one that drifts is the one nobody reads."""
    from app.main import STAGE_NAMES

    assert STAGE_NAMES is stages.NAMES


def test_the_bindings_can_be_read_not_only_written():
    """"Which model writes the notes" had no answer short of reading the
    source: the bindings were writable and not readable."""
    from app.main import app

    paths = {getattr(r, "path", "") for r in app.routes}
    assert "/admin/pipeline-bindings" in paths


def test_each_stage_says_what_it_drives_and_what_it_costs():
    """An operator paying per token should see what they are buying, and the
    two extremes named: the ingest is billed by the page, the notes are where a
    weak model shows first."""
    for stage in stages.STAGES:
        assert stage.label and stage.drives, stage.name

    ingest = stages.BY_NAME["ingest_extraction"]
    assert "billed by the page" in f"{ingest.drives} {ingest.guidance}"
    assert "weak model shows first" in stages.BY_NAME["notes_generation"].guidance


def test_the_console_does_not_pretend_to_know_which_models_exist():
    """This service keeps no list of what an account can call, and inventing
    one would fail at generation time with a confusing error."""
    source = (BACKEND / "app/main.py").read_text()
    listing = source[source.index("def list_stage_bindings"):]
    listing = listing[: listing.index("@app.post")]
    assert "does not keep a list of which models" in listing

    view = " ".join((FRONTEND / "src/views/StageModels.tsx").read_text().split())
    # A free-text field, not a dropdown of names we guessed.
    assert 'placeholder="model id"' in view
    assert "inherited" in view


def test_a_single_station_run_is_scored_too():
    """Comparing one model against another should cost one sub-strand, not a
    pipeline run. The score was only computed on full-pipeline jobs, so the
    cheap experiment had no number to compare."""
    import inspect

    import app.routes.curriculum as routes

    for handler in (routes._run_queued, routes._run_queued_questions):
        source = inspect.getsource(handler)
        assert "quality_score.score" in source, handler.__name__
        assert 'out["quality"]' in source, handler.__name__


def test_the_console_shows_the_score_on_the_station():
    view = (FRONTEND / "src/views/ContentFactory.tsx").read_text()
    assert "function QualityScore" in view
    assert "Measured score" in view
    # And names the one variable the operator is meant to change.
    flat = " ".join(view.split())
    assert "Change one thing — the model on this station" in flat
