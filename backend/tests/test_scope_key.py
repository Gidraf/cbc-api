"""One way of naming a scope, on both sides of the coverage join.

Coverage joins what the curriculum REQUIRES to what has been GENERATED. The
requirement comes from the design tree, the generation from the artifacts
table, and the two keys were built by hand in four places — one stripping
whitespace, another not.

A key that does not match produces no error. It produces a sub-strand whose
every station has run and which reports 0%, beside a board that locks the next
stage because "none exist yet". Grade 9 read 0% with strands, sub-strands,
lesson plans, notes and diagrams all filed.
"""
from __future__ import annotations

import inspect

from app.services import scope_key


def test_the_same_name_typed_two_ways_is_one_scope() -> None:
    assert scope_key.key("Mathematics", "Whole Numbers") == \
           scope_key.key("mathematics ", " whole  numbers")


def test_curly_quotes_do_not_split_a_scope() -> None:
    """Names arrive from PDFs, which use ’ where an operator types '."""
    assert scope_key.key("Maths", "Number’s") == scope_key.key("maths", "number's")
    assert scope_key.norm("Number’s") == "numbers"


def test_a_non_breaking_space_is_still_a_space() -> None:
    """A design pasted out of a PDF carries them, and they are invisible."""
    assert scope_key.key("Maths", "Whole\u00a0Numbers") == \
           scope_key.key("Maths", "Whole Numbers")



def test_two_genuinely_different_substrands_stay_different() -> None:
    assert scope_key.key("Maths", "Integers") != scope_key.key("Maths", "Indices")
    assert scope_key.key("Maths", "Integers") != scope_key.key("Biology", "Integers")


def test_work_that_matched_nothing_is_said_out_loud() -> None:
    """The missing diagnosis. Work filed under a name the design does not use
    scores nothing, unlocks nothing, and nothing anywhere said so."""
    required = {scope_key.key("Mathematics", "Integers")}
    generated = {scope_key.key("Mathematics", "Integers"),
                 scope_key.key("Mathematics", "Indices")}

    said = " ".join(scope_key.report_misses(required, generated))

    assert "1 generated sub-strand(s) matched no sub-strand" in said
    assert "indices" in said
    assert "none of that work is counted anywhere" in said
    assert "imported under different names" in said, "and what to do about it"


def test_a_clean_join_says_nothing() -> None:
    scopes = {scope_key.key("Mathematics", "Integers")}
    assert scope_key.report_misses(scopes, scopes) == []


def test_a_long_list_of_orphans_is_summarised_not_dumped() -> None:
    generated = {scope_key.key("Maths", f"Sub {i}") for i in range(20)}
    said = scope_key.report_misses(set(), generated)

    assert len(said) <= 11
    assert any("and 12 more" in line for line in said)


# ── both sides of every join use it ─────────────────────────────────────────


def test_every_coverage_index_is_keyed_by_the_same_function() -> None:
    from app.routes import admin_langfuse
    from app.services import substrand_bundle

    route = inspect.getsource(admin_langfuse)
    assert route.count("scope_key.key(") >= 4, \
        "requirements, artifacts, media and approvals"
    assert 'str(row.get("sub_strand_name") or "").strip().lower()' not in route, \
        "no hand-built key survives"

    assert "scope_key.key(" in inspect.getsource(substrand_bundle.index_for_grade)


def test_the_coverage_report_carries_what_it_could_not_match() -> None:
    from app.routes import admin_langfuse

    route = inspect.getsource(admin_langfuse)
    assert '"unmatched_generations": scope_key.report_misses(' in route


# ── the console ─────────────────────────────────────────────────────────────

from pathlib import Path  # noqa: E402

FRONTEND = Path(__file__).resolve().parents[2] / "frontend-web"


def test_the_coverage_screen_says_when_work_is_not_being_counted() -> None:
    """A grade reading 0% with every station run was indistinguishable from a
    grade nobody had touched."""
    screen = " ".join((FRONTEND / "src/views/Coverage.tsx").read_text().split())

    assert "unmatched_generations" in screen
    assert "Some generated work is not being counted" in screen
