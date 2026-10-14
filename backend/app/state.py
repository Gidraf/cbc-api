from __future__ import annotations

import json
import logging
import os
import secrets
from dataclasses import dataclass, field

from cryptography.fernet import Fernet

from .config import Provider
from .infra.db import execute, fetch_all, to_json
from .settings import settings

logger = logging.getLogger("cbc-state")

# The OpenAI model a stage runs on unless bound otherwise in the console:
# the default for stages that write, the light one for stages that read.
# Any GPT-5-family id bound in the console is passed through untouched.
DEFAULT_OPENAI_MODEL = settings.openai_default_model
LIGHT_OPENAI_MODEL = settings.openai_light_model


def default_model_for(stage: str) -> str:
    """The tier's model now — which an approved model-scout switch changes."""
    from .services.model_policy import tier_model, tier_of

    try:
        return tier_model(tier_of(stage))
    except Exception:  # noqa: BLE001
        from .services.stages import needs_reasoning

        return DEFAULT_OPENAI_MODEL if needs_reasoning(stage) else LIGHT_OPENAI_MODEL


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
            # Unset: the key docker-compose.yml used to supply, so keys saved
            # with it still read — services/secrets_guard.py reports it as
            # weak and deploy/harden.sh moves them to a key of your own. A
            # fresh random key here would make every saved key unreadable.
            from .services.secrets_guard import PUBLISHED_MASTER_KEY

            key_bytes = PUBLISHED_MASTER_KEY.encode("utf-8")

        self._fernet = Fernet(key_bytes)
        self.provider_credentials: dict[str, ProviderCredential] = {
            Provider.OPENAI.value: ProviderCredential(provider=Provider.OPENAI.value),
            Provider.ANTHROPIC.value: ProviderCredential(provider=Provider.ANTHROPIC.value),
            Provider.GEMINI.value: ProviderCredential(provider=Provider.GEMINI.value),
            Provider.OLLAMA.value: ProviderCredential(
                provider=Provider.OLLAMA.value,
                base_url=settings.ollama_base_url or "http://localhost:11434",
                ollama_models=[],
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
        """Kept for the callers that run it at startup: see harden_users."""
        harden_users()

    def load_from_db(self) -> None:
        self._load_provider_configs()
        self._load_stage_bindings()
        self._load_pipeline_runs()

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
            provider = row["provider"]
            raw_model = (row.get("model") or "").strip()
            lower = raw_model.lower().replace(" ", "-").replace("_", "-")

            # A stored binding names a model. An empty one, or one from a
            # retired family, becomes the stage's default — the console's
            # old buttons wrote gpt-4o-mini and gpt-4o into every stage, and
            # runs on them were read as runs on the model the console showed.
            from .services.model_policy import enforce, is_retired

            if provider == "openai":
                if not raw_model or lower in {"", "null", "undefined", "default", "none"} \
                        or is_retired(raw_model):
                    model = default_model_for(row["pipeline_stage"])
                    if raw_model:
                        logger.warning("Stage %s was bound to %r; using %s — retired here.",
                                       row["pipeline_stage"], raw_model, model)
                else:
                    model = raw_model
            elif provider in ("anthropic", "gemini"):
                model = enforce(provider, raw_model, where=f"stage {row['pipeline_stage']}")
            else:
                model = raw_model

            self.stage_bindings[row["pipeline_stage"]] = StageBinding(
                pipeline_stage=row["pipeline_stage"],
                provider=provider,
                model=model,
                base_url=row.get("base_url"),
            )
            # If the model name was corrected, persist the repaired name back to the database
            if model != raw_model:
                try:
                    self.persist_stage_binding(row["pipeline_stage"])
                except Exception:
                    pass

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


# ── accounts ─────────────────────────────────────────────────────────────────

# Passwords this code once shipped as defaults, and the obvious ones: an
# account still using one is switched off at startup.
KNOWN_WEAK = {"admin123", "operator123", "reviewer123", "developer123", "admin", "password", "changeme",
              "change-me", "12345678", "123456789", "password123", "qwerty123"}
MIN_BUILTIN_PASSWORD = 12


def harden_users() -> dict[str, list[str]]:
    """At every start: no account keeps a plain-text password, no built-in
    account gets a default one, and an account still using a known default
    is switched off. What happened is logged and returned (names only).

    * Plain-text passwords are hashed with bcrypt and the text is wiped.
    * ADMIN_PASSWORD (and OPERATOR_, REVIEWER_, DEVELOPER_) set to a strong
      value — 12 characters or more, not a known default — sets that
      account's password. Unset, the account is left as it is: set its
      password with `docker compose exec api python -m app.admin_tools reset-password --username <name>`.
    * An account whose password is a known default is switched off.
    """
    import logging
    import os

    from .infra.db import execute, fetch_all
    from .services.auth import hash_password, verify_password

    log = logging.getLogger("cbc-security")
    done: dict[str, list[str]] = {"hashed": [], "set_from_env": [], "switched_off": [], "weak_env": []}

    for row in fetch_all("SELECT username, password_plain, password_hash FROM app_users "
                         "WHERE COALESCE(password_plain, '') <> ''") or []:
        if not str(row.get("password_hash") or "").startswith("$2"):
            execute("UPDATE app_users SET password_hash = :h, password_plain = '', updated_at = NOW() WHERE username = :u",
                    {"h": hash_password(str(row["password_plain"])), "u": row["username"]})
        else:
            execute("UPDATE app_users SET password_plain = '', updated_at = NOW() WHERE username = :u",
                    {"u": row["username"]})
        done["hashed"].append(row["username"])

    for username, (env_name, role) in settings.builtin_accounts.items():
        wanted = os.getenv(env_name, "")
        if wanted and (len(wanted) < MIN_BUILTIN_PASSWORD or wanted.lower() in KNOWN_WEAK):
            done["weak_env"].append(env_name)
            wanted = ""
        if wanted:
            execute("""INSERT INTO app_users (username, password_plain, password_hash, role, is_active, updated_at)
                       VALUES (:u, '', :h, :r, TRUE, NOW())
                       ON CONFLICT (username) DO UPDATE SET password_plain = '', password_hash = EXCLUDED.password_hash,
                           role = EXCLUDED.role, is_active = TRUE, updated_at = NOW()""",
                    {"u": username, "h": hash_password(wanted), "r": role})
            done["set_from_env"].append(username)

    # Staff accounts only (a handful): bcrypt is slow on purpose, and public
    # sign-ups meet the password rule when they register.
    for row in fetch_all("""SELECT username, password_hash FROM app_users WHERE is_active = TRUE
                            AND role IN ('admin', 'operator', 'reviewer', 'developer')""") or []:
        stored = str(row.get("password_hash") or "")
        if stored and any(verify_password(weak, stored) for weak in KNOWN_WEAK):
            execute("UPDATE app_users SET is_active = FALSE, updated_at = NOW() WHERE username = :u",
                    {"u": row["username"]})
            done["switched_off"].append(row["username"])

    for name in done["weak_env"]:
        log.error("%s is too weak (12+ characters, not a default) and was ignored.", name)
    for name in done["switched_off"]:
        log.error("Account %r used a known default password and is switched off. Give it a new one: "
                  "docker compose exec api python -m app.admin_tools reset-password --username %s", name, name)
    if done["hashed"]:
        log.warning("Hashed %d plain-text password(s).", len(done["hashed"]))
    return done
