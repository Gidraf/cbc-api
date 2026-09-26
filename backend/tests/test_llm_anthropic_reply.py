"""Reading a Claude reply when thinking is on.

The current Claude models think by default, so the reply's content list opens
with a `thinking` block that has no `text`. `data["content"][0]["text"]`
raised KeyError on every call.
"""
from __future__ import annotations

import httpx
import pytest

from app.errors import ApiError
from app.services import llm_client
from app.services.llm_client import LlmClient, anthropic_output_text
from app.services.provider_router import ResolvedModelConfig

MESSAGES = [{"role": "system", "content": "Be brief."},
            {"role": "user", "content": "Say hi."}]


def _config(model: str) -> ResolvedModelConfig:
    return ResolvedModelConfig(
        pipeline_stage="question_generation", provider="anthropic", model=model,
        resolved_base_url="https://api.anthropic.test", credential_ref_id="c", api_key="k")


def _reply(*blocks: dict, stop_reason: str = "end_turn", **extra) -> dict:
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5",
            "content": list(blocks), "stop_reason": stop_reason,
            "usage": {"input_tokens": 10, "output_tokens": 20}, **extra}


THINKING = {"type": "thinking", "thinking": "", "signature": "sig"}


@pytest.fixture()
def anthropic_returning(monkeypatch):
    """Serve `body` from the Messages endpoint; the sent payloads are kept."""
    sent: list[dict] = []

    def install(body: dict) -> list[dict]:
        def handler(request: httpx.Request) -> httpx.Response:
            import json
            sent.append(json.loads(request.content))
            return httpx.Response(200, json=body)

        real = httpx.Client
        monkeypatch.setattr(llm_client.httpx, "Client",
                            lambda *a, **k: real(transport=httpx.MockTransport(handler)))
        return sent
    return install


def test_a_leading_thinking_block_is_skipped(anthropic_returning) -> None:
    anthropic_returning(_reply(THINKING, {"type": "text", "text": "hi"}))

    text, usage = LlmClient()._call_anthropic(_config("claude-opus-5"), MESSAGES, 0.2, 0.9)

    assert text == "hi"
    assert usage.completion_tokens == 20


def test_every_text_block_is_joined_in_order() -> None:
    data = _reply(THINKING, {"type": "text", "text": '{"a": '},
                  {"type": "thinking", "thinking": "", "signature": "s2"},
                  {"type": "text", "text": "1}"})
    assert anthropic_output_text(data) == '{"a": 1}'


def test_max_tokens_is_raised_not_returned_partial() -> None:
    data = _reply(THINKING, {"type": "text", "text": '{"questions": [{"st'},
                  stop_reason="max_tokens")
    with pytest.raises(ApiError) as raised:
        anthropic_output_text(data, "claude-opus-5")
    assert raised.value.code == "LLM_INCOMPLETE"
    assert "max_tokens" in raised.value.message
    assert raised.value.retryable is False


def test_a_refusal_is_raised_with_its_category() -> None:
    data = _reply(stop_reason="refusal",
                  stop_details={"type": "refusal", "category": "cyber", "explanation": "No."})
    with pytest.raises(ApiError) as raised:
        anthropic_output_text(data, "claude-opus-5")
    assert raised.value.code == "LLM_CONTENT_FILTER"
    assert "cyber" in raised.value.message


def test_a_refusal_without_details_still_raises() -> None:
    with pytest.raises(ApiError) as raised:
        anthropic_output_text(_reply(stop_reason="refusal", stop_details=None))
    assert raised.value.code == "LLM_CONTENT_FILTER"


@pytest.mark.parametrize("model", ["claude-opus-5", "claude-sonnet-5", "claude-fable-5-1"])
def test_current_models_get_no_sampling_params_and_no_budget(anthropic_returning, model) -> None:
    """temperature/top_p and budget_tokens are each a 400 on these models."""
    sent = anthropic_returning(_reply(THINKING, {"type": "text", "text": "ok"}))

    LlmClient()._call_anthropic(_config(model), MESSAGES, 0.2, 0.9)

    payload = sent[0]
    assert payload["model"] == model
    assert "temperature" not in payload and "top_p" not in payload
    assert "thinking" not in payload, "left out: adaptive is the default"
    assert "budget_tokens" not in str(payload)
    assert payload["max_tokens"] >= 16000, "room for the thinking billed as output"
    assert payload["system"] == "Be brief."


def test_haiku_still_gets_sampling_params(anthropic_returning) -> None:
    sent = anthropic_returning(_reply({"type": "text", "text": "ok"}))

    LlmClient()._call_anthropic(_config("claude-haiku-4-5-20251001"), MESSAGES, 0.2, 0.9)

    assert sent[0]["temperature"] == 0.2 and sent[0]["top_p"] == 0.9


@pytest.mark.parametrize("model", ["claude-opus-5-5", "claude-opus-4-7", "claude-opus-4-8"])
def test_sampling_is_dropped_for_other_models_that_reject_it(model) -> None:
    assert llm_client._ANTHROPIC_NO_SAMPLING.match(model)
