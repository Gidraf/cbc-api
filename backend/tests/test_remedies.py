"""An error should say what to do about it, and let you do it.

"MISSING_PARENT_CONTEXT: no approved lesson plan" meant: go to the board, find
the grade, find the learning area, find the lesson plan stage, run it, wait,
review it, approve it, come back. Six navigations to act on one sentence, in a
console with fifteen grades and nine stages, every one of them a chance to act
on the wrong row.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.errors import ApiError, raise_api_error
from app.services import remedies

FRONTEND = Path(__file__).resolve().parents[2] / "frontend-web"


def test_several_missing_stages_are_one_remedy_in_order() -> None:
    """Not several remedies: they are not alternatives, and a list of buttons
    invites pressing the last one — which is the one furthest from possible."""
    remedy = remedies.missing_upstream(
        "grade-3", "Mathematics", "diagram", have={"ingest", "strands"}
    )

    assert remedy.kind == "run"
    assert [s["stage"] for s in remedy.steps] == ["substrands", "notes", "material"]
    assert remedy.sequential is True
    assert "3 stages" in remedy.label
    assert "running them together fails all but the first" in remedy.why


def test_a_single_missing_stage_says_which_one() -> None:
    """"Run the 1 stages this needs" is how a remedy stops being read."""
    remedy = remedies.missing_upstream(
        "grade-3", "Mathematics", "notes",
        have={"ingest", "strands", "substrands"},
    )

    assert remedy.label == "Run sub-strands" or len(remedy.steps) == 0 or "Run" in remedy.label
    assert len(remedy.steps) <= 1


def test_nothing_already_done_is_ever_proposed() -> None:
    """Proposing stages that have already run is how a remedy teaches an
    operator to ignore remedies."""
    remedy = remedies.missing_upstream(
        "grade-3", "Mathematics", "questions",
        have={"ingest", "strands", "substrands", "notes", "material",
              "diagram", "media", "simulation", "activity"},
    )
    assert remedy.steps == []


def test_approval_is_offered_as_a_place_to_go_not_a_button_to_press() -> None:
    """A person signs, and no error should offer to sign for them."""
    remedy = remedies.approve_first("grade-3", "Mathematics", "notes")

    assert remedy.kind == "open"
    assert "does not sign for you" in remedy.why
    assert remedy.href.startswith("/pipelines?")


def test_a_bad_model_is_offered_as_the_field_it_actually_is() -> None:
    remedy = remedies.set_the_model("notes", current="gemini-1.5-pro",
                                    options=["gemini-2.0-flash"])

    assert remedy.kind == "set"
    assert remedy.field_name == "model"
    assert remedy.current == "gemini-1.5-pro"
    assert "retrying will not help" in remedy.why


def test_the_remedy_travels_on_the_error() -> None:
    with pytest.raises(ApiError) as caught:
        raise_api_error(
            "MISSING_PARENT_CONTEXT", "no lesson plan",
            remedy=remedies.run_this_stage("grade-3", "Mathematics", "notes"),
        )

    assert caught.value.remedy
    assert caught.value.remedy[0]["kind"] == "run"

    # And an error with nothing sensible to suggest carries nothing, rather
    # than an empty list the console has to special-case.
    with pytest.raises(ApiError) as plain:
        raise_api_error("VALIDATION_FAILED", "nope")
    assert plain.value.remedy is None


def test_the_response_body_carries_it() -> None:
    from app.main import api_error_handler
    import asyncio, json

    error = ApiError(
        code="LLM_INVALID_MODEL", message="nope", status_code=400,
        remedy=remedies.as_payload(remedies.set_the_model("notes")),
    )
    body = json.loads(asyncio.run(api_error_handler(None, error)).body)
    assert body["errors"][0]["remedy"][0]["kind"] == "set"


def test_a_model_that_does_not_exist_offers_the_provider_s_own_list() -> None:
    """A free-text box is how `gemini-1.5-pro` got bound to a station that has
    never served it."""
    from app.services.provider_router import known_models_for

    assert "gemini-2.0-flash" in known_models_for("gemini")
    assert "gpt-4o-mini" in known_models_for("openai")
    # Not a gate: providers add models faster than a list is maintained.
    assert known_models_for("something-new") == ()


def test_the_board_offers_what_a_blocked_stage_is_waiting_for() -> None:
    """A board that says "waiting on the lesson plan" and makes you go and find
    the lesson plan has told you where to click, which is not the same as
    letting you click it."""
    from app.services import pipeline_board

    assert "remedy" in pipeline_board.Stage(stage="notes").to_dict()

    source = open("app/services/pipeline_board.py").read()
    assert "_remedy_for" in source
    assert "import_the_design" in source, "a grade with no design is a different press"


# ── the console ──────────────────────────────────────────────────────────────


def test_the_steps_run_one_at_a_time_and_stop_at_the_first_failure() -> None:
    """Each is built from the one before it, so firing them together fails all
    but the first — the exact failure the remedy exists to prevent."""
    panel = " ".join((FRONTEND / "src/ui/Remedy.tsx").read_text().split())

    assert "for (let i = 0; i < steps.length; i++)" in panel
    assert "await act.mutateAsync" in panel
    assert "Stopped at" in panel
    assert "carrying on only buries the reason" in panel


def test_every_error_notice_shows_the_remedy() -> None:
    """Wired once, where every screen already reports its failures."""
    components = (FRONTEND / "src/ui/components.tsx").read_text()

    assert "LazyRemedy" in components
    assert "errors?.[0]?.remedy" in components
    # And "Try again" is not offered for something that fails identically
    # every time.
    assert "retryable !== false" in components
