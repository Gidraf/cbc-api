"""The outer review cycle does not re-run a station that has already repaired
itself, and returns the best cycle rather than the last.

One notes job ran two full generations — six lessons, write-time retries and
four remediation passes each — because the gate failed on outstanding findings
and the cycle re-ran the whole station. The first reached 20/100; the second
reached 0; the second was saved.
"""
from __future__ import annotations

from app.services import review_cycle


def _result(score: int, passes: int, attempted: bool = True) -> dict:
    return {
        "quality_gate": {"passed": False, "overall_score": score,
                         "summary_message": "needs revision",
                         "next_actions": ["Improve x: y"],
                         "reviewer": {"feedback": [{"aspect": "x", "comment": "y", "status": "fail"}]}},
        "artifact": {"artifact_id": f"a{score}", "version": 1},
        "remediation": {"attempted": attempted, "passes_run": passes},
    }


def test_a_station_that_ran_its_own_loop_is_not_run_again() -> None:
    produced: list[str] = []

    def produce(instructions: str) -> dict:
        produced.append(instructions)
        return _result(20, passes=4)

    out, report = review_cycle.run(produce, label="notes", max_cycles=3)

    assert len(produced) == 1
    assert report.stopped_because == "station_exhausted"
    assert out["artifact"]["artifact_id"] == "a20"


def test_the_best_cycle_is_returned_not_the_last() -> None:
    scores = iter([20, 0, 5])

    def produce(instructions: str) -> dict:
        return _result(next(scores), passes=1, attempted=False)

    out, report = review_cycle.run(produce, label="notes", max_cycles=3)

    assert report.best_cycle == 1 and report.best_score == 20
    assert out["artifact"]["artifact_id"] == "a20"


def test_a_station_with_no_loop_of_its_own_still_cycles() -> None:
    scores = iter([40, 60, 80])
    calls = {"n": 0}

    def produce(instructions: str) -> dict:
        calls["n"] += 1
        return _result(next(scores), passes=0, attempted=False)

    review_cycle.run(produce, label="diagram", max_cycles=3)
    assert calls["n"] == 3
