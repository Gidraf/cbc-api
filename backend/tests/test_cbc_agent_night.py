"""The night planner: phases, a target shared out, carry-over, catch-up
nights, guides before questions, and an honest morning report."""
from __future__ import annotations

import argparse
import json
import os

import pytest

from app.agent_clients import cbc_agent as ca

CAMPAIGN = {"start": "2026-10-09", "grades": ["grade-9"], "subjects": [],
            "phases": [{"name": "create", "weeks": 10, "target_questions": 120},
                       {"name": "review", "weeks": 20}],
            "repeat": [{"name": "create", "weeks": 15, "target_questions": 240}, {"name": "review", "weeks": 15}],
            "batch": 20, "carry_limit_nights": 2, "max_attempts": 3}

COVERAGE = {
    "Mathematics": [
        {"strand": "Numbers", "sub_strand": "Integers", "questions": 38, "has_notes": True, "last_reviewed": None},
        {"strand": "Numbers", "sub_strand": "Fractions", "questions": 5, "has_notes": True, "last_reviewed": "2026-12-20"},
        {"strand": "Algebra", "sub_strand": "Equations", "questions": 0, "has_notes": False, "last_reviewed": None},
    ],
    "Integrated Science": [
        {"strand": "Matter", "sub_strand": "Atoms", "questions": 12, "has_notes": True, "last_reviewed": None},
    ],
}


@pytest.fixture
def fake(monkeypatch, tmp_path):
    monkeypatch.setattr(ca, "PLANNER_DIR", str(tmp_path))
    monkeypatch.setattr(ca, "_ingested_subjects", lambda grade: list(COVERAGE))

    def platform(method, path, body=None):
        if path.startswith("/api/v1/agent/coverage"):
            subject = path.split("subject=")[1].split("&")[0].replace("%20", " ")
            return {"sub_strands": COVERAGE[subject]}
        raise AssertionError(path)

    monkeypatch.setattr(ca, "_platform", platform)
    return tmp_path


def _jobs(state, ids):
    return [(state["jobs"][i]["kind"], state["jobs"][i]["sub_strand"]) for i in ids]


def test_phases_run_in_order_then_the_cycle_repeats() -> None:
    assert ca.phase_for(CAMPAIGN, "2026-10-09")["name"] == "create"
    assert ca.phase_for(CAMPAIGN, "2026-12-17")["name"] == "create"         # day 70 is the last
    assert ca.phase_for(CAMPAIGN, "2026-12-18")["name"] == "review"         # weeks 11–30
    p = ca.phase_for(CAMPAIGN, "2027-05-10")                                # after 30 weeks
    assert p["name"] == "create" and p["target_questions"] == 240 and p["cycle"] == 1


def test_a_create_night_shares_the_target_out_and_writes_a_guide_before_its_questions(fake) -> None:
    state: dict = {}
    plan = ca.plan_night(CAMPAIGN, state, night="2026-10-09", window="22:00-07:00", minutes_left=540)

    assert state["phases"][plan["phase"]["key"]]["per_sub_strand"] == 30, "120 over 4 sub-strands"
    planned = _jobs(state, plan["new"])
    # Emptiest first; Integers (38 of 30) is already full and is left alone.
    assert planned[:2] == [("notes", "Equations"), ("questions", "Equations")]
    assert ("questions", "Integers") not in planned
    eq = state["jobs"][plan["new"][1]]
    assert eq["after"] == plan["new"][0] and eq["count"] == 20
    assert state["jobs"][plan["new"][2]]["sub_strand"] == "Fractions"


def test_the_night_is_filled_to_its_measured_capacity(fake) -> None:
    state = {"measured": {"questions": [120, 120, 120], "notes": [60]}}
    plan = ca.plan_night(CAMPAIGN, state, night="2026-10-09", window="22:00-07:00", minutes_left=200)
    # 200 minutes: a guide (60) + its questions (120) uses it up; nothing else fits.
    assert _jobs(state, plan["new"]) == [("notes", "Equations"), ("questions", "Equations")]


