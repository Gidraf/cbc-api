"""Queued sub-strand generation, and drafts that survive a save of another strand.

Generate all five strands' sub-strands, save one, and the other four
disappeared. They were held in the console's own state, at a position in the
React tree that the first save moved — so React unmounted the component and
took the drafts with it. Nothing errored and nothing recorded that they had
existed.

Drafts now live in the jobs table. The console reads them; saving one strand
marks only that strand's draft consumed.
"""
from __future__ import annotations

import pathlib
import re

BACKEND = pathlib.Path(__file__).resolve().parents[1]
FRONTEND = BACKEND.parent / "frontend-web"


def _read(path: str) -> str:
    return (BACKEND / path).read_text()


def _front(path: str) -> str:
    return (FRONTEND / path).read_text()


# ── the queue kind ──────────────────────────────────────────────────────────


def test_substrand_generation_is_a_queueable_kind():
    from app.routes import curriculum  # noqa: F401  (registers handlers)
    from app.services import job_queue

    assert "substrands" in job_queue.known_kinds()


def test_the_substrand_handler_keeps_the_generated_sub_strands():
    """Every other queued kind writes as it goes; this one produces a draft, so
    losing the result would lose the work."""
    source = _read("app/routes/curriculum.py")
    handler = source[source.index("def _run_queued_substrands"):]
    handler = handler[: handler.index("\ndef _register_queue_handlers")]

    assert '"sub_strands": result.get("sub_strands")' in handler
    assert '"refused": result.get("refused")' in handler
    # And it must not quietly file an artifact — accepting is the operator's.
    assert "_record_artifact" not in handler


def test_a_queued_strand_carries_its_own_strand_id():
    """Sub-strand ids hang off it; defaulting every strand to 1.0 renumbers the
    curriculum."""
    source = _read("app/routes/curriculum.py")
    handler = source[source.index("def _run_queued_substrands"):]
    assert 'strand_id=str(payload.get("strand_id")' in handler[:2000]


# ── drafts are held server-side ─────────────────────────────────────────────


def test_the_drafts_query_returns_only_unaccepted_finished_work():
    source = _read("app/services/job_queue.py")
    drafts = source[source.index("def drafts("):]
    drafts = drafts[: drafts.index("\ndef cancel")]

    assert "status = 'done'" in drafts
    assert "consumed_at IS NULL" in drafts
    # The result IS the draft; status() omits results because across a grade
    # they are megabytes, so this query has to ask for them explicitly.
    assert "result" in drafts


def test_consuming_one_strand_cannot_touch_another():
    source = _read("app/services/job_queue.py")
    consume = source[source.index("def consume("):]
    consume = consume[: consume.index("\ndef drafts")]

    # Scoped by strand, not by subject or batch: saving Creation must leave
    # The Bible's draft exactly where it is.
    assert "LOWER(strand) = LOWER(:strand)" in consume
    assert "consumed_at IS NULL" in consume


def test_saving_a_strand_consumes_only_that_strands_draft():
    source = _read("app/routes/curriculum.py")
    save = source[source.index("def factory_save_substrands"):]
    save = save[: save.index('"draft_consumed"') + 40]

    assert "job_queue.consume(" in save
    assert 'strand=payload.strand_name' in save
    assert 'kind="substrands"' in save


def test_a_finished_draft_is_not_treated_as_a_duplicate():
    """Regenerating a strand whose draft is still waiting is a legitimate ask."""
    source = _read("app/services/job_queue.py")
    enqueue = source[source.index("def enqueue("):]
    enqueue = enqueue[: enqueue.index("\ndef consume")]

    assert "status IN ('queued', 'running')" in enqueue
    assert "'done'" not in enqueue.split("LIMIT 1")[0]


def test_the_drafts_column_has_a_migration():
    source = _read("app/infra/db.py")
    assert '"023_job_drafts"' in source
    assert "ADD COLUMN IF NOT EXISTS consumed_at" in source

    names = re.findall(r'^\s+"(\d{3}_[a-z0-9_]+)",', source, re.M)
    assert names == sorted(names), "migrations must run in the order they are listed"


