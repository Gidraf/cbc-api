"""Work survives a deploy, a crash, a lost message.

A job cut down by a deploy sat 'running' for ever; a job queued when its
broker message went missing sat 'queued' for ever. Now: every running job
heartbeats, a sweeper (API thread and worker beat) requeues the abandoned
and re-dispatches the stranded every two minutes, and a redelivered
message may reclaim its own job.
"""
from __future__ import annotations

import time
from types import SimpleNamespace

from app.services import job_queue as jq


class _Jobs:
    def __init__(self, rows):
        self.rows = {r["job_id"]: dict(r) for r in rows}
        self.dispatched: list[str] = []
        self.sql: list[str] = []

    def fetch_all(self, sql, params=None):
        self.sql.append(sql)
        params = params or {}
        if "COALESCE(heartbeat_at, started_at) <" in sql:
            return [r for r in self.rows.values() if r["status"] == "running" and r.get("stale")]
        if "status = 'queued' AND started_at IS NULL" in sql:
            return [r for r in self.rows.values() if r["status"] == "queued" and r.get("old")]
        return []

    def fetch_one(self, sql, params=None):
        params = params or {}
        if "SELECT heartbeat_at, started_at <" in sql:
            r = self.rows[params["job_id"]]
            return {"heartbeat_at": r.get("heartbeat_at"), "old": r.get("very_old", False)}
        if "RETURNING *" in sql:  # _claim_by_id
            r = self.rows[params["job_id"]]
            if r["status"] != "queued":
                return None
            r["status"] = "running"; r["attempts"] = r.get("attempts", 0) + 1
            return dict(r)
        return None

    def execute(self, sql, params=None):
        self.sql.append(sql)
        params = params or {}
        r = self.rows.get(params.get("job_id", ""))
        if r is None:
            return
        if "SET status = 'failed'" in sql and r["status"] == "running":
            r["status"] = "failed"; r["error"] = params.get("error", "")
        elif "SET status = 'queued', started_at = NULL" in sql and r["status"] == "running":
            if "attempts < :max" in sql and r.get("attempts", 0) >= params["max"]:
                return
            r["status"] = "queued"
        elif "SET heartbeat_at = NOW()" in sql:
            r["heartbeat_at"] = "now"


def _wire(monkeypatch, rows):
    from app.infra import db

    table = _Jobs(rows)
    monkeypatch.setattr(db, "fetch_all", table.fetch_all)
    monkeypatch.setattr(db, "fetch_one", table.fetch_one)
    monkeypatch.setattr(db, "execute", table.execute)
    monkeypatch.setattr(jq, "dispatch", lambda job_id: table.dispatched.append(job_id) or "celery")
    return table


def test_abandoned_running_jobs_go_back_to_the_queue_and_out_of_attempts_fail(monkeypatch):
    table = _wire(monkeypatch, [
        {"job_id": "alive", "kind": "notes", "status": "running", "attempts": 1, "heartbeat_at": "now", "stale": False},
        {"job_id": "dead", "kind": "notes", "status": "running", "attempts": 1, "heartbeat_at": "then", "stale": True},
        {"job_id": "spent", "kind": "notes", "status": "running", "attempts": 2, "heartbeat_at": "then", "stale": True},
        # From before the heartbeat existed: no heartbeat, judged by started_at.
        {"job_id": "legacy-fresh", "kind": "notes", "status": "running", "attempts": 1, "heartbeat_at": None, "stale": True, "very_old": False},
        {"job_id": "legacy-old", "kind": "notes", "status": "running", "attempts": 1, "heartbeat_at": None, "stale": True, "very_old": True},
    ])
    assert jq.recover_stalled() == 2
    assert table.rows["alive"]["status"] == "running"
    assert table.rows["dead"]["status"] == "queued" and "dead" in table.dispatched
    assert table.rows["spent"]["status"] == "failed" and "out of attempts" in table.rows["spent"]["error"]
    assert table.rows["legacy-fresh"]["status"] == "running", "a long job from before the column is left alone"
    assert table.rows["legacy-old"]["status"] == "queued"


