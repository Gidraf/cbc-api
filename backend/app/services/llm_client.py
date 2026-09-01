from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx

from ..config import Provider
from ..errors import raise_api_error
from ..services.cost_tracker import TokenUsage
from ..services.provider_router import ResolvedModelConfig
from ..services.retry import retry_llm

logger = logging.getLogger("cbc-llm")


@dataclass(slots=True)
class LlmResponse:
    """Structured response from an LLM call, including parsed content and token usage."""
    content: dict[str, Any]
    usage: TokenUsage
    model: str
    provider: str


def _model_remedy(config: "ResolvedModelConfig"):
    """The station's model field, offered where the failure was reported.

    The provider's own list where we have one — a free-text box is how
    'gemini-1.5-pro' got bound to a station that has never served it.
    """
    from .provider_router import known_models_for
    from .remedies import set_the_model

    return set_the_model(
        config.pipeline_stage,
        current=config.model,
        options=sorted(known_models_for(config.provider)),
    )


class LlmClient:
    def __init__(self, timeout_seconds: float = 120.0) -> None:
        self.timeout = timeout_seconds

    @retry_llm
    def generate(
        self,
        config: ResolvedModelConfig,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        top_p: float = 0.9,
    ) -> LlmResponse:
        """Calls the configured LLM provider, parses JSON response, and extracts token usage.
        
        Raises precise ApiError on failure — never returns fallback data.
        """
        provider = config.provider

        if provider == Provider.OPENAI.value or provider == Provider.OLLAMA.value:
            raw_text, usage = self._call_openai_compatible(config, messages, temperature, top_p)
        elif provider == Provider.ANTHROPIC.value:
            raw_text, usage = self._call_anthropic(config, messages, temperature, top_p)
        elif provider == Provider.GEMINI.value:
            raw_text, usage = self._call_gemini(config, messages, temperature, top_p)
        else:
            raw_text, usage = self._call_openai_compatible(config, messages, temperature, top_p)

        # Metered here, once, rather than threaded through fourteen route
        # handlers — the one that gets missed is always the one that spends
        # the most.
        from .run_meter import add as _meter

        _meter(usage, config.model, config.provider)

        content = self._extract_and_parse_json(raw_text)
        return LlmResponse(
            content=content,
            usage=usage,
            model=config.model,
            provider=config.provider,
        )

    def _classify_http_error(self, config: ResolvedModelConfig, resp: httpx.Response) -> None:
        """Classify HTTP error responses into precise ApiError codes."""
        status = resp.status_code
        body_preview = resp.text[:300] if resp.text else "(empty response)"
        provider_name = config.provider
        model_name = config.model

        if status == 401:
            raise_api_error(
                "MODEL_CREDENTIAL_MISSING",
                f"Invalid API key for {provider_name}. Check your API key in the Providers settings.",
            )
        elif status == 402:
            raise_api_error(
                "LLM_CREDIT_EXHAUSTED",
                f"Your {provider_name} account has insufficient credits. "
                f"Please add billing credits to continue generating content.",
            )
        elif status == 429:
            # Check if it's a quota/billing issue disguised as rate limit (OpenAI does this)
            body_lower = resp.text.lower() if resp.text else ""
            if "quota" in body_lower or "billing" in body_lower or "exceeded" in body_lower:
                raise_api_error(
                    "LLM_CREDIT_EXHAUSTED",
                    f"Your {provider_name} billing quota has been exceeded. "
                    f"Add credits at your provider's billing page to continue.",
                )
            raise_api_error(
                "LLM_RATE_LIMITED",
                f"Rate limit exceeded for {model_name} on {provider_name}. "
                f"The system will retry automatically.",
            )
        elif status == 404:
            # "Check your pipeline stage bindings in the Pipelines tab" is an
            # instruction, and the operator still has to find the tab, the
            # station, and the field. The remedy carries the field itself.
            raise_api_error(
                "LLM_INVALID_MODEL",
                f"Model '{model_name}' not found on {provider_name}. Every "
                f"generation at this station fails the same way until the "
                f"model is changed — retrying will not help.",
                remedy=_model_remedy(config),
            )
        elif status == 400:
            body_lower = resp.text.lower() if resp.text else ""
            if "invalid model" in body_lower or "model_not_found" in body_lower or "does not exist" in body_lower or "unknown model" in body_lower:
                raise_api_error(
                    "LLM_INVALID_MODEL",
                    f"Model '{model_name}' is not recognised on {provider_name} "
                    f"({body_preview}). Every generation at this station fails "
                    f"the same way until the model is changed.",
                    remedy=_model_remedy(config),
                )
            if "content_filter" in body_lower or "content_policy" in body_lower or "safety" in body_lower:
                raise_api_error(
                    "LLM_CONTENT_FILTER",
                    f"Content was blocked by {provider_name}'s safety filter. "
                    f"Review the prompt content for policy compliance.",
                )
            raise_api_error(
                "LLM_PROVIDER_ERROR",
                f"{provider_name} rejected the request ({status}): {body_preview}",
            )
        elif status >= 500:
            raise_api_error(
                "MODEL_ENDPOINT_UNAVAILABLE",
                f"{provider_name} server error ({status}): {body_preview}",
            )
        else:
            raise_api_error(
                "LLM_PROVIDER_ERROR",
                f"{provider_name} API error ({status}): {body_preview}",
            )

    def _call_openai_compatible(
        self,
        config: ResolvedModelConfig,
        messages: list[dict[str, str]],
        temperature: float,
        top_p: float,
    ) -> tuple[str, TokenUsage]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"

        base_url = config.resolved_base_url.rstrip("/")
        url = f"{base_url}/chat/completions" if not base_url.endswith("/v1") else f"{base_url}/chat/completions"

        model_name = (config.model or "gpt-4o-mini").strip()
        if not model_name or model_name.lower() in {"null", "undefined", "default", "none"}:
            model_name = "gpt-4o-mini"

        payload: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": 8192,
            "response_format": {"type": "json_object"},
        }

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, headers=headers, json=payload)
            # If 400 is returned because of response_format on some custom gateways, retry without response_format
            if resp.status_code == 400 and ("response_format" in resp.text or "json_object" in resp.text):
                payload.pop("response_format", None)
                resp = client.post(url, headers=headers, json=payload)

            if resp.status_code >= 400:
                self._classify_http_error(config, resp)

            data = resp.json()
            text = data["choices"][0]["message"]["content"]
            raw_usage = data.get("usage", {})
            usage = TokenUsage(
                prompt_tokens=raw_usage.get("prompt_tokens", 0),
                completion_tokens=raw_usage.get("completion_tokens", 0),
                total_tokens=raw_usage.get("total_tokens", 0),
            )
            return text, usage

    def _call_anthropic(
        self,
        config: ResolvedModelConfig,
        messages: list[dict[str, str]],
        temperature: float,
        top_p: float,
    ) -> tuple[str, TokenUsage]:
        headers = {
            "x-api-key": config.api_key or "",
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        url = f"{config.resolved_base_url.rstrip('/')}/v1/messages"

        system_prompt = "\n\n".join([m["content"] for m in messages if m["role"] == "system"])
        user_messages = [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] != "system"]

        payload = {
            "model": config.model or "claude-3-5-sonnet-20241022",
            "max_tokens": 8192,
            "system": system_prompt,
            "messages": user_messages,
            "temperature": temperature,
            "top_p": top_p,
        }

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, headers=headers, json=payload)
            if resp.status_code >= 400:
                self._classify_http_error(config, resp)

            data = resp.json()
            text = data["content"][0]["text"]
            raw_usage = data.get("usage", {})
            usage = TokenUsage(
                prompt_tokens=raw_usage.get("input_tokens", 0),
                completion_tokens=raw_usage.get("output_tokens", 0),
                total_tokens=raw_usage.get("input_tokens", 0) + raw_usage.get("output_tokens", 0),
            )
            return text, usage

    def _call_gemini(
        self,
        config: ResolvedModelConfig,
        messages: list[dict[str, str]],
        temperature: float,
        top_p: float,
    ) -> tuple[str, TokenUsage]:
        model = config.model or "gemini-2.0-flash"
        url = f"{config.resolved_base_url.rstrip('/')}/v1beta/models/{model}:generateContent?key={config.api_key}"

        contents = []
        for m in messages:
            role = "user" if m["role"] in {"user", "system"} else "model"
            contents.append({"role": role, "parts": [{"text": m["content"]}]})

        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "topP": top_p,
                "maxOutputTokens": 8192,
                "responseMimeType": "application/json",
            },
        }

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, json=payload)
            if resp.status_code >= 400:
                self._classify_http_error(config, resp)

            data = resp.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            usage_meta = data.get("usageMetadata", {})
            prompt_tokens = usage_meta.get("promptTokenCount", 0)
            completion_tokens = usage_meta.get("candidatesTokenCount", 0)
            usage = TokenUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            )
            return text, usage

    def _extract_and_parse_json(self, text: str) -> dict[str, Any]:
        """The JSON a model meant to send, out of what it actually sent.

        Hosted models answer a json_object request with bare JSON. Local ones
        very often do not, and the two habits below are not defects to be
        prompted away — they are how these models work:

        *   **Reasoning models narrate first.** qwen3 and its family emit a
            `<think>…</think>` block before the answer. It is the whole reason
            a local run comes back "could not be parsed as JSON" on a prompt
            that a hosted model answers perfectly.
        *   **Small models introduce themselves.** "Here is the JSON you asked
            for:" in front of a perfectly good object.

        So: drop the thinking, take the fences, and if it still will not parse,
        take the outermost braces. Every one of these is safe for a model that
        did the right thing, because none of them changes well-formed JSON.
        """
        cleaned = (text or "").strip()

        # Thinking first: a fence inside a <think> block would otherwise be
        # mistaken for the answer.
        cleaned = re.sub(r"<think(?:ing)?>.*?</think(?:ing)?>", "", cleaned,
                         flags=re.DOTALL | re.IGNORECASE).strip()
        # An unclosed block means the model ran out of tokens mid-thought.
        # There is no answer after it, but saying so beats "Expecting value".
        if re.match(r"<think(?:ing)?>", cleaned, re.IGNORECASE):
            raise_api_error(
                "SCHEMA_VALIDATION_FAILED",
                "The model was still thinking when it ran out of room and never "
                "reached its answer. Raise the context length, or run this "
                "station on a model that does not think out loud.",
            )

        if "```json" in cleaned:
            match = re.search(r"```json\s*(.*?)\s*```", cleaned, re.DOTALL)
            if match:
                cleaned = match.group(1)
        elif "```" in cleaned:
            match = re.search(r"```\s*(.*?)\s*```", cleaned, re.DOTALL)
            if match:
                cleaned = match.group(1)

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # Last resort: the outermost object in whatever came back.
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start:end + 1])
            except json.JSONDecodeError:
                pass

        logger.error("JSON parsing failed on LLM output: %s", cleaned[:300])
        raise_api_error(
            "SCHEMA_VALIDATION_FAILED",
            f"The model did not return JSON. It began: {cleaned[:160]!r}",
        )
        return {}


llm_client = LlmClient()
