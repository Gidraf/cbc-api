"""One button ingests every grade's dataset and builds the structure behind it."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.routes import admin_langfuse as al
from app.routes import curriculum as cur
from app.services import dataset_ingest as di
from app.services import dataset_watch as dw
from app.services import job_queue


class _Queue:
    def __init__(self):
        self.jobs: list[tuple[str, str, str, dict]] = []
        self.started = 0

    def enqueue(self, kind, grade, subject, payload, **_):
        self.jobs.append((kind, grade, subject, dict(payload)))
        return SimpleNamespace(job_id=f"job_{len(self.jobs)}")

    def start_worker(self):
        self.started += 1
        return True


@pytest.fixture
def queue(monkeypatch):
    q = _Queue()
    monkeypatch.setattr(job_queue, "enqueue", q.enqueue)
    monkeypatch.setattr(job_queue, "start_worker", q.start_worker)
    return q


def _auth():
    return SimpleNamespace(subject="ops@example.com", role="admin", auth_type="session")


def _status_rows(rows_by_grade):
    def fetch_all(sql, params=None):
        if "dataset_ingest_status" in sql:
            return list(rows_by_grade.get((params or {}).get("grade"), []))
        return []
    return fetch_all


def test_every_grade_is_synced_and_every_unfinished_document_queued(queue, monkeypatch):
    from app.infra import db
    from app.services import dataset_ingest as di
    from app.services.grade_order import GRADE_SEQUENCE

    synced = []
    monkeypatch.setattr(di, "sync_grade", lambda g: synced.append(g) or {"new": 1})
    rows = {
        "grade-7": [
            {"item_id": "m7", "status": "pending", "resolved_subject": "Mathematics", "declared_subject": "", "title": "Maths"},
            {"item_id": "e7", "status": "ingested", "resolved_subject": "English", "declared_subject": "", "title": "English"},
            {"item_id": "s7", "status": "failed", "resolved_subject": "", "declared_subject": "Science", "title": "Sci"},
            {"item_id": "k7", "status": "processing", "resolved_subject": "Kiswahili", "declared_subject": "", "title": "Kis"},
        ],
        "grade-9": [
            {"item_id": "m9", "status": "pending", "resolved_subject": "Mathematics", "declared_subject": "", "title": "Maths"},
        ],
    }
    monkeypatch.setattr(db, "fetch_all", _status_rows(rows))

    out = al.ingest_everything(al.IngestEverythingRequest(), auth=_auth())

    assert synced == [slug for slug, _, _ in GRADE_SEQUENCE]
    assert out["queued"] == 3 and out["skipped"] == 2
    kinds = {(g, p["item_id"]) for _, g, _, p in queue.jobs}
    assert kinds == {("grade-7", "m7"), ("grade-7", "s7"), ("grade-9", "m9")}
    # Each document carries the follow-up flag so the worker builds the spine.
    assert all(p["then_structure"] and not p["force"] for _, _, _, p in queue.jobs)
    # The failed one is queued under its declared subject since nothing resolved.
    assert ("dataset_item", "grade-7", "Science") in {(k, g, s) for k, g, s, _ in queue.jobs}
    assert queue.started == 1


def test_force_requeues_the_ingested_documents_too(queue, monkeypatch):
    from app.infra import db
    from app.services import dataset_ingest as di

    monkeypatch.setattr(di, "sync_grade", lambda g: {})
    rows = {"grade-7": [
        {"item_id": "e7", "status": "ingested", "resolved_subject": "English", "declared_subject": "", "title": "English"},
    ]}
    monkeypatch.setattr(db, "fetch_all", _status_rows(rows))

    out = al.ingest_everything(al.IngestEverythingRequest(force=True), auth=_auth())
    assert out["queued"] == 1 and queue.jobs[0][3]["force"] is True


def test_a_grade_whose_sync_fails_does_not_stop_the_others(queue, monkeypatch):
    from app.infra import db
    from app.services import dataset_ingest as di

    def sync(g):
        if g == "grade-pp1":
            raise RuntimeError("Langfuse unreachable")
        return {}
    monkeypatch.setattr(di, "sync_grade", sync)
    rows = {"grade-9": [
        {"item_id": "m9", "status": "pending", "resolved_subject": "Mathematics", "declared_subject": "", "title": "M"},
    ]}
    monkeypatch.setattr(db, "fetch_all", _status_rows(rows))

    out = al.ingest_everything(al.IngestEverythingRequest(), auth=_auth())
    assert out["synced"]["grade-pp1"]["error"].startswith("Langfuse unreachable")
    assert out["queued"] == 1


def test_nothing_to_do_does_not_start_the_worker(queue, monkeypatch):
    from app.infra import db
    from app.services import dataset_ingest as di

    monkeypatch.setattr(di, "sync_grade", lambda g: {})
    monkeypatch.setattr(db, "fetch_all", _status_rows({}))
    out = al.ingest_everything(al.IngestEverythingRequest(), auth=_auth())
    assert out["queued"] == 0 and queue.started == 0


def test_missing_structure_is_queued_as_a_strands_then_substrands_pipeline(queue, monkeypatch):
    monkeypatch.setattr(dw, "missing_structure", lambda grade="", subject="": [
        {"grade": "grade-7", "subject": "Mathematics", "needs": "strands", "strands": []}])

    out = al.structure_everything(_auth())
    assert out["queued"] == 1
    kind, grade, subject, payload = queue.jobs[0]
    assert (kind, grade, subject) == ("pipeline", "grade-7", "Mathematics")
    assert payload["steps"] == ["strands", "substrands"] and payload["index"] == 0
    assert payload["auto_save"] is True, "saved as it goes — nobody is at the console to accept sixteen subjects"
    assert queue.started == 1


def test_an_ingested_document_queues_the_spine_for_bare_learning_areas(queue, monkeypatch):
    calls = []
    monkeypatch.setattr(di, "process_item", lambda item_id, force=False: calls.append((item_id, force)) or {"ok": True})
    monkeypatch.setattr(dw, "queue_missing_structure",
                        lambda grade="", subject="": [{"grade": grade, "subject": "Mathematics", "job_id": "job_x"}])

    out = cur._run_queued_dataset_item(
        {"grade": "grade-7", "payload": {"item_id": "m7", "then_structure": True}}
    )
    assert calls == [("m7", False)]
    assert out["structure_queued"] == [{"grade": "grade-7", "subject": "Mathematics", "job_id": "job_x"}]


def test_without_the_flag_the_document_is_ingested_and_nothing_follows(queue, monkeypatch):
    monkeypatch.setattr(di, "process_item", lambda item_id, force=False: {"ok": True})
    followed = []
    monkeypatch.setattr(dw, "queue_missing_structure", lambda **kw: followed.append(kw) or [])
    out = cur._run_queued_dataset_item({"grade": "grade-7", "payload": {"item_id": "m7"}})
    assert out == {"ok": True} and followed == []


# ── The watch ────────────────────────────────────────────────────────────────

@pytest.fixture
def settings(monkeypatch):
    from app.services import platform_settings as ps

    store = {"auto_ingest_enabled": False, "auto_ingest_interval_minutes": 30}
    monkeypatch.setattr(ps, "get", lambda key, default=None: store.get(key, default))
    monkeypatch.setattr(dw, "_last", {"at": 0.0, "result": None, "error": "", "trigger": ""})
    return store


def test_the_watch_does_nothing_while_the_setting_is_off(settings, monkeypatch):
    ran = []
    monkeypatch.setattr(dw, "run_pass", lambda **kw: ran.append(kw) or {"queued": 0})
    assert dw.tick() is None and ran == []
    assert dw.status()["enabled"] is False and dw.status()["next_run_in_seconds"] is None


def test_the_watch_runs_the_pass_when_on_and_then_waits_the_interval(settings, monkeypatch):
    settings["auto_ingest_enabled"] = True
    ran = []

    def pass_(**kw):
        ran.append(kw)
        dw._last.update(at=__import__("time").time(), result={"queued": 2, "skipped": 1})
        return {"queued": 2, "skipped": 1}
    monkeypatch.setattr(dw, "run_pass", pass_)

    assert dw.tick() == {"queued": 2, "skipped": 1}
    assert ran[0]["trigger"] == "schedule"
    # Not again until thirty minutes have passed.
    assert dw.tick() is None and len(ran) == 1
    st = dw.status()
    assert st["enabled"] and st["last_queued"] == 2 and 0 < st["next_run_in_seconds"] <= 1800


def test_a_langfuse_outage_is_recorded_and_the_watch_survives(settings, monkeypatch):
    settings["auto_ingest_enabled"] = True

    def boom(**kw):
        raise RuntimeError("Langfuse unreachable")
    monkeypatch.setattr(dw, "run_pass", boom)
    assert dw.tick() is None
    assert dw.status()["last_error"].startswith("Langfuse unreachable")
    # And it backs off for the interval rather than hammering.
    assert dw.tick() is None


def test_interval_never_drops_below_five_minutes(settings):
    settings["auto_ingest_interval_minutes"] = 1
    assert dw.interval_seconds() == 300


def test_console_toggle_writes_the_setting_and_starts_the_watch(monkeypatch):
    from app.services import platform_settings as ps

    written = {}
    monkeypatch.setattr(ps, "set_many", lambda values, updated_by="": written.update(values) or values)
    started = []
    monkeypatch.setattr(dw, "start", lambda: started.append(True) or True)
    monkeypatch.setattr(dw, "status", lambda: {"enabled": True})

    out = al.set_auto_ingest(al.AutoIngestRequest(enabled=True, interval_minutes=2), auth=_auth())
    assert written == {"auto_ingest_enabled": "true", "auto_ingest_interval_minutes": 5}
    assert started == [True] and out == {"enabled": True}


# ── Controls ─────────────────────────────────────────────────────────────────
#
# A small jobs table in memory. The controls are SQL over `jobs` and
# `dataset_ingest_status`, so the double answers the handful of shapes they
# send rather than parsing SQL.

class _Jobs:
    def __init__(self, jobs):
        self.jobs = {j["job_id"]: dict(j) for j in jobs}
        self.released: list[str] = []
        self.started = 0

    def _ours(self, j):
        return j["kind"] == "dataset_item" or (
            j["kind"] == "pipeline" and j.get("queued_by") == "datasets")

    def _match(self, sql, params, j):
        if not self._ours(j):
            return False
        # Only the WHERE clause says which rows; the SET clause names the new status.
        sql = sql.split("WHERE", 1)[-1]
        if "status = 'queued'" in sql:
            ok = j["status"] == "queued"
        elif "status = 'paused'" in sql:
            ok = j["status"] == "paused"
        elif "status IN ('queued', 'paused')" in sql:
            ok = j["status"] in ("queued", "paused")
        elif "status = 'running'" in sql:
            ok = j["status"] == "running"
        else:
            ok = True
        if "job_id = :job_id" in sql:
            ok = ok and j["job_id"] == params["job_id"]
        if "payload->>'item_id' = :item_id" in sql:
            ok = ok and j["payload"].get("item_id") == params["item_id"]
        if "REPLACE(LOWER(grade)" in sql and "grade" in (params or {}):
            ok = ok and j["grade"] == params["grade"]
        return ok

    def fetch_one(self, sql, params=None):
        params = params or {}
        if "COUNT(*) AS n" in sql:
            return {"n": sum(1 for j in self.jobs.values() if self._match(sql, params, j))}
        hits = [j for j in self.jobs.values() if self._match(sql, params, j)]
        return hits[0] if hits else None

    def fetch_all(self, sql, params=None):
        params = params or {}
        if "dataset_ingest_status GROUP BY" in sql:
            return [{"grade": "grade-7", "status": "ingested", "n": 3},
                    {"grade": "grade-7", "status": "pending", "n": 1},
                    {"grade": "grade-9", "status": "ingested", "n": 4}]
        if "GROUP BY grade, status" in sql:
            return []
        if "GROUP BY status" in sql:
            counts = {}
            for j in self.jobs.values():
                if self._ours(j):
                    counts[j["status"]] = counts.get(j["status"], 0) + 1
            return [{"status": s, "n": n} for s, n in counts.items()]
        return [j for j in self.jobs.values() if self._match(sql, params, j)]

    def execute(self, sql, params=None):
        params = params or {}
        if "UPDATE dataset_ingest_status" in sql:
            self.released.append(sql)
            return
        new = "paused" if "SET status = 'paused'" in sql else (
            "queued" if "SET status = 'queued'" in sql else "cancelled")
        for j in self.jobs.values():
            if self._match(sql, params, j):
                j["status"] = new


@pytest.fixture
def jobs(monkeypatch):
    from app.infra import db

    table = _Jobs([
        {"job_id": "j1", "kind": "dataset_item", "grade": "grade-7", "subject": "Mathematics",
         "status": "running", "payload": {"item_id": "m7"}, "queued_by": "datasets"},
        {"job_id": "j2", "kind": "dataset_item", "grade": "grade-7", "subject": "English",
         "status": "queued", "payload": {"item_id": "e7"}, "queued_by": "datasets"},
        {"job_id": "j3", "kind": "dataset_item", "grade": "grade-9", "subject": "Mathematics",
         "status": "queued", "payload": {"item_id": "m9"}, "queued_by": "datasets"},
        {"job_id": "j4", "kind": "pipeline", "grade": "grade-7", "subject": "Science",
         "status": "queued", "payload": {"steps": ["strands", "substrands"]}, "queued_by": "datasets"},
        # Somebody else's work: never touched by the ingest controls.
        {"job_id": "j5", "kind": "notes", "grade": "grade-7", "subject": "Mathematics",
         "status": "queued", "payload": {}, "queued_by": "ops"},
    ])
    monkeypatch.setattr(db, "fetch_one", table.fetch_one)
    monkeypatch.setattr(db, "fetch_all", table.fetch_all)
    monkeypatch.setattr(db, "execute", table.execute)
    monkeypatch.setattr(job_queue, "start_worker", lambda: table.__setattr__("started", table.started + 1) or True)
    return table


def _statuses(table):
    return {k: v["status"] for k, v in table.jobs.items()}


def test_pause_holds_what_waits_and_leaves_the_running_document_alone(jobs):
    assert dw.pause() == 3
    assert _statuses(jobs) == {"j1": "running", "j2": "paused", "j3": "paused",
                               "j4": "paused", "j5": "queued"}
    assert dw.resume() == 3 and jobs.started == 1
    assert _statuses(jobs)["j2"] == "queued"


def test_skip_drops_one_document_by_item_or_a_whole_grade(jobs):
    assert dw.skip(item_id="e7") == 1
    assert _statuses(jobs)["j2"] == "cancelled" and _statuses(jobs)["j3"] == "queued"
    assert jobs.released, "the document goes back to Not processed"
    assert dw.skip(grade="grade-9") == 1
    assert _statuses(jobs)["j3"] == "cancelled"


def test_stop_cancels_every_waiting_ingest_job_but_nobody_elses(jobs):
    dw.pause()
    assert dw.stop() == 3
    assert _statuses(jobs) == {"j1": "running", "j2": "cancelled", "j3": "cancelled",
                               "j4": "cancelled", "j5": "queued"}


def test_progress_reports_grades_jobs_and_the_current_document(jobs, monkeypatch):
    monkeypatch.setattr(dw, "status", lambda: {"enabled": False})
    p = dw.progress()
    by_grade = {g["grade"]: g for g in p["grades"]}
    assert by_grade["grade-7"]["counts"]["ingested"] == 3 and by_grade["grade-7"]["total"] == 4
    assert p["total"] == 8 and p["ingested"] == 7 and p["percentage"] == 88
    assert p["jobs"] == {"running": 1, "queued": 3}
    assert p["active"] and not p["paused"]
    assert p["current"]["job_id"] == "j1"
    assert [w["job_id"] for w in p["waiting"]] == ["j2", "j3", "j4"]
    dw.pause()
    assert dw.progress()["paused"] is True


def test_control_route_validates_the_action_and_skip_needs_a_target(jobs, monkeypatch):
    from app.errors import ApiError

    monkeypatch.setattr(dw, "status", lambda: {"enabled": False})
    with pytest.raises(ApiError):
        al.ingest_control(al.IngestControlRequest(action="dance"), _auth())
    with pytest.raises(ApiError):
        al.ingest_control(al.IngestControlRequest(action="skip"), _auth())
    out = al.ingest_control(al.IngestControlRequest(action="pause"), _auth())
    assert out["action"] == "pause" and out["affected"] == 3 and out["paused"]


def test_uningest_everything_needs_the_word_then_undoes_every_grade(jobs, monkeypatch):
    from app.errors import ApiError
    from app.infra import db

    with pytest.raises(ApiError):
        al.uningest_everything(al.UningestEverythingRequest(confirm="yes"), _auth())

    real_fetch_all = db.fetch_all

    def fetch_all(sql, params=None):
        if "WHERE status IN (:ingested, :failed)" in sql:
            return [{"item_id": "m7", "grade": "grade-7", "status": "ingested"},
                    {"item_id": "s6", "grade": "grade-6", "status": "failed"}]
        return real_fetch_all(sql, params)
    monkeypatch.setattr(db, "fetch_all", fetch_all)
    undone = []
    monkeypatch.setattr(di, "uningest_item",
                        lambda item_id, purge_generated=False: undone.append((item_id, purge_generated))
                        or {"removed": {"design": 1, "substrands": 5}})
    monkeypatch.setattr(di, "purge_orphaned_designs",
                        lambda slug: {"designs": 1, "substrands": 2} if slug == "grade-4" else {})

    out = al.uningest_everything(
        al.UningestEverythingRequest(confirm="everything", purge_generated=True), _auth())
    assert out["stopped"] == 3, "waiting jobs are cancelled before the undo"
    assert undone == [("m7", True), ("s6", True)]
    assert out["uningested"] == 2 and out["failed"] == 0
    assert out["removed"] == {"design": 3, "substrands": 12}
    assert out["orphans_purged"] == {"grade-4": {"designs": 1, "substrands": 2}}


def test_fixed_dataset_paths_are_matched_before_the_grade_route():
    """`/datasets/{grade}` declared first would read 'progress' as a grade."""
    from app.main import app

    seen_grade = False
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set()) or set()
        if path.endswith("/langfuse/datasets/{grade}") and "GET" in methods:
            seen_grade = True
        if path.endswith(("/datasets/progress", "/datasets/auto-ingest")) and "GET" in methods:
            assert not seen_grade, f"{path} is declared after /datasets/{{grade}}"
