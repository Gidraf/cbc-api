from __future__ import annotations

import hashlib
from dataclasses import dataclass
from urllib import request
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
            raise_api_error("MODEL_NOT_CONFIGURED_FOR_STAGE", f"No provider/model mapping found for stage: {stage}")

        provider = binding.provider
        provider_config = self.state.provider_credentials.get(provider)
        if not provider_config:
            raise_api_error("UNSUPPORTED_MODEL_PROVIDER", f"Unsupported provider: {provider}")

        if provider in {Provider.OPENAI.value, Provider.ANTHROPIC.value, Provider.GEMINI.value}:
            default_base_url = OFFICIAL_BASE_URLS[Provider(provider)]
            resolved_base_url = binding.base_url or provider_config.base_url or default_base_url
        else:
            resolved_base_url = binding.base_url or provider_config.base_url
            if not resolved_base_url:
                raise_api_error("MODEL_ENDPOINT_UNAVAILABLE", "Ollama base_url is not configured")
            if binding.model not in provider_config.ollama_models:
                raise_api_error("MODEL_NOT_CONFIGURED_FOR_STAGE", f"Ollama model not allowed/configured: {binding.model}")

        api_key = self.state.decrypt_api_key(provider)
        if provider in {Provider.OPENAI.value, Provider.ANTHROPIC.value, Provider.GEMINI.value} and not api_key:
            raise_api_error("MODEL_CREDENTIAL_MISSING", f"API key missing for provider: {provider}")

        credential_ref_id = provider_config.credential_ref_id or self._synth_credential_ref(provider)
        self._check_endpoint_reachability(resolved_base_url)

        return ResolvedModelConfig(
            pipeline_stage=stage,
            provider=provider,
            model=binding.model,
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
