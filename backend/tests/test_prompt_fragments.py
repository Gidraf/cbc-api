"""Small pieces of prompt, chosen by context, instead of one large one.

Education is wide. Geography needs maps and the solar system; Chemistry needs
equations that balance; Music needs sol-fa; Home Science needs quantities and a
hygiene rule; Carpentry needs a cutting list. None of that belongs in a
Christian Religious Education prompt, and all of it belongs somewhere.

One prompt per station does not work, and not because of length. A prompt that
must serve every subject is a prompt nobody can improve: change the paragraph
about balancing equations and you have edited the prompt that writes a PP1
singing lesson. So the person who knows chemistry will not touch it, and it
stays wrong.
"""
from __future__ import annotations

import pathlib

from app.services import prompt_fragments as pf


# ── which fragment applies where ────────────────────────────────────────────


def test_a_subject_gets_only_what_it_needs():
    assert [f.name for f in pf.for_context("Chemistry", "questions", "grade-10")] \
        == ["chemistry-equations"]
    assert [f.name for f in pf.for_context("Music", "notes", "grade-4")] \
        == ["music-notation"]


def test_a_subject_with_no_domain_of_its_own_gets_nothing():
    """A CRE lesson plan receives no paragraph about mortise and tenon joints,
    and the instructions it does receive are easier to find for it."""
    assert pf.compose("Christian Religious Education", "notes", "grade-pp1") == ""


def test_home_science_is_cookery_not_astronomy():
    """"science" as a bare stem swept it into the solar system."""
    got = [f.name for f in pf.for_context("Home Science", "activity", "grade-8")]

    assert got == ["home-science-practical"]


def test_a_grade_range_is_named_by_grade_not_by_ordinal():
    """Ordinals are 1-based over the whole sequence — grade-pp1 is 1, so Grade
    4 is 6 — and `from_ordinal=4` meaning Grade 4 silently gave every map
    fragment to Grade 2."""
    maps = next(f for f in pf.FRAGMENTS if f.name == "geography-maps")

    assert maps.from_grade == "grade-4"
    assert maps.to_dict()["grades"][0] == "grade-4"


def test_a_cutting_list_is_not_for_a_four_year_old():
    assert not pf.for_context("Carpentry and Joinery", "diagram", "grade-pp1")
    assert pf.for_context("Carpentry and Joinery", "diagram", "grade-10")


def test_a_fragment_reaches_only_the_stations_it_names():
    """A cutting list has no business in a question paper."""
    cooking = next(f for f in pf.FRAGMENTS if f.name == "home-science-practical")

    assert "questions" not in cooking.stations
    assert not any(f.name == "home-science-practical"
                   for f in pf.for_context("Home Science", "questions", "grade-8"))


def test_reading_a_strand_list_out_of_a_table_gets_no_domain_prompt():
    """A fragment with no explicit station list would otherwise reach every
    caller including that one."""
    assert pf.compose("Geography", "structure", "grade-7") == ""


# ── each fragment has to earn its place ─────────────────────────────────────


def test_every_fragment_says_why_it_exists():
    for fragment in pf.FRAGMENTS:
        assert len(fragment.why) > 60, fragment.name


def test_every_fragment_names_what_in_the_kicd_design_it_serves():
    """Domain knowledge is exactly where a prompt drifts away from the
    curriculum and towards what the author happens to know about the subject.
    Naming the design's own hook is what keeps a chemistry fragment about KICD
    chemistry rather than about chemistry."""
    for fragment in pf.FRAGMENTS:
        assert len(fragment.kicd) > 80, fragment.name
        assert "design" in fragment.kicd.lower() or "rubric" in fragment.kicd.lower(), \
            fragment.name


def test_a_fragment_asks_for_data_rather_than_prose():
    """A map described in words cannot be measured; a map given as a scale, a
    key and a feature list can."""
    for name in ("geography-maps", "chemistry-equations", "music-notation",
                 "home-science-practical", "technical-drawing"):
        fragment = next(f for f in pf.FRAGMENTS if f.name == name)
        assert '":' in fragment.body, f"{name} gives no structure to fill"


def test_the_domains_named_are_all_covered():
    names = {f.name for f in pf.FRAGMENTS}

    assert {"geography-maps", "astronomy-solar-system", "chemistry-equations",
            "music-notation", "home-science-practical", "technical-drawing"} <= names


# ── what each one actually insists on ───────────────────────────────────────


def test_a_map_carries_a_scale_a_north_arrow_and_a_key():
    body = next(f for f in pf.FRAGMENTS if f.name == "geography-maps").body

    assert "SCALE" in body and "NORTH" in body and "KEY" in body
    assert "cannot be asked a" in body, "it should say what a map without them costs"


