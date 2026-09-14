"""Settings from the console, with the environment as the fallback; webhooks signed."""
from __future__ import annotations

import hashlib
import hmac
import json

from app.services import platform_settings as ps
from app.services import webhooks


def _no_db(monkeypatch):
    ps._cache.clear()
    ps._cache_at = 0.0
    monkeypatch.setattr(ps, "_load", lambda: ps._cache)


def test_a_console_value_beats_the_environment_which_beats_the_default(monkeypatch) -> None:
    _no_db(monkeypatch)
    monkeypatch.delenv("PAPER_SERIES_NAME", raising=False)
    assert ps.get("paper_series_name") == "" and ps.source_of("paper_series_name") == "default"

    monkeypatch.setenv("PAPER_SERIES_NAME", "From Env")
    assert ps.get("paper_series_name") == "From Env" and ps.source_of("paper_series_name") == "environment"

    ps._cache["paper_series_name"] = "From Console"
    assert ps.get("paper_series_name") == "From Console" and ps.source_of("paper_series_name") == "console"


def test_values_are_coerced_to_their_kind(monkeypatch) -> None:
    _no_db(monkeypatch)
    ps._cache["log_retention_days"] = "14"
    ps._cache["webhook_events"] = "job.done, paper.frozen"
    assert ps.get("log_retention_days") == 14
    assert ps.get("webhook_events") == ["job.done", "paper.frozen"]
    ps._cache["log_retention_days"] = "not a number"
    assert ps.get("log_retention_days") == 7


def test_the_public_base_url_prefers_the_request_then_the_setting(monkeypatch) -> None:
    _no_db(monkeypatch)
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)

    class Req:
        headers = {"x-forwarded-proto": "https", "x-forwarded-host": "papers.example.co.ke"}

        class url:
            scheme = "http"
            netloc = "10.0.0.5:8000"

    assert ps.public_base_url(Req()) == "https://papers.example.co.ke"
    assert ps.public_base_url() == "http://localhost:8000"
    ps._cache["public_base_url"] = "https://set.example/"
    assert ps.public_base_url() == "https://set.example"


def test_the_secret_is_never_described_in_clear(monkeypatch) -> None:
    _no_db(monkeypatch)
    ps._cache["webhook_secret"] = "hunter2"
    row = next(r for r in ps.describe() if r["key"] == "webhook_secret")
    assert row["value"] == "••••••" and row["source"] == "console"


def test_a_webhook_is_signed_and_only_sent_for_configured_events(monkeypatch) -> None:
    _no_db(monkeypatch)
    ps._cache.update({"webhook_url": "https://hook.example/x", "webhook_secret": "s3cret",
                      "webhook_events": ["paper.frozen"]})
    sent = {}

    def fake_deliver(url, event, body, secret, attempts=3):
        sent.update(url=url, event=event, body=body, secret=secret)
        return {"ok": True, "status": 200, "error": ""}

    monkeypatch.setattr(webhooks, "deliver", fake_deliver)
    assert webhooks.emit("job.done", {"job_id": "j1"}) is False, "not a configured event"
    assert webhooks.emit("paper.frozen", {"exam_id": "e1"}) is True
    import time
    for _ in range(50):
        if sent:
            break
        time.sleep(0.02)
    assert sent["event"] == "paper.frozen"
    payload = json.loads(sent["body"])
    assert payload["payload"] == {"exam_id": "e1"} and payload["event"] == "paper.frozen"
    expected = "sha256=" + hmac.new(b"s3cret", sent["body"], hashlib.sha256).hexdigest()
    assert webhooks.sign("s3cret", sent["body"]) == expected


def test_the_platform_fires_events_where_things_finish() -> None:
    import inspect

    from app.routes import questions
    from app.services import byom, job_queue

    assert '_announce("job.done"' in inspect.getsource(job_queue._execute)
    assert '_announce("job.failed"' in inspect.getsource(job_queue._execute)
    assert 'webhooks.emit("paper.frozen"' in inspect.getsource(questions.freeze_paper_now)
    assert '"agent_task.done"' in inspect.getsource(byom.start)


def test_the_settings_route_is_admin_only() -> None:
    import inspect

    from app.routes import admin_settings

    source = inspect.getsource(admin_settings)
    assert source.count('require_roles("admin")') == 3
