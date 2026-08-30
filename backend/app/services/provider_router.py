from __future__ import annotations

import hashlib
from dataclasses import dataclass
from urllib import request
from urllib.error import HTTPError
from urllib.error import URLError

from ..config import OFFICIAL_BASE_URLS, Provider
from ..errors import ApiError, raise_api_error
from ..state import RuntimeState


@dataclass(slots=True)
class ResolvedModelConfig:
    pipeline_stage: str
    provider: str
    model: str
    resolved_base_url: str
    credential_ref_id: str
    api_key: str | None


OPENAI_VALID_MODELS = {
    "gpt-4o-mini",
    "gpt-4o",
    "gpt-4o-2024-08-06",
    "gpt-4o-2024-05-13",
    "gpt-4o-mini-2024-07-18",
    "gpt-4-turbo",
    "gpt-4",
    "gpt-3.5-turbo",
    "o1",
    "o1-mini",
    "o1-preview",
    "o3-mini",
    "chatgpt-4o-latest",
}


def _is_qualified(lower: str, prefix: str) -> bool:
    """Whether a binding already names a specific model rather than a family.

    The rules below used to match on a bare word: `"pro" in lower` rewrote
    EVERY Gemini model with "pro" in its name to gemini-1.5-pro, so a stage
    bound to gemini-2.5-pro was silently downgraded to a model Google has since
    retired — and the run then failed with

        Model 'gemini-1.5-pro' not found on gemini

    naming a model the operator had never chosen. The same shape sent every
    Anthropic binding containing "opus" to claude-3-opus-20240229.

    A normaliser exists to turn "sonnet" into a real model id. It has no
    business rewriting an id that is already one — new models ship constantly,
    and a mapping table that has to be edited before any of them can be used is
    a mapping table that will be out of date every time.
    """
    return lower.startswith(prefix) and any(ch.isdigit() for ch in lower)


def normalize_model_name(provider: str, raw_model: str) -> str:
    """Normalizes and auto-corrects model names, typos, and version aliases."""
    cleaned = (raw_model or "").strip()
    lower = cleaned.lower().replace(" ", "-").replace("_", "-")

    if provider == Provider.OPENAI.value:
        if not cleaned or lower in {"", "null", "undefined", "default", "none"}:
            return "gpt-4o-mini"
        if cleaned in OPENAI_VALID_MODELS:
            return cleaned
        # A fully-qualified id is passed through before any alias rule runs.
        # "gpt-5" used to be listed as a typo for gpt-4o-mini, written when no
        # such model existed. It exists now, and a stage bound to it was
        # silently served a cheaper one — the failure that is hardest to
        # notice, because the run succeeds.
        if _is_qualified(lower, "gpt-") or lower.startswith("o1") or lower.startswith("o3"):
            return lower
        # Genuine aliases: a family typed without a version.
        if "4o-mini" in lower or "gpt-4-mini" in lower or "gpt4-mini" in lower:
            return "gpt-4o-mini"
        if "4o" in lower:
            return "gpt-4o"
        if "3.5" in lower or "35" in lower:
            return "gpt-3.5-turbo"
        return "gpt-4o-mini"

    elif provider == Provider.ANTHROPIC.value:
        if not cleaned or lower in {"", "null", "undefined", "default", "none"}:
            return "claude-3-5-sonnet-20241022"
        if _is_qualified(lower, "claude-"):
            return cleaned
        # Bare families only, for a binding typed as "sonnet" or "opus".
        if "sonnet" in lower:
            return "claude-3-5-sonnet-20241022"
        if "opus" in lower:
            return "claude-3-opus-20240229"
        if "haiku" in lower:
            return "claude-3-5-haiku-20241022"
        return cleaned

    elif provider == Provider.GEMINI.value:
        if not cleaned or lower in {"", "null", "undefined", "default", "none"}:
            return "gemini-2.0-flash"
        if _is_qualified(lower, "gemini-"):
            return cleaned
        if "pro" in lower:
            return "gemini-2.5-pro"
        if "flash" in lower:
            return "gemini-2.0-flash"
        return cleaned

    elif provider == Provider.OLLAMA.value:
        if not cleaned or lower in {"", "null", "undefined", "default", "none"}:
            return "llama3.1"
        return cleaned

    return cleaned or "gpt-4o-mini"