def test_a_sky_diagram_says_whether_it_is_to_scale():
    """A figure drawn to fill the page and unlabelled teaches that Neptune is a
    short way past Saturn."""
    body = next(f for f in pf.FRAGMENTS if f.name == "astronomy-solar-system").body

    assert "not to scale" in body
    assert "Neptune" in body


def test_an_equation_must_be_checked_before_it_is_written():
    body = next(f for f in pf.FRAGMENTS if f.name == "chemistry-equations").body

    assert "count the atoms" in body.lower()
    assert "atom_count" in body


def test_a_song_is_written_out_in_the_notation_kenyan_classrooms_read():
    """A song named and not written down is a song the teacher must already
    know. Most cannot read staff notation; almost all can read sol-fa."""
    body = next(f for f in pf.FRAGMENTS if f.name == "music-notation").body

    assert "SOL-FA" in body
    assert "never substituted" in body


def test_a_recipe_says_how_you_know_each_step_is_done():
    """"Cook for five minutes" and "cook until it pulls away from the sides"
    are different instructions, and only the second works on a jiko whose heat
    nobody measured."""
    body = next(f for f in pf.FRAGMENTS if f.name == "home-science-practical").body

    assert "how_you_know" in body
    assert "HEAT AND BLADES ARE THE TEACHER'S" in body


def test_a_drawing_dimensions_every_part_once():
    body = next(f for f in pf.FRAGMENTS if f.name == "technical-drawing").body

    assert "DIMENSION EVERY PART ONCE" in body
    assert "cutting_list" in body


# ── each is its own prompt, improvable on its own ───────────────────────────


def test_each_fragment_is_its_own_langfuse_prompt():
    for fragment in pf.FRAGMENTS:
        assert fragment.langfuse_name == f"fragment/{fragment.name}"


def test_the_sync_writes_every_fragment_separately():
    from app.services.prompt_sync import _all_prompts

    names = set(_all_prompts())
    for fragment in pf.FRAGMENTS:
        assert fragment.langfuse_name in names, fragment.name


def test_an_edited_fragment_is_preferred_over_the_built_in():
    """The code holds the default so a fresh deployment works with no prompt
    store at all; Langfuse holds the improvements."""
    import inspect

    source = inspect.getsource(pf._body)
    assert "langfuse_context_service.get_prompt" in source
    assert "return fragment.body" in source


def test_an_empty_edit_is_refused_rather_than_silently_removing_the_rules():
    import inspect

    from app.routes import pipelines

    source = inspect.getsource(pipelines.edit_fragment)
    assert "silently remove this subject's domain" in source


def test_saving_one_fragment_does_not_rewrite_the_others():
    """A person has rewritten one domain fragment and expects that one to
    change, and nothing else."""
    import inspect

    from app.services import prompt_sync

    source = inspect.getsource(prompt_sync.push_one)
    assert "name=name, prompt=text" in source


# ── seen and edited from the console ────────────────────────────────────────


def _view() -> str:
    return (pathlib.Path(__file__).resolve().parents[2]
            / "frontend-web/src/views/PromptFragments.tsx").read_text()


def test_the_console_shows_what_the_kicd_design_asks_for_beside_each():
    assert "What the KICD design asks for" in _view()


def test_the_console_says_where_each_one_applies():
    view = _view()

    assert "applies here" in view
    assert "fragment.grades[0]" in view


def test_a_fragment_can_be_edited_and_reverted():
    view = _view()

    assert "Save to Langfuse" in view
    assert "Back to the built-in" in view


def test_the_board_shows_only_what_applies_to_the_stage_being_looked_at():
    board = (pathlib.Path(__file__).resolve().parents[2]
             / "frontend-web/src/views/Pipelines.tsx").read_text()

    assert "Domain prompts" in board
    assert "compact" in board


def test_no_domain_prompt_applying_is_explained_rather_than_left_blank():
    assert "which is usually right" in _view()


def test_every_station_that_states_the_notation_also_states_the_domain():
    source = (pathlib.Path(__file__).resolve().parents[1]
              / "app/routes/curriculum.py").read_text()

    assert source.count('"notation": notation.block_for(') == \
        source.count('"domain_directives": prompt_fragments.compose(')


def test_the_reviewers_hold_the_same_domain_rules_the_generator_was_given():
    """Or they are judging against their own recollection of what a map needs."""
    source = (pathlib.Path(__file__).resolve().parents[1]
              / "app/services/pipeline.py").read_text()

    assert '"domain_directives": prompt_fragments.compose(' in source
