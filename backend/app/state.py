from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass, field

from cryptography.fernet import Fernet

from .config import Provider
from .infra.db import execute, fetch_all, to_json
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
        self.user_accounts = {
            username: {
                "password": details.get("password", ""),
                "role": details.get("role", "developer"),
            }
            for username, details in settings.user_accounts.items()
        }

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

    def persist_provider(self, provider: str) -> None:
        config = self.provider_credentials[provider]
        execute(
            """
            INSERT INTO provider_configs (provider, base_url, encrypted_api_key, credential_ref_id, ollama_models, updated_at)
            VALUES (:provider, :base_url, :encrypted_api_key, :credential_ref_id, CAST(:ollama_models AS jsonb), NOW())
            ON CONFLICT (provider)
            DO UPDATE SET
                base_url = EXCLUDED.base_url,
                encrypted_api_key = EXCLUDED.encrypted_api_key,
                credential_ref_id = EXCLUDED.credential_ref_id,
                ollama_models = EXCLUDED.ollama_models,
                updated_at = NOW()
            """,
            {
                "provider": provider,
                "base_url": config.base_url,
                "encrypted_api_key": config.encrypted_api_key,
                "credential_ref_id": config.credential_ref_id,
                "ollama_models": to_json(config.ollama_models),
            },
        )

    def persist_stage_binding(self, stage: str) -> None:
        binding = self.stage_bindings[stage]
        execute(
            """
            INSERT INTO stage_bindings (pipeline_stage, provider, model, base_url, updated_at)
            VALUES (:pipeline_stage, :provider, :model, :base_url, NOW())
            ON CONFLICT (pipeline_stage)
            DO UPDATE SET
                provider = EXCLUDED.provider,
                model = EXCLUDED.model,
                base_url = EXCLUDED.base_url,
                updated_at = NOW()
            """,
            {
                "pipeline_stage": binding.pipeline_stage,
                "provider": binding.provider,
                "model": binding.model,
                "base_url": binding.base_url,
            },
        )

    def sync_users_from_env(self) -> None:
        for username, details in self.user_accounts.items():
            execute(
                """
                INSERT INTO app_users (username, password_plain, role, is_active, updated_at)
                VALUES (:username, :password_plain, :role, TRUE, NOW())
                ON CONFLICT (username)
                DO UPDATE SET
                    password_plain = EXCLUDED.password_plain,
                    role = EXCLUDED.role,
                    updated_at = NOW()
                """,
                {
                    "username": username,
                    "password_plain": details.get("password", ""),
                    "role": details.get("role", "developer"),
                },
            )

    def load_from_db(self) -> None:
        self._load_provider_configs()
        self._load_stage_bindings()
        self._load_pipeline_runs()
        self._load_user_accounts()

    def _load_provider_configs(self) -> None:
        provider_rows = fetch_all("SELECT provider, base_url, encrypted_api_key, credential_ref_id, ollama_models FROM provider_configs")
        for row in provider_rows:
            provider = row["provider"]
            if provider not in self.provider_credentials:
                continue

            models = self._parse_json(row.get("ollama_models"), [])
            self.provider_credentials[provider].base_url = row.get("base_url")
            self.provider_credentials[provider].encrypted_api_key = row.get("encrypted_api_key")
            self.provider_credentials[provider].credential_ref_id = row.get("credential_ref_id")
            self.provider_credentials[provider].ollama_models = list(models or [])

    def _load_stage_bindings(self) -> None:
        stage_rows = fetch_all("SELECT pipeline_stage, provider, model, base_url FROM stage_bindings")
        for row in stage_rows:
            self.stage_bindings[row["pipeline_stage"]] = StageBinding(
                pipeline_stage=row["pipeline_stage"],
                provider=row["provider"],
                model=row["model"],
                base_url=row.get("base_url"),
            )

    def _load_pipeline_runs(self) -> None:
        run_rows = fetch_all("SELECT run_id, request_id, trace_id, workflow_state, result, updated_at FROM pipeline_runs")
        for row in run_rows:
            result = self._parse_json(row.get("result"), {})
            self.run_registry[row["run_id"]] = {
                "request_id": row.get("request_id"),
                "trace_id": row.get("trace_id"),
                "workflow_state": row.get("workflow_state"),
                "result": result,
                "updated_at": str(row.get("updated_at")),
            }

    def _load_user_accounts(self) -> None:
        user_rows = fetch_all("SELECT username, password_plain, role FROM app_users WHERE is_active = TRUE")
        if not user_rows:
            return

        self.user_accounts = {
            row["username"]: {
                "password": row.get("password_plain", ""),
                "role": row.get("role", "developer"),
            }
            for row in user_rows
        }

    @staticmethod
    def _parse_json(value: object, fallback: object):
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return fallback
        if value is None:
            return fallback
        return value

    def save_pipeline_run(self, run_id: str, payload: dict, result: dict) -> None:
        self.run_registry[run_id] = {
            "request_id": payload.get("request_id"),
            "trace_id": payload.get("trace_id"),
            "workflow_state": "reviewer_queue",
            "result": result,
            "updated_at": result.get("published_bundle", {}).get("updated_at"),
        }
        execute(
            """
            INSERT INTO pipeline_runs (run_id, request_id, trace_id, workflow_state, result, updated_at)
            VALUES (:run_id, :request_id, :trace_id, :workflow_state, CAST(:result AS jsonb), NOW())
            ON CONFLICT (run_id)
            DO UPDATE SET
                request_id = EXCLUDED.request_id,
                trace_id = EXCLUDED.trace_id,
                workflow_state = EXCLUDED.workflow_state,
                result = EXCLUDED.result,
                updated_at = NOW()
            """,
            {
                "run_id": run_id,
                "request_id": payload.get("request_id"),
                "trace_id": payload.get("trace_id"),
                "workflow_state": "reviewer_queue",
                "result": to_json(result),
            },
        )

    def set_pipeline_run_state(self, run_id: str, state: str) -> None:
        if run_id in self.run_registry:
            self.run_registry[run_id]["workflow_state"] = state
        execute(
            """
            UPDATE pipeline_runs
            SET workflow_state = :state, updated_at = NOW()
            WHERE run_id = :run_id
            """,
            {"run_id": run_id, "state": state},
        )


runtime_state = RuntimeState()
