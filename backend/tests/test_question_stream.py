"""Questions arriving as they are produced, not ten minutes later in a heap.

Not token streaming. A batch is one JSON object, so streaming its tokens sends
a reviewer half-written braces; the useful unit is a finished,
structure-checked question. So the run is broken into small calls and each
one's items are emitted as they land.

Three consequences, and all three are the reason: a reviewer starts reading
after one instalment rather than after the whole run; a provider failure at
item forty keeps the thirty-nine already produced and saved; and the items are
better, because one call asked for fifty produces worse questions than six
calls asked for eight.
"""
from __future__ import annotations

import inspect
import json

import pytest

from app.routes import questions


def _events(body) -> list[tuple[str, dict]]:
    """StreamingResponse wraps a sync generator in an async iterator, so the
    chunks are collected through the event loop rather than a for-loop."""
    import asyncio

    async def _collect():
        return [chunk async for chunk in body]

    chunks = asyncio.run(_collect())
    out = []
    for chunk in chunks:
        if isinstance(chunk, bytes):
            chunk = chunk.decode()
        event = data = None
        for line in chunk.strip().split("\n"):
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        out.append((event, data))
    return out


def _batch(n: int, start: int = 0) -> dict:
    return {"questions": [{"question_id": f"q{start + i}", "question_text": "x"}
                          for i in range(n)],
            "rejected": [], "quality_gate": {"overall_score": 88}}


@pytest.fixture
def generated(monkeypatch):
    calls: list[int] = []

    def _fake(payload, _auth):
        calls.append(payload.batch_count)
        start = sum(calls[:-1])
        return _batch(payload.batch_count, start)

    monkeypatch.setattr(questions, "factory_generate_questions_batch", _fake)
    return calls


def test_each_finished_question_is_sent_on_its_own(generated) -> None:
    response = questions.factory_generate_questions_stream(
        grade="grade-9", subject="Mathematics", strand="Numbers",
        sub_strand="Integers", batch_count=3, difficulty=0.65,
        slo_id="", custom_instructions="", auth=object())

    events = _events(response.body_iterator)
    kinds = [e for e, _ in events]

    assert kinds[0] == "start"
    assert kinds.count("question") == 3
    assert kinds[-1] == "done"
    assert [d["n"] for e, d in events if e == "question"] == [1, 2, 3]


def test_it_asks_in_small_instalments_rather_than_all_at_once(generated) -> None:
    """One call for fifty produces worse questions than six calls for eight,
    and nothing can be shown until a call returns."""
    response = questions.factory_generate_questions_stream(
        grade="grade-9", subject="Mathematics", strand="Numbers",
        sub_strand="Integers", batch_count=20, difficulty=0.65,
        slo_id="", custom_instructions="", auth=object())
    _events(response.body_iterator)

    assert questions.STREAM_CHUNK == 8
    assert generated[0] == 8, "an instalment, not the whole run"


def test_the_last_instalment_asks_only_for_what_is_left(generated) -> None:
    response = questions.factory_generate_questions_stream(
        grade="grade-9", subject="Mathematics", strand="Numbers",
        sub_strand="Integers", batch_count=10, difficulty=0.65,
        slo_id="", custom_instructions="", auth=object())
    list(_events(response.body_iterator))

    assert generated == [8, 2], "not 8 and 8, which would overshoot by six"


def test_a_failure_keeps_what_was_already_produced(monkeypatch) -> None:
    """Everything already sent is already saved by the batch that made it."""
    state = {"n": 0}

    def _fake(payload, _auth):
        state["n"] += 1
        if state["n"] > 1:
            raise RuntimeError("provider down")
        return _batch(payload.batch_count)

    monkeypatch.setattr(questions, "factory_generate_questions_batch", _fake)

    response = questions.factory_generate_questions_stream(
        grade="grade-9", subject="Mathematics", strand="Numbers",
        sub_strand="Integers", batch_count=20, difficulty=0.65,
        slo_id="", custom_instructions="", auth=object())
    events = _events(response.body_iterator)

    assert [e for e, _ in events].count("question") == 8
    kind, data = events[-1]
    assert kind == "error"
    assert data["produced"] == 8
    assert "provider down" in data["reason"]


def test_a_chunk_that_returns_nothing_new_stops_the_run(monkeypatch) -> None:
    """Looping on it spends money to stand still."""
    monkeypatch.setattr(questions, "factory_generate_questions_batch",
                        lambda payload, _auth: _batch(2))   # same ids every time

    response = questions.factory_generate_questions_stream(
        grade="grade-9", subject="Mathematics", strand="Numbers",
        sub_strand="Integers", batch_count=50, difficulty=0.65,
        slo_id="", custom_instructions="", auth=object())
    events = _events(response.body_iterator)

    assert [e for e, _ in events].count("question") == 2
    assert events[-1][0] == "error"
    assert "no new items" in events[-1][1]["reason"]


def test_progress_carries_what_the_gate_and_the_repair_did(generated) -> None:
    response = questions.factory_generate_questions_stream(
        grade="grade-9", subject="Mathematics", strand="Numbers",
        sub_strand="Integers", batch_count=8, difficulty=0.65,
        slo_id="", custom_instructions="", auth=object())
    events = _events(response.body_iterator)

    progress = next(d for e, d in events if e == "progress")
    assert progress["produced"] == 8
    assert progress["target"] == 8
    assert progress["gate"] == 88
    assert "rejected" in progress and "repair" in progress


def test_the_response_is_not_buffered_by_the_proxy() -> None:
    """Nginx buffers a response body by default, which holds every instalment
    until the whole run finishes — exactly what this exists to avoid."""
    source = inspect.getsource(questions.factory_generate_questions_stream)

    assert '"X-Accel-Buffering": "no"' in source
    assert 'media_type="text/event-stream"' in source


# ── the console ─────────────────────────────────────────────────────────────


def test_the_panel_reads_the_stream_itself_rather_than_using_eventsource() -> None:
    """`EventSource` cannot carry an Authorization header. Reading the stream
    with fetch also makes the run stoppable: aborting ends the generation
    rather than leaving it spending money into a page nobody is watching."""
    from pathlib import Path

    frontend = Path(__file__).resolve().parents[2] / "frontend-web"
    panel = " ".join((frontend / "src/ui/QuestionStream.tsx").read_text().split())

    # The component's own comment names EventSource to say why it is not used,
    # so what matters is that it is never constructed.
    assert "new EventSource(" not in panel
    assert "AbortController" in panel
    assert "Authorization: `Bearer ${token}`" in panel
    # A partial frame has to survive until the rest of it arrives.
    assert "const frames = buffer.split" in panel
    assert "buffer = frames.pop()" in panel


def test_leaving_the_screen_stops_the_run() -> None:
    from pathlib import Path

    frontend = Path(__file__).resolve().parents[2] / "frontend-web"
    panel = " ".join((frontend / "src/ui/QuestionStream.tsx").read_text().split())

    assert "React.useEffect(() => () => abort.current?.abort(), [])" in panel
    assert "stopping keeps what has arrived" in panel
