"""Remove ONE strand or sub-strand, not the whole learning area.

The only tool was the factory reset. That is right for "the pipeline changed,
start again" and wrong for "this sub-strand came out badly" — and with only the
second, an operator either keeps a bad sub-strand or throws away eleven good
ones with it.
"""
from __future__ import annotations

import pathlib

import pytest

from app.services import scoped_delete

BACKEND = pathlib.Path(__file__).resolve().parents[1]
FRONTEND = BACKEND.parent / "frontend-web"


def _clause(target: scoped_delete.Scoped, **kw):
    return target.clause(
        kw.get("grade", ""), kw.get("subject", ""),
        kw.get("strand", ""), kw.get("sub_strand", ""),
    )


def _by_table(name: str) -> scoped_delete.Scoped:
    return next(t for t in scoped_delete.DERIVED if t.table == name)


def test_children_are_deleted_before_their_parent():
    """Deleting the sub-strand first leaves its notes, questions and review
    verdicts pointing at a row that is gone."""
    order = [t.table for t in scoped_delete.DERIVED]

    assert order.index("artifact_reviews") < order.index("artifacts")
    assert order.index("artifact_comments") < order.index("artifacts")
    assert order.index("artifact_labels") < order.index("artifacts")
    assert order[-1] == "curriculum_substrands", "the sub-strand itself goes last"


def test_everything_derived_from_a_sub_strand_is_covered():
    """An orphan still counts toward coverage and still appears in the question
    bank, describing a sub-strand that no longer exists."""
    tables = {t.table for t in scoped_delete.DERIVED}

    assert {
        "artifacts", "artifact_reviews", "artifact_labels", "artifact_comments",
        "artifact_dna", "substrand_media", "substrand_resources", "question_dna",
        "curriculum_substrands",
    } <= tables


def test_a_sub_strand_delete_narrows_to_that_sub_strand():
    clause, params = _clause(
        _by_table("curriculum_substrands"),
        grade="grade-pp1", subject="CRE", strand="Creation", sub_strand="Our God",
    )
    assert "sub_strand_name" in clause
    assert params["sub_strand"] == "Our God"
    assert params["strand"] == "Creation"


def test_a_table_that_cannot_be_narrowed_is_skipped_not_emptied():
    """Deleting it anyway would take rows belonging to sub-strands nobody
    named."""
    unnarrowable = scoped_delete.Scoped("some_table", "things")
    clause, params = _clause(unnarrowable, grade="grade-pp1", subject="CRE")

    assert clause == ""
    assert params == {}


def test_rows_reachable_only_through_artifacts_are_found_by_join():
    """Reviews and labels carry an artifact_id and no curriculum scope of their
    own."""
    clause, params = _clause(
        _by_table("artifact_reviews"),
        grade="grade-pp1", subject="CRE", sub_strand="Our God",
    )
    assert "SELECT a.artifact_id FROM artifacts a" in clause
    assert "LOWER(a.sub_strand_name) = LOWER(:sub_strand)" in clause


def test_json_scoped_tables_are_narrowed_through_their_json():
    clause, _ = _clause(
        _by_table("question_dna"),
        grade="grade-pp1", subject="CRE", sub_strand="Our God",
    )
    assert "curriculum_link->>'sub_strand'" in clause


def test_it_refuses_to_run_without_a_strand_or_sub_strand():
    """Clearing a whole learning area is what the reset is for, and it asks for
    a longer confirmation because it takes more."""
    from app.errors import ApiError

    with pytest.raises(ApiError):
        scoped_delete.delete("grade-pp1", "CRE")


def test_it_is_a_dry_run_unless_confirmed():
    report = scoped_delete.DeleteReport(
        scope={"sub_strand": "Our God"}, dry_run=True,
        tables=[{"table": "artifacts", "what": "versions", "rows": 4}],
    )
    body = report.to_dict()

    assert body["dry_run"] is True
    assert body["total_rows"] == 4
    assert "Nothing has been deleted" in body["message"]
    assert body["confirmation_required"] == "DELETE"


def test_regeneration_keeps_the_strand_it_regenerates_against():
    source = (BACKEND / "app/routes/curriculum.py").read_text()
    route = source[source.index("def factory_regenerate_scope"):]
    route = route[: route.index("\n@router.post")]

    assert "keep_strand=True" in route
    # And it removes before it generates: writing over the old rows leaves the
    # previous sub-strands stored under names this run did not produce.
    assert route.index("scoped_delete.delete") < route.index("job_queue.enqueue")


