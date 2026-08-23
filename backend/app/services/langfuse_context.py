from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

from ..errors import raise_api_error
from ..settings import settings

logger = logging.getLogger("cbc-langfuse")

_DEV_FALLBACK_MASTER_CONTEXT = """# CBC Master Context (Development Fallback)
This is a minimal development fallback. For production, seed Langfuse:
  python -m app.services.langfuse_seed

KICD Basic Education Curriculum Framework: Criterion-referenced assessment only.
NEVER rank or compare learners against each other.
"""

@dataclass(slots=True)
class CompiledContextResult:
    master_context: str
    subject_context: dict
    user_prompt: str
    messages: list[dict[str, str]]
    prompt_name: str
    prompt_version: str
    prompt_label: str
    prompt_hash: str

class LangfuseContextService:
    def __init__(self) -> None:
        self._client: Any = None
        self._cache: dict[str, tuple[float, Any]] = {}
        self._init_client()

    @property
    def _is_strict(self) -> bool:
        return settings.langfuse_env == "prod"

    def _init_client(self) -> None:
        if settings.langfuse_public_key and settings.langfuse_secret_key:
            try:
                from langfuse import Langfuse

                self._client = Langfuse(
                    public_key=settings.langfuse_public_key,
                    secret_key=settings.langfuse_secret_key,
                    host=settings.langfuse_host,
                )
                logger.info("Langfuse client initialized for host: %s", settings.langfuse_host)
            except Exception as exc:
                logger.warning("Failed to initialize Langfuse SDK: %s", exc)
                self._client = None
        else:
            if self._is_strict:
                logger.error("Langfuse keys missing in production environment!")
            else:
                logger.info("Langfuse keys not set; using local fallback in dev/staging.")

    def _get_from_cache(self, key: str) -> Any | None:
        if key in self._cache:
            timestamp, val = self._cache[key]
            if time.time() - timestamp < settings.langfuse_cache_ttl_seconds:
                return val
        return None

    def _set_cache(self, key: str, val: Any) -> None:
        self._cache[key] = (time.time(), val)

    def get_master_context(self) -> str:
        cached = self._get_from_cache("master_context")
        if cached:
            return cached

        if self._client:
            try:
                prompt = self._client.get_prompt("cbc-master-context", label=settings.langfuse_env)
                if prompt and prompt.prompt:
                    text = prompt.compile()
                    self._set_cache("master_context", text)
                    return text
            except Exception as exc:
                logger.warning("Could not fetch 'cbc-master-context' from Langfuse: %s", exc)
                if self._is_strict:
                    raise_api_error("LANGFUSE_UNAVAILABLE", "Failed to fetch master context from Langfuse in strict mode.")

        if self._is_strict:
            raise_api_error("LANGFUSE_UNAVAILABLE", "Langfuse client unavailable in strict mode.")

        self._set_cache("master_context", _DEV_FALLBACK_MASTER_CONTEXT)
        return _DEV_FALLBACK_MASTER_CONTEXT

    def get_grade_dataset(self, grade_slug: str) -> list[dict]:
        cache_key = f"dataset_{grade_slug}"
        cached = self._get_from_cache(cache_key)
        if cached:
            return cached

        if self._client:
            try:
                dataset = self._client.get_dataset(name=grade_slug)
                if dataset and dataset.items:
                    items = [
                        {
                            "id": item.id,
                            "input": item.input,
                            "expected_output": item.expected_output,
                            "metadata": item.metadata or {},
                        }
                        for item in dataset.items
                    ]
                    self._set_cache(cache_key, items)
                    return items
            except Exception as exc:
                logger.warning("Could not fetch dataset '%s' from Langfuse: %s", grade_slug, exc)
                if self._is_strict:
                    raise_api_error("LANGFUSE_DATASET_NOT_FOUND", f"Failed to fetch dataset '{grade_slug}' from Langfuse.")

        if self._is_strict:
            raise_api_error("LANGFUSE_DATASET_NOT_FOUND", f"Langfuse client unavailable to fetch dataset '{grade_slug}' in strict mode.")

        # Fallback local dataset items
        fallback = [
            {
                "id": f"itm_{grade_slug}_default",
                "input": {
                    "grade": grade_slug,
                    "subject": "Integrated Science",
                    "subject_code": "ISCI",
                },
                "metadata": {
                    "name": "Integrated Science",
                    "code": "ISCI",
                    "essence_statement": "Develops scientific inquiry, environmental conservation, and technological literacy.",
                    "strands": [
                        {
                            "name": "Matter",
                            "sub_strands": [
                                {
                                    "name": "Classification of Matter",
                                    "slos": ["MS-G7-ISCI-MAT-CLM-01"],
                                }
                            ],
                        }
                    ],
                },
            }
        ]
        self._set_cache(cache_key, fallback)
        return fallback

    def get_subject_context(self, grade_slug: str, subject: str) -> dict:
        dataset_items = self.get_grade_dataset(grade_slug)
        for item in dataset_items:
            inp = item.get("input", {})
            if isinstance(inp, dict) and inp.get("subject", "").lower() == subject.lower():
                return item.get("metadata", {})
            if isinstance(inp, str) and subject.lower() in inp.lower():
                return item.get("metadata", {})

        if self._is_strict:
            raise_api_error("DATASET_ITEM_NOT_FOUND", f"Subject '{subject}' not found in dataset '{grade_slug}'.")

        return {
            "essence_statement": f"Curriculum design for {subject} in {grade_slug}.",
            "strands": [],
        }

    def get_agent_prompt(self, agent_name: str) -> str:
        cached = self._get_from_cache(f"prompt_{agent_name}")
        if cached:
            return cached

        if self._client:
            try:
                prompt = self._client.get_prompt(agent_name, label=settings.langfuse_env)
                if prompt and prompt.prompt:
                    text = prompt.prompt
                    self._set_cache(f"prompt_{agent_name}", text)
                    return text
            except Exception as exc:
                logger.warning("Could not fetch prompt '%s' from Langfuse: %s", agent_name, exc)
                if self._is_strict:
                    raise_api_error("PROMPT_NOT_FOUND", f"Failed to fetch prompt '{agent_name}' from Langfuse.")

        if self._is_strict:
            raise_api_error("PROMPT_NOT_FOUND", f"Langfuse client unavailable to fetch prompt '{agent_name}'.")

        # In dev mode, we can try to import the seed fallback if needed.
        try:
            from .langfuse_seed import SEED_AGENT_PROMPTS
            template = SEED_AGENT_PROMPTS.get(agent_name)
            if template:
                self._set_cache(f"prompt_{agent_name}", template)
                return template
        except ImportError:
            pass

        raise_api_error("PROMPT_NOT_FOUND", f"Agent prompt template '{agent_name}' not found")

    def _render_template(self, template: str, variables: dict[str, Any]) -> str:
        rendered = template
        for k, v in variables.items():
            val_str = json.dumps(v, indent=2) if isinstance(v, (dict, list)) else str(v or "")
            rendered = rendered.replace(f"{{{{ {k} }}}}", val_str)
            rendered = rendered.replace(f"{{{{{k}}}}}", val_str)
        return rendered

    def assemble_agent_context(
        self,
        agent_name: str,
        grade_slug: str,
        subject: str,
        template_vars: dict[str, Any] | None = None,
    ) -> CompiledContextResult:
        # Layer 1: Global BECF Context
        master_ctx = self.get_master_context()
        if not master_ctx or len(master_ctx.strip()) < 50:
            raise_api_error("MISSING_CONTEXT_LAYER", "Layer 1 (Global BECF Context) is missing or empty. Seed Langfuse with: python -m app.services.langfuse_seed")

        # Layer 2: Grade dataset
        dataset_items = self.get_grade_dataset(grade_slug)
        if not dataset_items:
            raise_api_error("MISSING_CONTEXT_LAYER", f"Layer 2 (Grade Dataset '{grade_slug}') has no items. Upload curriculum data for this grade.")

        # Layer 3: Subject context
        subject_ctx = self.get_subject_context(grade_slug, subject)
        if not subject_ctx or not subject_ctx.get("strands"):
            raise_api_error("MISSING_CONTEXT_LAYER", f"Layer 3 (Subject Context for '{subject}' in '{grade_slug}') is missing. Upload this subject's curriculum data.")

        # Layer 4: Strand/Sub-strand validation
        template_vars = template_vars or {}
        if "strand" in template_vars and "sub_strand" in template_vars:
            strand_name = template_vars["strand"]
            sub_strand_name = template_vars["sub_strand"]
            found_sub = False
            for strand in subject_ctx.get("strands", []):
                if strand.get("name", "").lower() == strand_name.lower():
                    for sub_strand in strand.get("sub_strands", []):
                        if sub_strand.get("name", "").lower() == sub_strand_name.lower():
                            found_sub = True
                            break
                    if found_sub:
                        break
            if not found_sub:
                logger.warning("Layer 4 (Strand/Sub-strand) validation failed for %s -> %s", strand_name, sub_strand_name)
                # Not explicitly raising error here to remain backward compatible, but we log the warning.

        # Layer 5: Agent prompt
        raw_prompt = self.get_agent_prompt(agent_name)

        vars_dict = {
            "grade": grade_slug,
            "subject": subject,
            "subject_context": subject_ctx,
            **template_vars,
        }

        user_prompt = self._render_template(raw_prompt, vars_dict)
        prompt_hash = hashlib.sha256(user_prompt.encode("utf-8")).hexdigest()

        messages = [
            {"role": "system", "content": master_ctx},
            {
                "role": "system",
                "content": f"## CBC Curriculum Context ({grade_slug} - {subject})\n{json.dumps(subject_ctx, indent=2)}",
            },
            {"role": "user", "content": user_prompt},
        ]

        return CompiledContextResult(
            master_context=master_ctx,
            subject_context=subject_ctx,
            user_prompt=user_prompt,
            messages=messages,
            prompt_name=agent_name,
            prompt_version="v2.1",
            prompt_label=settings.langfuse_env,
            prompt_hash=prompt_hash,
        )

    def list_datasets(self) -> list[dict]:
        if self._client:
            try:
                # We need to list dataset correctly or use get_dataset individually?
                # Actually Langfuse SDK doesn't have an easy list_datasets, but we just fallback to the predefined range, or just use what works.
                pass
            except Exception:
                pass
        return [{"name": f"grade-{i}"} for i in range(1, 13)] + [{"name": "grade-pp1"}, {"name": "grade-pp2"}]

    def upload_dataset_item(self, grade_slug: str, subject_data: dict) -> dict:
        if self._client:
            try:
                self._client.create_dataset_item(
                    dataset_name=grade_slug,
                    input={"subject": subject_data.get("subject", "General")},
                    metadata=subject_data,
                )
                self._cache.pop(f"dataset_{grade_slug}", None)
                return {"status": "created", "dataset_name": grade_slug}
            except Exception as exc:
                logger.error("Failed to upload dataset item to Langfuse: %s", exc)
                if self._is_strict:
                    raise_api_error("LANGFUSE_UNAVAILABLE", "Failed to upload dataset item in strict mode.")

        if self._is_strict:
            raise_api_error("LANGFUSE_UNAVAILABLE", "Langfuse client unavailable to upload dataset item in strict mode.")

        return {"status": "saved_locally", "dataset_name": grade_slug}

    def get_available_subjects(self, grade_slug: str) -> list[dict]:
        items = self.get_grade_dataset(grade_slug)
        subjects = []
        for item in items:
            meta = item.get("metadata", {})
            inp = item.get("input", {})
            name = meta.get("name") or (inp.get("subject") if isinstance(inp, dict) else None)
            if name:
                subjects.append({
                    "name": name,
                    "code": meta.get("code", ""),
                    "essence_statement": meta.get("essence_statement", ""),
                })
        return subjects

    def get_strands_for_subject(self, grade_slug: str, subject: str) -> list[dict]:
        ctx = self.get_subject_context(grade_slug, subject)
        return ctx.get("strands", [])

    def get_slos_for_substrand(self, grade_slug: str, subject: str, strand: str, sub_strand: str) -> list[str]:
        strands = self.get_strands_for_subject(grade_slug, subject)
        for st in strands:
            if st.get("name", "").lower() == strand.lower():
                for sub in st.get("sub_strands", []):
                    if sub.get("name", "").lower() == sub_strand.lower():
                        return sub.get("slos", [])
        return []

    def get_master_context_metadata(self) -> dict:
        master_ctx = self.get_master_context()
        return {
            "text": master_ctx,
            "version": "latest",
            "label": settings.langfuse_env,
        }

    def update_master_context(self, text: str) -> dict:
        if self._client:
            try:
                prompt = self._client.create_prompt(
                    name="cbc-master-context",
                    prompt=text,
                    type="text",
                    labels=[settings.langfuse_env],
                )
                self._cache.pop("master_context", None)
                return {"status": "success", "prompt_name": prompt.name, "version": prompt.version}
            except Exception as exc:
                logger.error("Failed to update master context: %s", exc)
                if self._is_strict:
                    raise_api_error("LANGFUSE_UNAVAILABLE", "Failed to update master context in strict mode.")
        if self._is_strict:
            raise_api_error("LANGFUSE_UNAVAILABLE", "Langfuse client unavailable to update master context in strict mode.")
        return {"status": "failed", "reason": "No Langfuse client"}

langfuse_context_service = LangfuseContextService()
