"""Where the notes prompt spends its budget, and how deep a module must be.

One run put 20,606 characters into the blueprint — about 18,000 of them
describing the eleven sub-strands the guide was NOT writing, each field
duplicated inside its own `prompt_package` — and gave the design itself a
4,000-character excerpt, cut mid-table at "The learner is guided to:". The
quality gate then scored source grounding against all 31,689 characters and
returned 0.20, which was the correct score for what the model had been shown.

And the depth floor contradicted itself: the prompt asked for 800 characters a
module, the validator failed below 400, and a guide averaging 662 passed the
validator, failed the instruction, and reported "complete, 100%".
"""
from __future__ import annotations

from app.routes.curriculum import MAX_DESIGN_CHARS
from app.services.langfuse_context import focus_sub_strand_context
from app.services.notes_coverage import MIN_BODY_CHARS, check
from app.services.time_allocation import parse


def _blueprint() -> dict:
    def sub(name: str) -> dict:
        body = {
            "name": name, "hours": "7 lessons",
            "slos": ["identify three qualities of God"],
            "link_to_other_learning_areas": "x" * 200,
        }
        # The stored shape duplicates every field inside itself.
        return {**body, "prompt_package": dict(body)}

    return {
        "subject": "Christian Religious Education",
        "strands": [
            {"name": "Creation", "sub_strands": [
                sub("Our God"), sub("God our Creator"), sub("God our Loving Father"),
            ]},
            {"name": "The Church", "sub_strands": [sub("A House of God")]},
        ],
    }


# ── The budget ──────────────────────────────────────────────────────────────

def test_only_the_sub_strand_being_written_is_given_in_full() -> None:
    focused = focus_sub_strand_context(_blueprint(), "Creation", "Our God")

    subs = focused["strands"][0]["sub_strands"]
    assert [s["name"] for s in subs] == ["Our God"]
    assert subs[0]["slos"], "the one being written must keep its detail"


def test_the_duplicated_package_inside_each_sub_strand_is_dropped() -> None:
    """One copy is a blueprint; two is padding."""
    focused = focus_sub_strand_context(_blueprint(), "Creation", "Our God")

    assert "prompt_package" not in focused["strands"][0]["sub_strands"][0]


def test_the_siblings_are_kept_by_name_so_the_guide_knows_its_neighbours() -> None:
    """"Do not pre-empt 1.2" needs 1.2 to have a name — and nothing else."""
    focused = focus_sub_strand_context(_blueprint(), "Creation", "Our God")

    assert focused["other_sub_strands_in_this_strand"] == [
        "God our Creator", "God our Loving Father",
    ]
    assert "do not teach their content here" in focused["note"]


def test_narrowing_actually_cuts_the_bulk() -> None:
    import json

    full = len(json.dumps(_blueprint()))
    focused = len(json.dumps(focus_sub_strand_context(_blueprint(), "Creation", "Our God")))

    assert focused < full / 2, f"{focused} of {full} — barely narrowed"


def test_the_notes_route_narrows_to_the_sub_strand() -> None:
    route = open("app/routes/curriculum.py").read()
    notes = route[route.index("def factory_generate_notes"):]
    notes = notes[: notes.index("\n@router.")]

    assert "focus_sub_strand=payload.sub_strand" in notes


def test_the_whole_design_now_reaches_the_prompt() -> None:
    """It was cut to 4,000 characters — a twentieth of the source it was then
    scored against."""
    route = open("app/routes/curriculum.py").read()

    assert "source_text[:4000]" not in route
    assert "source_text[:MAX_DESIGN_CHARS]" in route
    assert MAX_DESIGN_CHARS >= 32_000, "a design runs to about 32,000 characters"


def test_a_whole_design_still_fits_the_window() -> None:
    """At four characters per token a 32,000-character design is 8,000 tokens
    against a 128,000-token window."""
    assert MAX_DESIGN_CHARS / 4 < 100_000


# ── The floor ───────────────────────────────────────────────────────────────

def test_the_floor_is_half_a_printed_page_a_lesson() -> None:
    assert MIN_BODY_CHARS == 1_500
    seven_lessons = 7 * MIN_BODY_CHARS
    assert 3.0 <= seven_lessons / 3_000 <= 4.0, "a 7-lesson sub-strand near 3 pages"


def test_the_prompt_and_the_validator_state_the_same_number() -> None:
    """The prompt asked for 800 and the validator failed below 400, so a guide
    averaging 662 passed one and failed the other."""
    route = open("app/routes/curriculum.py").read()

    assert "MIN_BODY_CHARS * 2" not in route
    assert "{notes_coverage.MIN_BODY_CHARS:,}" in route


def test_the_prompt_no_longer_contradicts_its_own_floor() -> None:
    """Rule 4 said depth is "not a fixed word count" eleven lines above a fixed
    floor. Two opposite instructions means one gets followed."""
    route = open("app/routes/curriculum.py").read()

    assert "not a fixed \" \n" not in route
    assert "Depth follows the learner described in WHO THIS IS FOR, not a fixed" not in route
    assert "the floor below is a floor" in route


def test_a_guide_at_the_old_average_now_fails() -> None:
    """662 characters a module reported "complete, 100%"."""
    notes = {"modules": [
        {"module_number": i, "title": f"Lesson {i}", "duration_minutes": 30,
         "teacher_exposition": "x" * 662}
        for i in range(1, 8)
    ]}

    coverage = check(notes, parse("7 lessons", "grade-pp1"))

    assert not coverage.complete
    assert len(coverage.thin_modules) == 7


def test_a_guide_at_the_new_floor_passes() -> None:
    notes = {"modules": [
        {"module_number": i, "title": f"Lesson {i}", "duration_minutes": 30,
         "teacher_exposition": "x" * MIN_BODY_CHARS}
        for i in range(1, 8)
    ]}

    coverage = check(notes, parse("7 lessons", "grade-pp1"))

    assert coverage.complete
    assert coverage.to_dict()["estimated_printed_pages"] >= 3.0


# ── The two content failures the last run showed ────────────────────────────

def test_the_prompt_demands_the_designs_own_words_be_used() -> None:
    """The design handed the guide an actual Swahili sentence to say aloud —
    the most concrete thing in the specification — and the guide skipped it."""
    from app.services.langfuse_seed import SEED_AGENT_PROMPTS

    flat = SEED_AGENT_PROMPTS["note-generator"].replace("\n", " ")

    assert "USE WHAT THE DESIGN GIVES YOU" in flat
    assert "that phrase goes in the guide verbatim" in flat
    assert "Every suggested learning experience must appear in at least one module" in flat


def test_the_prompt_forbids_drifting_into_the_next_sub_strand() -> None:
    """Module 7 of a guide for 1.1 Our God taught God's creation — which is
    1.2's content, taught twice and scheduled once."""
    from app.services.langfuse_seed import SEED_AGENT_PROMPTS

    flat = SEED_AGENT_PROMPTS["note-generator"].replace("\n", " ")

    assert "STAY INSIDE THIS SUB-STRAND" in flat
    assert "never sideways into the next sub-strand" in flat


def test_an_empty_gaps_list_is_called_out_as_suspicious() -> None:
    """"Gaps: None identified" and "Uncited Content: None identified" were both
    false — the guide's "loving, powerful, wise" triad is not the design's."""
    from app.services.langfuse_seed import SEED_AGENT_PROMPTS

    flat = SEED_AGENT_PROMPTS["note-generator"].replace("\n", " ")

    assert "not that you did not look" in flat
    assert "an empty list is nearly always a failure to look" in flat
