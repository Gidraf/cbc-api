"""A reasoning model is asked through the Responses API, in its own shape.

The client posted every OpenAI call to /chat/completions with `temperature`,
`top_p` and `max_tokens`. GPT-5-family models reject those outright, and the
newest of them are served through /responses — `input`, `reasoning.effort`,
`text.format`, `max_output_tokens` — so a stage bound to one of them failed on
every call. The operator's own working sample:

    client.responses.create(model="gpt-5.6-sol",
                            reasoning={"effort": "high"}, input=...)
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.services import llm_client as lc
from app.services.provider_router import ResolvedModelConfig

REASONING = ResolvedModelConfig(
    pipeline_stage="notes_generation", provider="openai", model="gpt-5.6-sol",
    resolved_base_url="https://api.openai.com/v1", credential_ref_id="c", api_key="k")
CHAT = ResolvedModelConfig(
    pipeline_stage="notes_generation", provider="openai", model="gpt-4o",
    resolved_base_url="https://api.openai.com/v1", credential_ref_id="c", api_key="k")

MESSAGES = [{"role": "system", "content": "You write guides."},
            {"role": "user", "content": "Write lesson 1."}]

RESPONSES_BODY = {
    "id": "resp_1", "status": "completed",
    "output": [
        {"type": "reasoning", "summary": []},
        {"type": "message", "role": "assistant",
         "content": [{"type": "output_text", "text": '{"title": "Integers"}'}]},
    ],
    "usage": {"input_tokens": 120, "output_tokens": 900, "total_tokens": 1020},
}


@pytest.fixture()
def posted(monkeypatch):
    """Capture the request; answer with a canned body."""
    calls: list[dict] = []
    body = {"value": RESPONSES_BODY}

    class FakeClient:
        def __init__(self, *a, **k): ...
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, url, headers=None, json=None):
            calls.append({"url": url, "json": json, "headers": headers})
            return httpx.Response(200, json=body["value"],
                                  request=httpx.Request("POST", url))

    monkeypatch.setattr(lc.httpx, "Client", FakeClient)
    import app.services.run_meter as meter
    monkeypatch.setattr(meter, "add", lambda *a, **k: None)
    calls.append(body)  # sentinel so tests can swap the body
    return calls


def test_a_reasoning_model_is_asked_through_responses(posted) -> None:
    out = lc.LlmClient().generate(REASONING, MESSAGES)

    call = posted[-1] if "url" in posted[-1] else posted[1]
    assert call["url"].endswith("/responses")
    payload = call["json"]
    assert payload["model"] == "gpt-5.6-sol"
    assert payload["input"] == MESSAGES
    assert payload["reasoning"] == {"effort": lc.openai_payload("gpt-5.6-sol", [], 0, 1)["reasoning"]["effort"]}
    assert payload["text"] == {"format": {"type": "json_object"}}
    assert "temperature" not in payload and "max_tokens" not in payload
    assert payload["max_output_tokens"] >= 16000
    assert out.content == {"title": "Integers"}
    assert out.usage.prompt_tokens == 120 and out.usage.completion_tokens == 900


def test_a_chat_model_still_goes_through_chat_completions(posted) -> None:
    posted[0]["value"] = {
        "choices": [{"message": {"content": '{"title": "Integers"}'}}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12}}

    lc.LlmClient().generate(CHAT, MESSAGES)

    call = posted[-1]
    assert call["url"].endswith("/chat/completions")
    assert call["json"]["temperature"] == 0.2 and call["json"]["max_tokens"] == 8192


def test_the_text_is_read_out_of_the_output_list() -> None:
    assert lc.responses_output_text(RESPONSES_BODY) == '{"title": "Integers"}'
    assert lc.responses_output_text({"output_text": "x"}) == "x"
    assert lc.responses_output_text({"output": [{"type": "reasoning"}]}) == ""


def test_thinking_that_eats_the_whole_budget_is_a_named_error(posted) -> None:
    """An `incomplete` response with no message is not "the model returned
    no JSON" — it is the reasoning budget, and the fix is a setting."""
    posted[0]["value"] = {"status": "incomplete",
                          "incomplete_details": {"reason": "max_output_tokens"},
                          "output": [{"type": "reasoning"}], "usage": {}}

    with pytest.raises(Exception) as caught:
        lc.LlmClient().generate(REASONING, MESSAGES)
    assert "OPENAI_REASONING_EFFORT" in str(caught.value) or "reasoning" in str(caught.value).lower()


def test_the_shipped_defaults_are_the_5_6_tiers() -> None:
    import os
    from app.settings import Settings
    saved = {k: os.environ.pop(k, None) for k in
             ("OPENAI_DEFAULT_MODEL", "OPENAI_LIGHT_MODEL",
              "OPENAI_REASONING_EFFORT", "OPENAI_LIGHT_REASONING_EFFORT")}
    try:
        fresh = Settings()
        assert fresh.openai_default_model == "gpt-5.6-terra"
        assert fresh.openai_light_model == "gpt-5.6-luna"
        assert fresh.openai_reasoning_effort == "medium"
        assert fresh.openai_light_reasoning_effort == "low"
    finally:
        for k, val in saved.items():
            if val is not None:
                os.environ[k] = val
