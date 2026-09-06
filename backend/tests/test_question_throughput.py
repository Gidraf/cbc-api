"""What a day is supposed to produce, and what it actually produced.

Selling this content means knowing whether today's work happened — not whether
the generator can be run. Three separate daily rates that only balance over
weeks: 500 written, 250 read, 50 signed for.
"""
from __future__ import annotations

import inspect

import pytest

from app.services import question_throughput as th


def test_each_stage_is_counted_against_its_own_rate() -> None:
    """The event is past tense and the rate is not. Deriving one from the
    other is how "reviewed" quietly becomes "reviewe_per_day"."""
    target = th.Target()

    assert target.per_day(th.GENERATED) == 500
    assert target.per_day(th.REVIEWED) == 250
    assert target.per_day(th.APPROVED) == 50
    assert target.per_day("nonsense") == 0


def test_a_day_reports_how_far_short_it_fell() -> None:
    day = th.DayProgress(
        grade="grade-9", subject="Mathematics", on="2026-09-06",
        done={th.GENERATED: 500, th.REVIEWED: 60, th.APPROVED: 10},
        target=th.Target())

    stages = {s["stage"]: s for s in day.to_dict()["stages"]}
    assert stages[th.GENERATED]["share"] == 100.0
    assert stages[th.REVIEWED]["short_by"] == 190
    assert stages[th.APPROVED]["share"] == 20.0


def test_overshooting_a_target_does_not_report_over_a_hundred() -> None:
    day = th.DayProgress(done={th.GENERATED: 900}, target=th.Target())

    assert day.share(th.GENERATED) == 100.0


def test_the_queue_is_what_actually_warns() -> None:
    """The number that kills this operation is not "we generated 400 today".
    It is "3,000 are waiting and nobody noticed"."""
    day = th.DayProgress(target=th.Target(), awaiting_review=3000)

    warnings = " ".join(day.warnings)
    assert "3000 items are waiting to be reviewed" in warnings
    assert "12 days of reading" in warnings
    assert "makes that worse" in warnings


def test_a_backlog_within_a_few_days_of_reading_is_not_a_warning() -> None:
    """A queue is normal. A queue nobody can clear is not."""
    assert th.DayProgress(target=th.Target(), awaiting_review=400).warnings == []


def test_nothing_can_be_sold_until_somebody_signs_it() -> None:
    day = th.DayProgress(target=th.Target(), awaiting_approval=900)

    assert any("waiting for approval" in w for w in day.warnings)


def test_items_the_gate_stopped_are_reported_as_never_reaching_a_person() -> None:
    day = th.DayProgress(target=th.Target(), blocked_today=12)

    assert any("never reached a reviewer" in w for w in day.warnings)


def test_a_generation_run_is_counted_per_item_not_per_run(monkeypatch) -> None:
    """The target is written in questions. Counting runs would make a run of 4
    look like a run of 400."""
    written: list[dict] = []
    monkeypatch.setattr(th, "record",
                        lambda event, **k: written.append({"event": event, **k}) or True)

    n = th.record_batch(th.GENERATED,
                        [{"question_id": "q1"}, {"question_id": "q2"}, "not a dict"],
                        grade="grade-9", subject="Mathematics")

    assert n == 2
    assert [w["question_id"] for w in written] == ["q1", "q2"]


def test_counting_never_takes_down_the_work_it_counts(monkeypatch) -> None:
    """A day's counting is worth less than the work it counts."""
    from app.infra import db

    def _boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(db, "execute", _boom)

    assert th.record(th.GENERATED, question_id="q1") is False


def test_a_target_falls_back_to_the_one_set_for_the_subject(monkeypatch) -> None:
    """Otherwise adding a strand silently drops it out of the day's plan."""
    from app.infra import db

    monkeypatch.setattr(db, "fetch_all", lambda *a, **k: [
        {"grade": "grade-9", "subject": "Mathematics", "strand": "",
         "generate_per_day": 300, "review_per_day": 150,
         "approve_per_day": 30, "active": True}])

    target = th.get_target("grade-9", "Mathematics", "Numbers")

    assert target.generate_per_day == 300
    assert target.strand == "", "the subject-wide one, because the strand has none"


def test_the_most_specific_target_wins(monkeypatch) -> None:
    from app.infra import db

    monkeypatch.setattr(db, "fetch_all", lambda *a, **k: [
        {"grade": "grade-9", "subject": "Mathematics", "strand": "Numbers",
         "generate_per_day": 80, "review_per_day": 40, "approve_per_day": 8,
         "active": True},
        {"grade": "grade-9", "subject": "Mathematics", "strand": "",
         "generate_per_day": 500, "review_per_day": 250, "approve_per_day": 50,
         "active": True}])

    assert th.get_target("grade-9", "Mathematics", "Numbers").generate_per_day == 80


def test_a_scope_with_no_target_gets_the_stated_defaults(monkeypatch) -> None:
    from app.infra import db

    monkeypatch.setattr(db, "fetch_all", lambda *a, **k: [])
    target = th.get_target("grade-12", "Mathematics")

    assert (target.generate_per_day, target.review_per_day,
            target.approve_per_day) == (500, 250, 50)


