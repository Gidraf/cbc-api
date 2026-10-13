"""Video jobs that survive deploys, and progress that moves while they render.

A deploy killed every render mid-way (Docker gives a stopping container 10
seconds), charged the job an attempt, and two deploys failed a healthy render
as "out of attempts". A batch's bar moved only when a video was finished.
"""
from __future__ import annotations

import pathlib
import re

from app.services import job_queue, video_batches

ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_a_restart_refunds_the_attempt_and_counts_an_interruption(monkeypatch):
    from app.infra import db

    sql, sent = [], []
    monkeypatch.setattr(db, "fetch_all", lambda q, p=None: [
        {"job_id": "j1", "kind": "social", "attempts": 2, "interruptions": 1, "heartbeat_at": "x"}])
    monkeypatch.setattr(db, "execute", lambda q, p=None: sql.append((q, p)))
    monkeypatch.setattr(job_queue, "dispatch", lambda jid: sent.append(jid))

    assert job_queue.recover_stalled() == 1
    q, p = sql[0]
    assert "attempts = GREATEST(attempts - 1, 0)" in q and "interruptions = interruptions + 1" in q
    assert "status = 'queued'" in q and sent == ["j1"], "back in the queue at once, not failed"


def test_a_job_cut_off_again_and_again_is_stopped(monkeypatch):
    from app.infra import db

    sql = []
    monkeypatch.setattr(db, "fetch_all", lambda q, p=None: [
        {"job_id": "j2", "kind": "social", "attempts": 0, "interruptions": job_queue.MAX_INTERRUPTIONS,
         "heartbeat_at": "x"}])
    monkeypatch.setattr(db, "execute", lambda q, p=None: sql.append((q, p)))
    monkeypatch.setattr(job_queue, "dispatch", lambda jid: None)

    assert job_queue.recover_stalled() == 0
    assert "status = 'failed'" in sql[0][0] and "Cut off mid-run" in sql[0][1]["error"]


def test_after_a_restart_the_patience_is_short(monkeypatch):
    from app.infra import db

    seen = {}
    monkeypatch.setattr(db, "fetch_all", lambda q, p=None: seen.update(p or {}) or [])
    job_queue.recover_stalled(minutes=job_queue.RESTART_ABANDONED_MINUTES)
    assert seen["minutes"] == 2, "four missed 30-second heartbeats is a dead worker"


def test_a_redelivered_message_only_reclaims_a_job_whose_heartbeat_stopped(monkeypatch):
    from app.infra import db

    sql = []
    monkeypatch.setattr(db, "execute", lambda q, p=None: sql.append((q, p)))
    monkeypatch.setattr(job_queue, "scope_is_busy", lambda jid: False)
    monkeypatch.setattr(job_queue, "_claim_by_id", lambda jid: None)
    job_queue.run_job_by_id("j3", redelivered=True)
    q, p = sql[0]
    assert "COALESCE(heartbeat_at, started_at) < NOW()" in q, "never while its worker is still on it"
    assert "attempts = GREATEST(attempts - 1, 0)" in q and p["max"] == job_queue.MAX_INTERRUPTIONS


def test_live_progress_is_one_percentage_over_weighted_stages(monkeypatch):
    written = []
    live = job_queue.Live("j4")
    monkeypatch.setattr(live, "write", lambda d: written.append(d))
    assert live.percent("script", 1, 1) == 3
    assert live.percent("voice", 9, 9) == 12
    assert live.percent("draw", 900, 1800) == 12 + 39
    assert live.percent("save", 1, 1) == 100
    live("draw", 1, 1800)
    live("draw", 2, 1800)          # within two seconds: not written again
    assert len(written) == 1 and written[0]["stage"] == "draw"
    live("mux", 0, 1)              # a new stage always is
    assert written[-1]["stage"] == "mux" and written[-1]["pct"] == 90
    live.done()
    assert written[-1] == {"stage": "done", "pct": 100}


def test_progress_never_goes_backwards():
    live = job_queue.Live("j5")
    live.write = lambda d: None
    live("draw", 1500, 1800)
    live("voice", 0, 9)            # a late report from an earlier stage
    assert live.pct >= 12 + 78 * 1500 / 1800 - 0.1


def test_a_batch_bar_counts_the_video_in_hand():
    rendering = [video_batches._rendering({"job_id": "j", "title": "Find the mass number", "seconds": 75,
                                           "live": {"stage": "draw", "n": 900, "total": 1800, "pct": 51},
                                           "interruptions": 1})]
    out = video_batches.summarise({"batch_id": "vb_1"}, {"done": 2, "running": 1, "queued": 1}, 120.0, 1, 0,
                                  rendering=rendering, resumed=1)
    assert out["progress_pct"] == round(100 * (2 + 0.51) / 4, 1)
    r = out["rendering"][0]
    assert r["stage"] == "Drawing" and r["frame"] == "900 of 1800" and r["resumed"] and r["pct"] == 51
    assert out["eta_seconds"] == round((2 - 0.51) * 120), "the video in hand is half done"
    assert out["resumed"] == 1


def test_compose_lets_a_render_finish_and_a_loading_redis_start():
    text = (ROOT / "docker-compose.yml").read_text()
    worker = text.split("\n  generation-worker:", 1)[1].split("\n  scheduler:", 1)[0]
    redis = text.split("\n  redis:\n", 1)[1].split("\n  playwright:", 1)[0]
    assert re.search(r"^\s+stop_grace_period: 3m$", worker, re.M)
    assert re.search(r"^\s+start_period: 120s$", redis, re.M)
    assert "--appendfsync everysec" in redis


def test_a_new_worker_resumes_what_the_old_one_was_cut_off_in():
    source = (ROOT / "backend/app/celery_app.py").read_text()
    assert "worker_ready" in source and "recover_stalled(minutes=job_queue.RESTART_ABANDONED_MINUTES)" in source
    assert "redispatch_stranded()" in source
