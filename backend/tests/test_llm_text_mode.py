"""Asking a model for an SVG and being able to accept one.

    The model failed: SCHEMA_VALIDATION_FAILED: The model did not return JSON.
    It began: '<svg viewBox="0 0 800 600" ...'

The station's own instruction is "Return ONLY the <svg> element". The model did
exactly that, and the client rejected it — because `generate` parsed every
response as JSON, whatever had been asked for.
"""
from __future__ import annotations

import inspect

import pytest

from app.services.llm_client import LlmClient, _strip_fence
from app.services.provider_router import ResolvedModelConfig

SVG = ('<svg viewBox="0 0 800 600" xmlns="http://www.w3.org/2000/svg">'
       '<g data-part-id="part-addition" id="part-addition">'
       '<text x="50" y="50">Addition</text></g></svg>')

CONFIG = ResolvedModelConfig(
    pipeline_stage="diagram_generation", provider="openai",
    model="gpt-4o-mini", resolved_base_url="", credential_ref_id="c", api_key="k")


@pytest.fixture()
def answering(monkeypatch):
    def reply(text: str) -> LlmClient:
        client = LlmClient()
        client._call_openai_compatible = lambda *a, **k: (text, {"total_tokens": 10})
        import app.services.run_meter as meter
        monkeypatch.setattr(meter, "add", lambda *a, **k: None)
        return client
    return reply


def test_an_svg_is_rejected_as_json(answering) -> None:
    """The failure, kept: this is what the station saw."""
    from app.errors import ApiError

    with pytest.raises(ApiError) as raised:
        answering(SVG).generate(CONFIG, [{"role": "user", "content": "draw"}])

    assert raised.value.code == "SCHEMA_VALIDATION_FAILED"


def test_an_svg_comes_back_whole_when_text_is_asked_for(answering) -> None:
    out = answering(SVG).generate(
        CONFIG, [{"role": "user", "content": "draw"}], expect="text")

    assert isinstance(out.content, str)
    assert out.content.startswith("<svg")
    assert "part-addition" in out.content


def test_json_is_still_the_default(answering) -> None:
    out = answering('{"a": 1}').generate(CONFIG, [{"role": "user", "content": "x"}])
    assert out.content == {"a": 1}


def test_usage_is_still_metered_in_text_mode(answering) -> None:
    """Text mode must not become a way to spend money unmetered."""
    source = inspect.getsource(LlmClient.generate)
    meter_at = source.index("_meter(usage")
    parse_at = source.index("expect != \"text\"")
    assert meter_at < parse_at, "metered before the response is interpreted"


# ── the fence a model adds anyway ───────────────────────────────────────────

@pytest.mark.parametrize("raw, expected", [
    ("```svg\n<svg id='a'/>\n```", "<svg id='a'/>"),
    ("```\n<svg id='a'/>\n```", "<svg id='a'/>"),
    ("<svg id='a'/>", "<svg id='a'/>"),
    ("<think>hmm</think>\n<svg id='a'/>", "<svg id='a'/>"),
    ("   <svg id='a'/>   ", "<svg id='a'/>"),
])
def test_a_fenced_answer_is_unwrapped(raw: str, expected: str) -> None:
    """Asked for an SVG and nothing else, a model still answers "```svg" often
    enough that this is the difference between a station that works and one
    that fails on the model's habits."""
    assert _strip_fence(raw) == expected


# ── the stations that ask for one ───────────────────────────────────────────

@pytest.mark.parametrize("name", ["factory_draw_visual", "factory_generate_asset"])
def test_every_route_that_asks_for_an_svg_asks_for_text(name: str) -> None:
    from app.routes import curriculum

    source = inspect.getsource(getattr(curriculum, name))
    assert 'expect="text"' in source, name
    assert "extract_and_sanitize_svg" in source, "and still sanitises it"


def test_the_drawn_svg_survives_sanitising() -> None:
    from app.services.diagram_dedup import extract_and_sanitize_svg

    cleaned = extract_and_sanitize_svg(SVG)

    assert cleaned
    assert "part-addition" in cleaned, "the occludable marker must survive"
