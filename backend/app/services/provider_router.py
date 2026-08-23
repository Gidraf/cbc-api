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


class ProviderRouter:
    def __init__(self, state: RuntimeState) -> None:
        self.state = state

    def resolve_for_stage(self, stage: str) -> ResolvedModelConfig:
        binding = self.state.stage_bindings.get(stage)
        if not binding:
            # Fallback to default binding if stage not explicitly bound
            provider = Provider.OPENAI.value
            model = "gpt-4o-mini"
            resolved_base_url = OFFICIAL_BASE_URLS[Provider.OPENAI]
            binding_base_url = None
        else:
            provider = binding.provider
            model = (binding.model or "").strip()
            binding_base_url = binding.base_url

        # Ensure valid non-empty model name
        if not model or model.lower() in {"null", "undefined", "default", "none", ""}:
            if provider == Provider.OPENAI.value:
                model = "gpt-4o-mini"
            elif provider == Provider.ANTHROPIC.value:
                model = "claude-3-5-sonnet-20241022"
            elif provider == Provider.GEMINI.value:
                model = "gemini-2.0-flash"
            elif provider == Provider.OLLAMA.value:
                model = "llama3.1"
            else:
                model = "gpt-4o-mini"

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
