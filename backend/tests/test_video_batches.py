"""Batches of new social videos: only what is not made or on its way, one
batch to follow, an honest estimate, cancel and retry."""
from datetime import datetime, timezone

import pytest

from app.services import video_batches as B


@pytest.fixture
def world(monkeypatch):
    from app.infra import db
    from app.services import question_dna, question_rows, social

    states = {"q0": "ready", "q1": "queued", "q2": "running", "q3": "none", "q4": "failed", "q5": "none", "q6": "none"}
    bank = [{"question_id": q, "status": "draft"} for q in states] + [{"question_id": "held", "status": "needs_review"}]
    w = {"enqueued": [], "sql": [], "scopes": []}

    def list_questions(**kw):
        w["scopes"].append(kw.get("sub_strand"))
        return bank

    monkeypatch.setattr(question_dna.question_dna_service, "list_questions", list_questions)
    monkeypatch.setattr(question_rows, "flatten_all", lambda rows: rows)
    monkeypatch.setattr(social, "status", lambda qid, q=None, voice="": {"status": states[qid], "scenes": 0 if qid == "q6" else 3})
    monkeypatch.setattr(social, "enqueue", lambda qid, **kw: w["enqueued"].append((qid, kw["batch_id"])) or {"status": "queued"})
    monkeypatch.setattr(db, "execute", lambda sql, p=None: w["sql"].append((sql, p)))
    return w


def test_a_batch_takes_only_questions_with_no_video_made_or_coming(world):
    out = B.queue("grade-9", "Mathematics", count=10, mix=False, by="gidraf")
    assert [q for q, _ in world["enqueued"]] == ["q3", "q4", "q5"]
    assert out["queued"] == 3 and out["short"] == 7 and "Only 3 of 10" in out["note"]
    assert out["already"] == {"ready": 1, "queued": 1, "running": 1, "nothing to draw": 1}
    batch = {b for _, b in world["enqueued"]}
    assert len(batch) == 1 and out["batch_id"] in batch and out["batch_id"].startswith("vb_")
    sql, p = world["sql"][0]
    assert "INSERT INTO video_batches" in sql and p["q"] == 3 and p["req"] == 10 and p["by"] == "gidraf"


def test_a_batch_stops_at_its_count_and_can_cover_chosen_topics(world):
    out = B.queue("grade-9", "Mathematics", ["Integers", "Indices"], count=2, mix=False)
    assert out["queued"] == 2 and world["scopes"] == ["Integers", "Indices"]


def test_nothing_new_queues_no_batch(world, monkeypatch):
    from app.services import social

    monkeypatch.setattr(social, "status", lambda qid, q=None, voice="": {"status": "ready", "scenes": 3})
    out = B.queue("grade-9", "Mathematics", count=5)
    assert out["queued"] == 0 and out["batch_id"] == "" and world["sql"] == []


def test_progress_and_estimate():
    b = {"batch_id": "vb_1", "label": "Week 2", "created_at": datetime(2026, 10, 13, tzinfo=timezone.utc)}
    s = B.summarise(b, {"done": 4, "running": 1, "queued": 5, "failed": 1}, per_video=120, renders=1, ahead=3)
    assert (s["total"], s["done"], s["waiting"], s["failed"], s["finished"]) == (11, 4, 5, 1, False)
    assert s["eta_seconds"] == (3 + 6) * 120
    done = B.summarise(b, {"done": 10, "failed": 1}, per_video=120, renders=1, ahead=0)
    assert done["finished"] and done["eta_seconds"] is None
    assert B.summarise(b, {"queued": 4}, per_video=120, renders=2, ahead=0)["eta_seconds"] == 240


def test_retry_puts_only_this_batchs_failures_back(monkeypatch):
    from app.infra import db
    from app.services import job_queue

    seen, sent = [], []
    monkeypatch.setattr(db, "fetch_all", lambda sql, p=None: [{"job_id": "j1"}, {"job_id": "j2"}])
    monkeypatch.setattr(db, "execute", lambda sql, p=None: seen.append((sql, p)))
    monkeypatch.setattr(job_queue, "dispatch", lambda jid: sent.append(jid))
    assert B.retry("vb_1") == 2 and sent == ["j1", "j2"]
    assert "batch_id = :id AND status = 'failed'" in seen[0][0] and seen[0][1] == {"id": "vb_1"}


def test_booking_can_take_only_finished_videos(monkeypatch):
    from datetime import date

    from app.infra import db
    from app.services import platform_settings, question_dna, question_rows, social
    from app.services import social_export as X

    bank = [{"question_id": f"q{i}", "status": "draft", "curriculum": {}} for i in range(40)]
    planned = []
    monkeypatch.setattr(platform_settings, "get", lambda k, d=None: d)
    monkeypatch.setattr(db, "fetch_one", lambda sql, p=None: {"t": None})
    monkeypatch.setattr(db, "fetch_all", lambda sql, p=None: [{"platform": "facebook"}] if "poster_state" in sql else [])
    monkeypatch.setattr(question_dna.question_dna_service, "list_questions", lambda **kw: bank)
    monkeypatch.setattr(question_rows, "flatten_all", lambda rows: rows)
    monkeypatch.setattr(social, "status", lambda qid, q=None, voice="": {"status": "ready" if int(qid[1:]) < 12 else "none", "scenes": 3})
    monkeypatch.setattr(social, "enqueue", lambda qid, **kw: None)
    monkeypatch.setattr(X, "_plan_post", lambda q, platform, at, by: planned.append(q["question_id"]))
    out = X.book_ahead("grade-9", "Mathematics", today=date(2026, 10, 13), seed=1, days=7, low=5, high=8, ready_only=True)
    assert sorted(planned, key=lambda q: int(q[1:])) == [f"q{i}" for i in range(12)]
    assert out["to_render"] == 0 and "finished videos" in out["notes"][-1]


def test_where_a_post_went_is_kept(monkeypatch):
    from app.infra import db
    from app.services import social_export as X

    seen = []
    monkeypatch.setattr(db, "execute", lambda sql, p=None: seen.append((sql, p)))
    out = X.record_attempt("sp1", ok=True, destinations=["reel", "feed", "story", "Reel", "nonsense"])
    assert out["destinations"] == ["reel", "feed", "story"]
    assert "destinations = CAST(:d AS jsonb)" in seen[0][0] and seen[0][1]["d"] == '["reel", "feed", "story"]'