def test_stranded_queued_jobs_are_dispatched_again(monkeypatch):
    table = _wire(monkeypatch, [
        {"job_id": "fresh", "kind": "notes", "status": "queued", "old": False},
        {"job_id": "stranded", "kind": "notes", "status": "queued", "old": True},
    ])
    assert jq.redispatch_stranded() == 1 and table.dispatched == ["stranded"]
    out = jq.sweep()
    assert out == {"recovered": 0, "redispatched": 1}


def test_a_redelivered_message_reclaims_the_job_its_dead_worker_held(monkeypatch):
    table = _wire(monkeypatch, [
        {"job_id": "j1", "kind": "notes", "status": "running", "attempts": 1},
    ])
    monkeypatch.setattr(jq, "scope_is_busy", lambda job_id: False)
    ran = []
    monkeypatch.setattr(jq, "_execute", lambda job: ran.append(job["job_id"]) or {"job_id": job["job_id"], "status": "done"})

    # Delivered fresh: a running row is somebody else's and is left alone.
    assert jq.run_job_by_id("j1")["status"] == "skipped" and ran == []
    # Redelivered: the worker that held it is gone; take it.
    assert jq.run_job_by_id("j1", redelivered=True)["status"] == "done" and ran == ["j1"]
    assert table.rows["j1"]["attempts"] == 2

    # But not past the attempt ceiling.
    table.rows["j1"].update(status="running", attempts=2)
    assert jq.run_job_by_id("j1", redelivered=True)["status"] == "skipped"


def test_a_running_job_heartbeats_while_it_runs(monkeypatch):
    table = _wire(monkeypatch, [{"job_id": "h1", "kind": "notes", "status": "running"}])
    monkeypatch.setattr(jq, "HEARTBEAT_SECONDS", 0.05)
    beat = jq._Heartbeat("h1")
    beat.start()
    time.sleep(0.2)
    beat.stop()
    assert table.rows["h1"]["heartbeat_at"] == "now"
    assert sum(1 for s in table.sql if "SET heartbeat_at = NOW()" in s) >= 2


def test_the_worker_sweeps_on_its_beat_and_the_task_reads_redelivery():
    from app import celery_app, tasks

    assert "sweep-jobs" in celery_app.celery_app.conf.beat_schedule
    assert celery_app.celery_app.conf.beat_schedule["sweep-jobs"]["task"] == "app.tasks.sweep_jobs"
    import inspect
    src = inspect.getsource(tasks.run_job)
    assert "redelivered=bool(info.get(\"redelivered\"))" in src


def test_the_board_filters_by_status_kind_and_search_and_reports_heartbeats(monkeypatch):
    from app.infra import db

    seen = {}

    def fetch_all(sql, params=None):
        seen.setdefault("sqls", []).append(sql)
        if "ORDER BY (status = 'running') DESC" in sql:
            seen["params"] = params
            return [{"job_id": "j1", "kind": "pipeline", "status": "running", "heartbeat_age_s": 12, "age_s": 400,
                     "last_step": {"step": "Lesson 3", "detail": "written", "status": "ok"}, "queued_by": "gm",
                     "llm_calls": 4, "cost_usd": 0.12}]
        return []
    monkeypatch.setattr(db, "fetch_all", fetch_all)
    monkeypatch.setattr(db, "fetch_one", lambda sql, params=None: None)
    monkeypatch.setattr(jq, "worker_running", lambda: False)
    monkeypatch.setattr(jq, "_celery_reachable", lambda: True)

    out = jq.status(job_status="running,queued", kind="pipeline", search="Integers", limit=50)
    assert seen["params"]["statuses"] == ["running", "queued"] and seen["params"]["kind"] == "pipeline"
    assert seen["params"]["search"] == "%Integers%"
    sql = [q for q in seen["sqls"] if "ORDER BY (status = 'running') DESC" in q][0]
    assert "heartbeat_age_s" in sql and "last_step" in sql and "queued_by" in sql
    assert out["jobs"][0]["heartbeat_age_s"] == 12 and out["jobs"][0]["last_step"]["step"] == "Lesson 3"
    assert out["runs_on"] == "celery"