def test_carried_jobs_come_first_and_a_big_backlog_makes_a_catch_up_night(fake) -> None:
    state: dict = {}
    for n in range(30):
        ca._new_job(state, "questions", {"strand": "S", "sub_strand": f"Old {n}"}, "grade-9", "Mathematics",
                    "2026-10-01", count=20)
    plan = ca.plan_night(CAMPAIGN, state, night="2026-10-09", window="22:00-07:00", minutes_left=540)
    assert plan["catch_up"] is True and plan["new"] == [], "30 × 40 min is more than 2 nights' work"
    assert len(plan["carried"]) == 30

    small: dict = {}
    ca._new_job(small, "questions", {"strand": "S", "sub_strand": "Carried"}, "grade-9", "Mathematics",
                "2026-10-08", count=20)
    plan = ca.plan_night(CAMPAIGN, small, night="2026-10-09", window="22:00-07:00", minutes_left=540)
    assert plan["catch_up"] is False and plan["carried"] and plan["new"], "a small carry-over plus new work"


def test_a_review_night_takes_the_never_reviewed_first(fake) -> None:
    state: dict = {}
    plan = ca.plan_night(CAMPAIGN, state, night="2027-01-05", window="22:00-07:00", minutes_left=540)
    assert plan["phase"]["name"] == "review"
    planned = _jobs(state, plan["new"])
    assert planned[0][0] == "review" and planned[0][1] in ("Integers", "Atoms")
    assert ("review", "Equations") not in planned, "nothing to review where there are no questions"
    assert ("review", "Fractions") not in planned, "reviewed within this phase already"


def test_working_a_night_records_done_failed_and_carries_at_the_window(fake, monkeypatch) -> None:
    state: dict = {}
    plan = ca.plan_night(CAMPAIGN, state, night="2026-10-09", window="22:00-07:00", minutes_left=540)
    ran = []

    def run(args):
        ran.append((args.station, args.sub_strand))
        if args.sub_strand == "Equations" and args.station == "notes":
            return {"status": "failed", "error": "the guide failed its checks"}
        if args.sub_strand == "Atoms":
            raise ca._WindowClosed()
        return {"status": "done", "result": {"saved": 20}}

    monkeypatch.setattr(ca, "run", run)
    monkeypatch.setattr(ca, "_in_window", lambda w, now=None: True)
    args = argparse.Namespace(model="qwen3:14b", llm_url="http://x/v1", window="22:00-07:00", plan_only=False)
    tally = ca.work_night(plan, state, CAMPAIGN, args)

    jobs = state["jobs"]
    notes_id, eq_id = plan["new"][0], plan["new"][1]
    assert jobs[notes_id]["status"] == "carried" and jobs[notes_id]["attempts"] == 1
    assert jobs[eq_id]["status"] == "carried" and ("questions", "Equations") not in ran, \
        "questions wait for their guide"
    assert tally["saved"] == 20 and jobs[plan["new"][2]]["status"] == "done"
    atoms = next(j for j in jobs.values() if j["sub_strand"] == "Atoms")
    assert atoms["status"] == "carried", "the window closed mid-job; it resumes next night"
    report = ca._report(plan, tally, state, CAMPAIGN)
    text = open(report).read()
    assert "Questions saved tonight: 20" in text and "Toward 120 questions" in text


def test_a_job_that_keeps_failing_is_given_up(fake, monkeypatch) -> None:
    state: dict = {}
    job = ca._new_job(state, "questions", {"strand": "S", "sub_strand": "Broken"}, "grade-9", "Mathematics",
                      "2026-10-01", count=5)
    job["attempts"] = 2
    plan = {"night": "2026-10-09", "phase": ca.phase_for(CAMPAIGN, "2026-10-09"), "carried": [job["id"]],
            "new": [], "catch_up": False}
    monkeypatch.setattr(ca, "run", lambda args: {"status": "failed", "error": "no"})
    monkeypatch.setattr(ca, "_in_window", lambda w, now=None: True)
    args = argparse.Namespace(model="m", llm_url="u", window="", plan_only=False)
    tally = ca.work_night(plan, state, CAMPAIGN, args)
    assert state["jobs"][job["id"]]["status"] == "given_up" and tally["given_up"] == [job["id"]]
    assert ca._open_jobs(state) == [], "a given-up job is not carried for ever"


def test_the_night_belongs_to_the_evening_it_started() -> None:
    import time as _t

    assert ca._night_of(_t.strptime("2026-10-09 03:00", "%Y-%m-%d %H:%M")) == "2026-10-08"
    assert ca._night_of(_t.strptime("2026-10-08 22:30", "%Y-%m-%d %H:%M")) == "2026-10-08"
