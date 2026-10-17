"""The poster on a Mac keeps going when the server is slow: it tries again,
and a post's result that cannot be sent is kept and sent later — a post the
server never hears of would be posted twice."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "poster"))
from poster import cbc, config  # noqa: E402


class Flaky:
    """An httpx.AsyncClient whose first `fail` requests time out."""
    calls: list[str] = []
    fail = 0

    def __init__(self, *a, **k): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False

    async def request(self, method, url, **kw):
        Flaky.calls.append(url)
        if len(Flaky.calls) <= Flaky.fail:
            raise httpx.ConnectTimeout("slow")
        return httpx.Response(200, json={"command": None, "post": None}, request=httpx.Request(method, url))


@pytest.fixture(autouse=True)
def flaky(monkeypatch, tmp_path):
    Flaky.calls, Flaky.fail = [], 0
    monkeypatch.setattr(cbc.httpx, "AsyncClient", Flaky)
    monkeypatch.setattr(cbc, "WAITS", (0, 0, 0, 0))
    monkeypatch.setattr(config, "SHOTS_DIR", str(tmp_path / "shots"))
    monkeypatch.setattr(config, "CBC_API_URL", "https://cbc.example")
    return Flaky


def test_a_timeout_is_tried_again_until_the_server_answers() -> None:
    Flaky.fail = 3
    out = asyncio.run(cbc.next_post(platform="facebook", dry=True, share="feed"))
    assert out == {"command": None, "post": None} and len(Flaky.calls) == 4


def test_it_gives_up_after_the_last_wait() -> None:
    Flaky.fail = 99
    with pytest.raises(httpx.ConnectTimeout):
        asyncio.run(cbc.next_post(platform="facebook"))
    assert len(Flaky.calls) == 5


def test_a_result_that_cannot_be_sent_is_kept_and_sent_later() -> None:
    Flaky.fail = 99
    asyncio.run(cbc.report("sp_1", ok=True))                 # posted, but the server is not answering
    assert [b["post_id"] for b in cbc._unsent()] == ["sp_1"]
    Flaky.calls, Flaky.fail = [], 0
    assert asyncio.run(cbc.send_unsent()) == 1
    assert cbc._unsent() == [] and Flaky.calls[0].endswith("/api/v1/play/poster/result")


def test_every_command_says_how_it_went_in_the_log() -> None:
    import inspect

    from poster import __main__ as main

    source = inspect.getsource(main.command_loop)
    assert 'log.info("Command %s done: %s"' in source
    assert "cbc.send_unsent()" in inspect.getsource(main.checkin_loop)


def test_a_post_is_looked_for_by_the_questions_words_and_the_contexts() -> None:
    from poster.flows import fb_comments as fc

    got = fc.needles("Examine and evaluate the following expression: (∛−1000 × (−4))",
                     ["Examine and evaluate a combined expression with directed numbers."])
    assert got[0] == "examine and evaluate the following expre" and len(got) == 2
    assert fc.needles("2 + 3?", []) == [], "too short to tell one post from another"
    assert "See more" in fc._EXPAND and "data-cbc-post" in fc._MARK
