from __future__ import annotations

import hashlib
import logging
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


logger = logging.getLogger("cbc-provider-router")

# The advanced models, and nothing older. One list, in model_policy, so the
# router, the console's catalogue, the second-opinion reviewer and the
# bootstrap cannot disagree about what is allowed to run.
from .model_policy import ANTHROPIC as _ANTHROPIC_MODELS
from .model_policy import GEMINI as _GEMINI_MODELS
from .model_policy import OPENAI as _OPENAI_MODELS

OPENAI_VALID_MODELS = set(_OPENAI_MODELS)


# What each provider is known to serve, for the moment a binding turns out to
# name something it does not. Not exhaustive and not a gate — providers add
# models faster than this list can be maintained, and refusing an unlisted one
# would block a model released this morning. It exists so the error that says
# "not found" can offer somewhere to start rather than a free-text box, which
# is how `gemini-1.5-pro` came to be bound to a station that never served it.
KNOWN_MODELS: dict[str, tuple[str, ...]] = {
    Provider.OPENAI.value: tuple(_OPENAI_MODELS),
    Provider.ANTHROPIC.value: tuple(_ANTHROPIC_MODELS),
    Provider.GEMINI.value: tuple(_GEMINI_MODELS),
    # Deliberately empty: a self-hosted server is the one provider that can be
    # ASKED what it has, and guessing at it is worse than useless. "llama3.1"
    # was the guess here, and it is not a model anybody has — Ollama names are
    # tagged, so the installed model is `llama3.1:8b`. The guess was offered as
    # a fix for a missing model and was itself missing.
    Provider.OLLAMA.value: (),
}


def installed_models(base_url: str) -> tuple[str, ...]:
    """What this Ollama actually has, from the server itself.

    Ollama names carry a tag — `llama3.1:8b`, `qwen3:14b` — and a bare family
    name resolves only if `:latest` was pulled. That is the whole of this bug:
    a station bound to `llama3.1` fails on a machine that has `llama3.1:8b`,
    and no amount of retrying changes it.
    """
    if not base_url:
        return ()
    import httpx

    root = base_url.rstrip("/")
    # The tag list lives at the server root; the chat endpoint may be under /v1.
    if root.endswith("/v1"):
        root = root[:-3]
    try:
        with httpx.Client(timeout=4.0) as client:
            found = client.get(f"{root}/api/tags").json()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not list models at %s: %s", root, exc)
        return ()
    return tuple(sorted(
        str(m.get("name") or "") for m in (found.get("models") or [])
        if isinstance(m, dict) and m.get("name")
    ))


def known_models_for(provider: str, base_url: str = "") -> tuple[str, ...]:
    """A starting point for a station whose model turned out not to exist.

    For a self-hosted server this is the real list, asked for at the moment it
    is needed, because the answer depends on which machine is serving and what
    was pulled onto it this week — neither of which any table here can know.
    """
    provider = (provider or "").strip().lower()
    if provider == Provider.OLLAMA.value:
        return installed_models(base_url)
    return KNOWN_MODELS.get(provider, ())


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
    """The model to run for a name somebody typed.

    A fully-qualified id passes through; a bare family name ("sonnet",
    "pro", "terra") becomes the current member of that family; an empty or
    retired name becomes the provider's default, with a warning. There is no
    alias here that lands on an old model.
    """
    from .model_policy import advanced_for, enforce

    provider = (provider or "").strip().lower()
    cleaned = (raw_model or "").strip()
    lower = cleaned.lower().replace(" ", "-").replace("_", "-")

    if provider == Provider.OLLAMA.value:
        return cleaned

    if provider in (Provider.OPENAI.value, Provider.ANTHROPIC.value, Provider.GEMINI.value):
        if not cleaned or lower in {"", "null", "undefined", "default", "none"}:
            return enforce(provider, "", where="binding")
        # A family typed without its version: the current member.
        if not any(ch.isdigit() for ch in lower):
            for candidate in advanced_for(provider):
                if lower in candidate.lower():
                    return candidate
            return enforce(provider, "", where=f"binding {cleaned!r}")
        return enforce(provider, lower if provider != Provider.ANTHROPIC.value else cleaned,
                       where=f"binding {cleaned!r}")

    return cleaned


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
            # An unbound stage runs on the configured default for its tier,
            # never on a hard-coded model. "gpt-4o-mini" sat here for a year
            # and every process that had not loaded its bindings — the Celery
            # worker — wrote content with it while the console showed a
            # different model.
            from ..state import default_model_for

            provider = provider or Provider.OPENAI.value
            model = model or (default_model_for(stage)
                              if provider == Provider.OPENAI.value else "")
            resolved_base_url = OFFICIAL_BASE_URLS[Provider.OPENAI]
            binding_base_url = None
            model = normalize_model_name(provider, model)
            logger.warning("Stage %s is not bound; using %s/%s.", stage, provider, model)
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