class ProviderRouter:
    def __init__(self, state: RuntimeState) -> None:
        self.state = state

    def resolve_for_stage(
        self, stage: str, provider: str | None = None, model: str | None = None,
    ) -> ResolvedModelConfig:
        """The model bound to a stage, or an explicit one the caller chose.

        Review needs the override: layer 2 exists to be a second opinion, and a
        second opinion from the vendor that wrote the content is one opinion
        asked twice. The caller picks the vendor; the resolution, credential
        handling and reachability checks stay exactly the same.
        """
        # An unbound stage inherits from the nearest bound relative before it
        # defaults. Splitting one stage into six would otherwise drop every new
        # one to the hardcoded fallback the moment the code shipped — a silent
        # downgrade on the run after a deploy, with nothing in the output
        # saying why the quality fell.
        from .stages import chain

        binding = None
        for candidate in chain(stage):
            binding = self.state.stage_bindings.get(candidate)
            if binding:
                break

        if not binding:
            # Fallback to default binding if stage not explicitly bound
            provider = provider or Provider.OPENAI.value
            model = model or "gpt-4o-mini"
            resolved_base_url = OFFICIAL_BASE_URLS[Provider.OPENAI]
            binding_base_url = None
            model = normalize_model_name(provider, model)
        else:
            provider = provider or binding.provider
            raw_model = (model or binding.model or "").strip()
            model = normalize_model_name(provider, raw_model)
            binding_base_url = binding.base_url if provider == binding.provider else None

        provider_config = self.state.provider_credentials.get(provider)
        if not provider_config:
            raise_api_error("UNSUPPORTED_MODEL_PROVIDER", f"Unsupported provider: {provider}")

        if provider in {Provider.OPENAI.value, Provider.ANTHROPIC.value, Provider.GEMINI.value}:
            default_base_url = OFFICIAL_BASE_URLS[Provider(provider)]
            resolved_base_url = binding_base_url or provider_config.base_url or default_base_url
        else:
            resolved_base_url = binding_base_url or provider_config.base_url
            if not resolved_base_url:
                raise_api_error("MODEL_ENDPOINT_UNAVAILABLE", "Ollama base_url is not configured")
            if provider_config.ollama_models and model not in provider_config.ollama_models:
                # Add to allowed ollama models dynamically if custom model passed
                provider_config.ollama_models.append(model)

        api_key = self.state.decrypt_api_key(provider)
        if provider in {Provider.OPENAI.value, Provider.ANTHROPIC.value, Provider.GEMINI.value} and not api_key:
            raise_api_error("MODEL_CREDENTIAL_MISSING", f"API key missing for provider: {provider}")

        credential_ref_id = provider_config.credential_ref_id or self._synth_credential_ref(provider)
        self._check_endpoint_reachability(resolved_base_url)

        return ResolvedModelConfig(
            pipeline_stage=stage,
            provider=provider,
            model=model,
            resolved_base_url=resolved_base_url,
            credential_ref_id=credential_ref_id,
            api_key=api_key,
        )

    def _check_endpoint_reachability(self, url: str) -> None:
        try:
            req = request.Request(url=url, method="GET")
            with request.urlopen(req, timeout=5.0) as response:  # noqa: S310
                status_code = response.getcode()
                if status_code >= 500:
                    raise_api_error("MODEL_ENDPOINT_UNAVAILABLE", f"Endpoint returned server error: {url}")
        except HTTPError as exc:
            # 4xx still proves the endpoint is reachable (many model APIs return
            # 401/403/404 for bare GETs on base paths). Only 5xx is considered unavailable.
            if exc.code >= 500:
                raise_api_error("MODEL_ENDPOINT_UNAVAILABLE", f"Endpoint returned server error: {url} (HTTP {exc.code})")
        except ApiError:
            raise
        except URLError as exc:
            raise_api_error("MODEL_ENDPOINT_UNAVAILABLE", f"Endpoint unreachable: {url} ({exc})")

    @staticmethod
    def prompt_hash(prompt_name: str, payload: dict) -> str:
        source = f"{prompt_name}:{payload}".encode("utf-8")
        return hashlib.sha256(source).hexdigest()

    @staticmethod
    def _synth_credential_ref(provider: str) -> str:
        seed = provider.encode("utf-8")
        return f"cred_{provider}_{hashlib.sha256(seed).hexdigest()[:8]}"
