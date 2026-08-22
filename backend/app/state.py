from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field

from cryptography.fernet import Fernet

from .config import Provider
from .settings import settings


@dataclass(slots=True)
class ProviderCredential:
    provider: str
    base_url: str | None = None
    encrypted_api_key: str | None = None
    credential_ref_id: str | None = None
    ollama_models: list[str] = field(default_factory=list)


@dataclass(slots=True)
class StageBinding:
    pipeline_stage: str
    provider: str
    model: str
    base_url: str | None = None


class RuntimeState:
    def __init__(self) -> None:
        env_key = os.getenv("CBC_MASTER_KEY")
        if env_key:
            key_bytes = env_key.encode("utf-8")
        else:
            key_bytes = Fernet.generate_key()

        self._fernet = Fernet(key_bytes)
        self.provider_credentials: dict[str, ProviderCredential] = {
            Provider.OPENAI.value: ProviderCredential(provider=Provider.OPENAI.value),
            Provider.ANTHROPIC.value: ProviderCredential(provider=Provider.ANTHROPIC.value),
            Provider.GEMINI.value: ProviderCredential(provider=Provider.GEMINI.value),
            Provider.OLLAMA.value: ProviderCredential(
                provider=Provider.OLLAMA.value,
                base_url=settings.ollama_base_url or "http://localhost:11434",
                ollama_models=["llama3.1", "qwen2.5:7b", "mistral"],
            ),
        }
        self.stage_bindings: dict[str, StageBinding] = {}
        self.run_registry: dict[str, dict] = {}

        if settings.openai_api_key:
            self.save_api_key(Provider.OPENAI.value, settings.openai_api_key)
        if settings.anthropic_api_key:
            self.save_api_key(Provider.ANTHROPIC.value, settings.anthropic_api_key)
        if settings.gemini_api_key:
            self.save_api_key(Provider.GEMINI.value, settings.gemini_api_key)

    def save_api_key(self, provider: str, api_key: str) -> str:
        encrypted = self._fernet.encrypt(api_key.encode("utf-8")).decode("utf-8")
        credential_ref_id = f"cred_{provider}_{secrets.token_hex(4)}"
        config = self.provider_credentials[provider]
        config.encrypted_api_key = encrypted
        config.credential_ref_id = credential_ref_id
        return credential_ref_id

    def decrypt_api_key(self, provider: str) -> str | None:
        encrypted = self.provider_credentials[provider].encrypted_api_key
        if not encrypted:
            return None
        return self._fernet.decrypt(encrypted.encode("utf-8")).decode("utf-8")

    def save_pipeline_run(self, run_id: str, payload: dict, result: dict) -> None:
        self.run_registry[run_id] = {
            "request_id": payload.get("request_id"),
            "trace_id": payload.get("trace_id"),
            "workflow_state": "reviewer_queue",
            "result": result,
            "updated_at": result.get("published_bundle", {}).get("updated_at"),
        }


runtime_state = RuntimeState()