def test_regeneration_previews_before_it_destroys():
    source = (BACKEND / "app/routes/curriculum.py").read_text()
    route = source[source.index("def factory_regenerate_scope"):]
    route = route[: route.index("\n@router.post")]

    assert 'payload.confirm.strip().upper() != scoped_delete.CONFIRMATION' in route
    assert '"queued": 0' in route


def test_a_strand_is_removed_from_the_designs_metadata():
    """Strands are a JSONB list on curriculum_designs, not rows, so removing
    one is a rewrite of that list rather than a DELETE."""
    source = (BACKEND / "app/services/scoped_delete.py").read_text()
    fn = source[source.index("def _remove_strand_from_design"):]
    fn = fn[: fn.index("\ndef delete(")]

    assert "UPDATE curriculum_designs SET metadata" in fn
    assert "strands" in fn


def test_strands_are_read_from_the_design_not_a_table_that_never_existed():
    """Two queries were written against `curriculum_strands`. No such table is
    created anywhere, so a pipeline reaching its second step would have raised
    UndefinedTable."""
    db = (BACKEND / "app/infra/db.py").read_text()
    assert "CREATE TABLE IF NOT EXISTS curriculum_strands" not in db

    routes = (BACKEND / "app/routes/curriculum.py").read_text()
    code = "\n".join(
        line for line in routes.splitlines() if not line.lstrip().startswith("#")
    )
    assert "FROM curriculum_strands" not in code


def test_the_console_offers_removal_per_strand_and_per_sub_strand():
    view = (FRONTEND / "src/views/CurriculumStructure.tsx").read_text()

    assert "previewRemoval(name, \"\", false)" in view, "remove a whole strand"
    assert "previewRemoval(name, subName(sub), false)" in view, "remove one sub-strand"
    assert "previewRemoval(name, \"\", true)" in view, "redo a strand"
    # And it shows what would go before it is irreversible.
    assert "pendingDelete" in view
    assert 'confirm: "DELETE"' in view


# ── the console must not go blank when it has data ──────────────────────────


def test_the_builder_renders_before_a_subject_is_chosen():
    """Gating it on `subject` meant that with "All subjects" selected the whole
    card vanished — no picker, no builder, no way forward — on a grade with
    seven ingested designs."""
    view = " ".join((FRONTEND / "src/views/ContentFactory.tsx").read_text().split())
    assert "{!substrand && !saved.isLoading && ( <details" in view
    assert "{!substrand && subject && !saved.isLoading &&" not in view


def test_the_empty_state_does_not_diagnose_by_guessing():
    """It said "Ingest a curriculum design for this grade" whatever the reason
    was — sending the operator to re-ingest seven designs that were already
    there."""
    view = (FRONTEND / "src/views/ContentFactory.tsx").read_text()

    assert "designsForGrade > 0" in view
    assert "there is nothing to re-ingest" in view
    assert "Choose a subject" in view


def test_grade_matching_is_case_insensitive():
    """Rows are written "grade-pp1". A caller sending "PP1" derives
    "grade-PP1", which Postgres does not consider equal — and the console then
    reports a fully ingested grade as empty."""
    source = (BACKEND / "app/routes/curriculum.py").read_text()
    listing = source[source.index('@router.get("/substrands")'):]
    listing = listing[: listing.index("    query = f")]

    assert "LOWER(grade) = LOWER(:grade)" in listing
    assert "LOWER(grade) = LOWER(:alt_grade)" in listing


def test_stored_structure_says_when_it_was_written():
    """Four rounds of "how accurate is this" were spent on output that looked
    freshly generated and was several pipeline changes old, because nothing in
    it said when it was made."""
    routes = (BACKEND / "app/routes/curriculum.py").read_text()
    block = routes[routes.index('strands[key]["sub_strands"].append('):]
    block = block[: block.index("ordered = sorted")]
    assert '"updated_at"' in block

    serialize = (FRONTEND / "src/lib/serialize.ts").read_text()
    assert "Stored: ${String(s.updated_at)}" in serialize
    assert "not yet saved (this is a draft)" in serialize