def test_the_queue_endpoint_refuses_a_subject_with_no_strands():
    source = _read("app/routes/curriculum.py")
    route = source[source.index("def factory_queue_substrands"):]
    route = route[: route.index("\n@router.get")]

    assert "MISSING_PARENT_CONTEXT" in route
    # Naming nothing means "the ones still outstanding", not "all of them
    # again" — requeuing a saved strand spends money to overwrite good work.
    # Strands live in the design's metadata rather than a table, so the
    # exclusion is a set difference against the sub-strands already stored.
    assert "DISTINCT strand_name FROM curriculum_substrands" in route
    assert "not in covered" in route


# ── the console cannot lose a draft by re-rendering ─────────────────────────


def test_the_structure_builder_is_rendered_from_one_position():
    """Two positions meant the first save unmounted it and took the drafts."""
    view = _front("src/views/ContentFactory.tsx")
    assert view.count("<CurriculumStructure") == 1, (
        "Rendering the builder from a ternary puts it at two positions in the "
        "tree, so React remounts it on the first save and every draft it holds "
        "for the other strands is destroyed."
    )


def test_the_builder_still_opens_itself_when_there_is_work_left():
    view = " ".join(_front("src/views/ContentFactory.tsx").split())
    assert "open={allSubstrands.length === 0 || strandsRemaining > 0}" in view


def test_the_console_reads_queued_drafts_as_well_as_its_own():
    view = _front("src/views/CurriculumStructure.tsx")
    assert "useSubstrandDrafts" in view
    assert "serverDrafts[name]" in view
    # Saving reaches for either kind, so the operator never has to know which
    # route a draft arrived by.
    assert "drafts[name] || serverDrafts[name]?.subs || []" in view


def test_the_drafts_poll_stops_when_the_queue_is_idle():
    queries = _front("src/lib/queries.ts")
    drafts = queries[queries.index("export function useSubstrandDrafts"):]
    drafts = drafts[: drafts.index("export function useDiscardDraft")]
    assert "refetchInterval: active ? 4000 : false" in drafts


def test_queueing_the_rest_skips_strands_already_done_or_drafted():
    view = " ".join(_front("src/views/CurriculumStructure.tsx").split())
    body = view[view.index("async function queueRemaining"):]
    body = body[: body.index("}") + 400]

    assert "saved[t.strand_name] === undefined" in body
    assert "!serverDrafts[t.strand_name]" in body


# ── a draft outlives the code that made it ──────────────────────────────────


def test_a_draft_records_which_generator_wrote_it():
    """Queued drafts persist across deploys, so after the generator is fixed
    the console still shows drafts from the old one — identical in shape, with
    nothing saying they are not current. That cost four rounds of "how accurate
    is this" on output already diagnosed."""
    source = _read("app/routes/curriculum.py")
    handler = source[source.index("def _run_queued_substrands"):]
    handler = handler[: handler.index("\ndef _run_queued_review")]

    assert '"generator": generation_version.VERSION' in handler


def test_the_drafts_endpoint_marks_stale_ones():
    source = _read("app/routes/curriculum.py")
    route = source[source.index("def factory_queue_drafts"):]
    route = route[: route.index("\n@router.post")]

    assert '"stale":' in route
    assert '"missing":' in route
    assert "generation_version.is_current" in route


def test_stale_drafts_can_be_discarded_in_one_go():
    source = _read("app/routes/curriculum.py")
    assert "def factory_discard_stale_drafts" in source
    route = source[source.index("def factory_discard_stale_drafts"):]
    route = route[: route.index("\n@router.post")]
    # Only the stale ones. Discarding a current draft would throw away work
    # that is waiting to be saved.
    assert "if generation_version.is_current(result.get(\"generator\")):" in route
    assert "continue" in route


def test_the_version_is_described_rather_than_only_compared():
    """"Old" is not actionable. "Missing the rubric page scoping" is."""
    from app.services import generation_version as gv

    assert gv.describe(gv.VERSION) == "current"
    assert "rubric" in gv.describe("2026-08-28.rubric-tables").lower()
    assert "before generator versions" in gv.describe("something-unknown")


def test_the_console_refuses_to_present_a_stale_draft_as_current():
    view = _front("src/views/CurriculumStructure.tsx")

    assert "produced by an older generator" in view
    assert "older generator)" in view, "the strand row says so too"
    assert "Discard {staleDrafts.length} stale draft(s)" in view
