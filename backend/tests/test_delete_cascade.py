"""Removing a strand has to remove what was generated from it.

Reported from the factory: deleting a strand left its notes, its reviews and
everything else in the database. The newer console deletes through
`scoped_delete`, which covers ten tables. The older endpoints ran three DELETEs
of their own and were wrong in three separate ways.
"""
from __future__ import annotations

import inspect
import pathlib

from app.routes import curriculum
from app.services import scoped_delete

BACKEND = pathlib.Path(__file__).resolve().parents[1]


def _source(fn) -> str:
    return inspect.getsource(fn)


# ── one implementation, not two ─────────────────────────────────────────────


def test_the_strand_endpoint_deletes_through_the_same_path_as_the_console():
    source = _source(curriculum.delete_curriculum_strand)

    assert "scoped_delete.delete(" in source
    assert "DELETE FROM" not in source, "it still runs DELETEs of its own"


def test_the_substrand_endpoint_deletes_through_the_same_path_too():
    source = _source(curriculum.delete_curriculum_substrand)

    assert "scoped_delete.delete(" in source
    assert "DELETE FROM" not in source


def test_neither_endpoint_matches_a_name_by_substring():
    """`LIKE '%god%'` deleted "Our God" and "God's Love" when asked for "God"."""
    for fn in (curriculum.delete_curriculum_strand,
               curriculum.delete_curriculum_substrand):
        # The docstring names the technique; the point is that nothing runs it.
        code = "\n".join(l for l in _source(fn).splitlines()
                         if "LIKE" not in l or "%name%" not in l)
        assert "LIKE :" not in code, fn.__name__
        assert "f\"%{" not in code, fn.__name__


def test_the_grade_is_actually_used():
    """Both endpoints took a grade and never put it in a WHERE clause, so
    removing a strand from one grade removed it from every grade with a strand
    by that name — and "Creation" is in several."""
    for fn in (curriculum.delete_curriculum_strand,
               curriculum.delete_curriculum_substrand):
        source = _source(fn)
        assert "grade=grade" in source, fn.__name__


def test_a_delete_through_the_old_endpoint_is_not_a_dry_run():
    """`scoped_delete` defaults to a dry run. Delegating without confirming
    would have turned a working delete into one that reports and does
    nothing — a quieter version of the same bug."""
    for fn in (curriculum.delete_curriculum_strand,
               curriculum.delete_curriculum_substrand):
        assert "confirm=scoped_delete.CONFIRMATION" in _source(fn), fn.__name__


# ── what has to go with it ──────────────────────────────────────────────────


def test_generated_versions_and_their_reviews_are_covered():
    """The three tables the old endpoints cleared, and the seven they did not."""
    tables = {t.table for t in scoped_delete.DERIVED}

    assert {"substrand_resources", "curriculum_substrands", "question_dna"} <= tables
    assert {"artifacts", "artifact_reviews", "artifact_labels",
            "artifact_comments", "artifact_dna", "substrand_media"} <= tables


def test_queued_work_for_a_deleted_scope_goes_too():
    """A job left behind is worse than an orphaned row: it still runs, and
    regenerates content for a sub-strand nobody can see — which reappears in
    the console as if the delete had undone itself."""
    jobs = next((t for t in scoped_delete.DERIVED if t.table == "jobs"), None)

    assert jobs is not None, "queued jobs survive a delete"
    assert jobs.grade and jobs.subject and jobs.strand and jobs.sub_strand


def test_the_sub_strand_row_still_goes_last():
    order = [t.table for t in scoped_delete.DERIVED]

    assert order[-1] == "curriculum_substrands"
    assert order.index("jobs") < order.index("curriculum_substrands")


# ── what the old endpoints already left behind ──────────────────────────────


def test_there_is_a_sweep_for_content_already_orphaned():
    """Fixing the endpoints does nothing for what they already left."""
    assert hasattr(scoped_delete, "find_orphans")
    assert hasattr(scoped_delete, "sweep_orphans")
    assert hasattr(curriculum, "factory_sweep_orphans")


def test_the_orphan_query_ignores_the_grade_prefix():
    """Artifacts store "grade-pp1"; the curriculum tables have carried both
    that and "pp1". Matching them raw would report every artifact as an
    orphan and offer to delete the whole corpus."""
    query = scoped_delete._ORPHAN_ARTIFACTS

    assert "REPLACE(LOWER(c.grade), 'grade-', '')" in query
    assert "REPLACE(LOWER(a.grade), 'grade-', '')" in query


def test_the_orphan_query_skips_artifacts_that_have_no_sub_strand():
    """A strand-level artifact has no sub_strand_name and is not an orphan for
    lacking one."""
    assert "a.sub_strand_name <> ''" in scoped_delete._ORPHAN_ARTIFACTS


def test_the_sweep_is_a_dry_run_until_confirmed():
    source = _source(scoped_delete.sweep_orphans)

    assert "confirm.strip().upper() != CONFIRMATION" in source
    assert '"dry_run": True' in source


def test_the_sweep_removes_reviews_before_the_versions_they_hang_off():
    source = _source(scoped_delete.sweep_orphans)
    reviews = source.index("artifact_reviews")
    versions = source.index("DELETE FROM artifacts WHERE")

    assert reviews < versions