def test_a_database_that_is_down_does_not_break_the_board(monkeypatch) -> None:
    from app.infra import db

    def _boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(db, "fetch_all", _boom)

    assert th.get_target("grade-9", "Mathematics").generate_per_day == 500
    assert th.history("grade-9", "Mathematics") == []


# ── wiring ──────────────────────────────────────────────────────────────────


def test_the_structure_gate_holds_items_before_a_person_sees_them() -> None:
    from app.routes import questions

    source = inspect.getsource(questions)
    assert "question_structure.check_all(normalized_questions)" in source
    assert 'v["blocked"]' in source
    # Held with the reason AND the fix — a queue of rejections nobody can act
    # on is a queue nobody works.
    assert '"fix":' in source
    assert '"stage": "structure"' in source


def test_the_generation_records_what_it_produced_and_what_it_held() -> None:
    from app.routes import questions

    source = inspect.getsource(questions)
    assert "question_throughput.record_batch(" in source
    assert "question_throughput.BLOCKED" in source


def test_a_step_is_an_event_not_a_status_column() -> None:
    """An item generated, reviewed, rejected and regenerated in one day shows
    as one generation on a status column, and the reviewer's day disappears."""
    from app.routes import questions

    source = inspect.getsource(questions.record_question_step)
    assert "question_throughput.record(" in source
    assert "is not a step" in source, "an unknown event is refused, not recorded"


def test_the_board_carries_today_and_the_fortnight_behind_it() -> None:
    from app.routes import questions

    source = inspect.getsource(questions.question_throughput_board)
    assert "question_throughput.progress(" in source
    assert "question_throughput.history(" in source


# ── the board ───────────────────────────────────────────────────────────────

from pathlib import Path  # noqa: E402

FRONTEND = Path(__file__).resolve().parents[2] / "frontend-web"


def test_the_board_draws_the_queues_not_only_the_counts() -> None:
    """Three numbers invite being read as a ratio. The useful picture is the
    funnel with what is waiting between the stages drawn in."""
    panel = " ".join((FRONTEND / "src/ui/QuestionPipeline.tsx").read_text().split())

    assert "waiting" in panel
    assert "awaitingReview" in panel and "awaitingApproval" in panel
    # Widths follow the targets, so the funnel narrows the way the operation is
    # meant to; the fill inside is the day's progress.
    assert "s.target || 1) / widest" in panel
    assert "width: `${s.share}%`" in panel


def test_the_board_shows_whether_the_queue_is_growing() -> None:
    panel = " ".join((FRONTEND / "src/ui/QuestionPipeline.tsx").read_text().split())

    assert "Written against read" in panel
    assert "data.history" in panel


def test_the_day_s_plan_can_be_set_from_the_board() -> None:
    panel = " ".join((FRONTEND / "src/ui/QuestionPipeline.tsx").read_text().split())

    assert "Set the day's plan" in panel
    assert "useSetQuestionTarget" in panel


def test_the_gate_is_visible_where_the_work_is_planned() -> None:
    """Items held by the structure gate never reached a reviewer, so they are
    invisible everywhere else."""
    panel = " ".join((FRONTEND / "src/ui/QuestionPipeline.tsx").read_text().split())
    factory = " ".join((FRONTEND / "src/views/ContentFactory.tsx").read_text().split())

    assert "Structure of what is filed" in panel
    assert "would be held" in panel
    assert "QuestionPipeline" in factory


def test_a_day_is_bounded_in_python_not_cast_in_sql() -> None:
    """`:on::date` is read by SQLAlchemy as a bind parameter named `o`
    followed by the literal `n::date`. The query asked for a parameter nothing
    supplied, raised, was swallowed by the guard, and every count came back
    zero — so the board showed "Written 0 / 500" beside "22 waiting", which is
    impossible."""
    import re

    from sqlalchemy import text

    for fn in (th._counts_today, th.history):
        sql = re.search(r'f"""(.*?)"""', inspect.getsource(fn), re.S).group(1)
        sql = re.sub(r"\{[^}]*\}", "a = :grade", sql)
        binds = set(text(sql)._bindparams)
        assert "o" not in binds, f"{fn.__name__} still casts a date in SQL"


def test_generated_questions_are_saved_not_only_returned() -> None:
    """Persistence lived only in `/factory/approve-batch`, a separate call
    nothing made automatically. A run could produce four good items, report
    them on screen and leave the bank empty — which is why coverage read
    "questions 0 / 345" after a successful run."""
    from app.routes import questions

    source = inspect.getsource(questions)

    assert "question_dna_service.save_batch_questions(" in source
    assert 'status="draft"' in source, "filed and countable, but not approved"
    assert '"saved": len(saved)' in source, "and the operator is told it was filed"
    # Losing the file is bad; losing the run as well is worse.
    saving = source.split("5b. SAVED")[1][:1200]
    assert "except Exception" in saving
