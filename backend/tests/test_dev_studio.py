"""The developer studio: an idea built into an app on the CBC API, filmed,
written up and queued for LinkedIn. The model is stubbed; the database is a
real, empty Postgres (CBC_TEST_PHASE2_DATABASE_URL)."""
from __future__ import annotations

import os

import pytest

from app.services import dev_studio as ds

DB = os.getenv("CBC_TEST_PHASE2_DATABASE_URL", "")
needs_db = pytest.mark.skipif(not DB, reason="set CBC_TEST_PHASE2_DATABASE_URL to an empty Postgres database")

PLAN = {"title": "Quiz Sprint", "pitch": "A quick quiz.", "walkthrough": "It loads questions and scores them.",
        "architecture": {"nodes": [{"id": "ui", "label": "Page", "kind": "ui"}, {"id": "api", "label": "CBC API", "kind": "api"}],
                         "edges": [{"from": "ui", "to": "api", "label": "fetch"}]},
        "data_flow": ["The page asks the API."], "files": [{"path": "index.html"}, {"path": "app.js"}, {"path": "tests.js"}],
        "demo": [], "episodes": [{"title": "Architecture", "say_intro": "How it fits.", "file": "app.js", "lines": "2-3",
                                  "explain": "One fetch."}], "sample": "fetch('./cbc/questions')", "hook": "Build a quiz"}
FILES = {"index.html": "<html><head></head><body><h1>Quiz</h1></body></html>",
         "app.js": "// one\nconst a = 1;\nconst b = 2;\nconst c = 3;", "tests.js": "test('t', () => assert(true));"}


@pytest.fixture()
def db(monkeypatch):
    from sqlalchemy import create_engine, text

    from app.infra import db as infra
    from app.services import platform_settings

    engine = create_engine(DB)
    with engine.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    monkeypatch.setattr(infra, "get_engine", lambda: engine)
    monkeypatch.setattr(platform_settings, "_load", lambda: {})
    infra.run_migrations()
    yield
    engine.dispose()


def test_the_plan_always_has_a_page_and_its_tests_and_never_too_many_files(monkeypatch) -> None:
    monkeypatch.setattr(ds, "_ask", lambda row, prompt, system="": {
        "title": "T", "files": [{"path": "app.js"}, {"path": "../etc/passwd"}] + [{"path": f"f{k}.js"} for k in range(9)]})
    p = ds.plan({"idea": "x", "category": "games"})
    paths = [f["path"] for f in p["files"]]
    assert paths[0] == "index.html" and "../etc/passwd" not in paths and len(paths) <= ds.MAX_FILES


def test_the_code_on_screen_is_the_lines_the_episode_names() -> None:
    code, _ = ds._code_window(FILES, "app.js", "2-3")
    assert code == "const a = 1;\nconst b = 2;"


def test_an_episode_is_the_architecture_its_code_and_the_app_working_and_the_intro_comes_last() -> None:
    row = {"project_id": "dp-0123456789", "plan": PLAN, "files": FILES,
           "shots": [{"before": "AAAA", "after": "AAAA", "box": [1, 2, 3, 4], "say": "Press start."}],
           "urls": {"app": "https://x/p/dp-0123456789/"}}
    kinds = [s["scene"] for s in ds.episode_scenes(row, 0)]
    assert kinds == ["title", "arch", "code", "screen"]
    intro = ds._intro(row, {"website": "x"})
    assert intro["scene"] == "outro" and intro["name"] == "Quiz Sprint" and "x/p/dp-0123456789/" in intro["website"]


def test_each_project_has_its_own_voice_from_a_developer_set() -> None:
    voices = {ds.voice_for(f"dp-{n:010x}") for n in range(40)}
    assert len(voices) > 4 and voices <= set(ds.DEV_VOICES)


def test_the_book_has_the_idea_the_architecture_the_tests_and_every_file() -> None:
    page = ds.book_html({"project_id": "dp-0123456789", "idea": "x", "category": "games", "plan": PLAN, "files": FILES,
                         "tests": {"tests": [{"name": "scores", "ok": True}]}, "shots": [], "urls": {"app": "https://x/p/1/"}})
    for want in ("Quiz Sprint", "<svg", "The page asks the API.", "✔ scores", "app.js", "const b = 2;", "@page{size:A5"):
        assert want in page


def test_only_a_projects_own_files_are_served() -> None:
    assert ds.served_file("dp-0123456789", "../../secrets") is None
    assert ds.served_file("not-a-project", "index.html") is None


def test_the_test_link_is_sandboxed_away_from_the_console(monkeypatch) -> None:
    from app.routes import dev_studio as routes

    monkeypatch.setattr(ds, "served_file", lambda pid, path: (b"<html></html>", "text/html"))
    r = routes.demo_file("dp-0123456789", "index.html")
    assert "sandbox allow-scripts" in r.headers["content-security-policy"]


@needs_db
def test_a_project_is_queued_then_its_posts_go_to_linkedin_one_at_a_time(db, monkeypatch) -> None:
    from app.infra.db import execute
    from app.services import job_queue

    class Job:
        job_id = "j1"

    monkeypatch.setattr(job_queue, "enqueue", lambda *a, **k: Job())
    monkeypatch.setattr(job_queue, "dispatch", lambda job_id: None)
    made = ds.create("", category="games", by="admin")
    assert made["idea"] in ds.IDEAS["games"] and ds.one(made["project_id"])["status"] == "queued"
    ds._save(made["project_id"], plan=PLAN, urls={"app": "https://x/p/", "book": "https://x/book.pdf",
                                                  "shorts": [{"title": "Ep 1", "url": "https://x/1.mp4"}],
                                                  "long": {"url": "https://x/long.mp4"}})
    assert ds.queue_linkedin(made["project_id"]) == 3
    first = ds.linkedin_next()
    assert first["kind"] == "document" and "https://x/p/" in first["body"]
    ds.linkedin_done(first["post_id"], True, url="https://linkedin/1")
    assert ds.linkedin_next()["kind"] == "video"
    for _ in range(3):
        nxt = ds.linkedin_next()
        if nxt:
            ds.linkedin_done(nxt["post_id"], False, error="no")
    execute("SELECT 1")
