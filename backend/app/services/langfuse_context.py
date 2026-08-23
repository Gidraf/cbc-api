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
            # Try BECF first with multiple standard labels (production, latest, prod, settings.langfuse_env)
            prompt_names = ["BECF", "cbc-master-context"]
            labels_to_try = [settings.langfuse_env, "production", "latest", "prod"]

            for pname in prompt_names:
                for lbl in labels_to_try:
                    try:
                        prompt = self._client.get_prompt(pname, label=lbl)
                        if prompt and prompt.prompt:
                            text = prompt.compile() if hasattr(prompt, "compile") else prompt.prompt
                            self._set_cache("master_context", text)
                            logger.info("Loaded master context from Langfuse prompt '%s' (label: '%s')", pname, lbl)
                            return text
                    except Exception:
                        continue
                # Also try unlabelled latest
                try:
                    prompt = self._client.get_prompt(pname)
                    if prompt and prompt.prompt:
                        text = prompt.compile() if hasattr(prompt, "compile") else prompt.prompt
                        self._set_cache("master_context", text)
                        logger.info("Loaded master context from Langfuse prompt '%s' (default)", pname)
                        return text
                except Exception:
                    pass

            if self._is_strict:
                raise_api_error("LANGFUSE_UNAVAILABLE", "Failed to fetch master context 'BECF' from Langfuse in strict mode.")

        if self._is_strict:
            raise_api_error("LANGFUSE_UNAVAILABLE", "Langfuse client unavailable in strict mode.")

        self._set_cache("master_context", _DEV_FALLBACK_MASTER_CONTEXT)
        return _DEV_FALLBACK_MASTER_CONTEXT

    def fetch_raw_datasets_from_langfuse(self, dataset_names: list[str] | None = None) -> list[dict[str, Any]]:
        """Fetches all raw dataset items directly from Langfuse project (e.g. cbc/datasets)."""
        names_to_try = dataset_names or ["cbc/datasets", "cbc-datasets", "cbc_datasets", "datasets", "curriculum", "grade-dte", "grade-7"]
        found_items: list[dict[str, Any]] = []

        if self._client:
            for name in names_to_try:
                try:
                    dataset = self._client.get_dataset(name=name)
                    if dataset and dataset.items:
                        logger.info("Found %d raw dataset items in Langfuse dataset '%s'", len(dataset.items), name)
                        for item in dataset.items:
                            # Package the raw payload as-is
                            inp = item.input if isinstance(item.input, dict) else {"input": item.input}
                            out = item.expected_output or (inp.get("output") if isinstance(inp, dict) else "") or ""
                            meta = item.metadata or {}
                            combined = {
                                "dataset_name": name,
                                "item_id": item.id,
                                **inp,
                                "output": out if out else (inp.get("output") or meta.get("output") or ""),
                                "metadata": meta,
                            }
                            found_items.append(combined)
                except Exception as exc:
                    logger.debug("Dataset '%s' not present in Langfuse: %s", name, exc)

        return found_items

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
                logger.debug("Dataset '%s' not present in Langfuse: %s", grade_slug, exc)

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
                    "strands": [],
                },
            }
        ]
        self._set_cache(cache_key, fallback)
        return fallback

    def get_subject_context(self, grade_slug: str, subject: str) -> dict:
        from ..infra.db import fetch_all
        rows = fetch_all(
            """
            SELECT strand_name, sub_strand_id, sub_strand_name, allocated_hours, slos,
                   learning_experiences, key_inquiry_questions, required_diagrams,
                   experiments, pedagogical_guidance, prompt_context
            FROM curriculum_substrands
            WHERE (grade = :grade OR :grade = '' OR :grade IS NULL) AND LOWER(subject) = LOWER(:subject)
            ORDER BY strand_id ASC, sub_strand_id ASC
            """,
            {"grade": grade_slug, "subject": subject},
        )

        if rows:
            strands_map: dict[str, list[dict]] = {}
            for r in rows:
                s_name = r["strand_name"]
                if s_name not in strands_map:
                    strands_map[s_name] = []
                strands_map[s_name].append({
                    "name": r["sub_strand_name"],
                    "hours": r["allocated_hours"],
                    "slos": [item.get("text", "") if isinstance(item, dict) else str(item) for item in (r["slos"] or [])],
                    "diagrams_required": r["required_diagrams"] or [],
                    "experiments": r["experiments"] or [],
                    "kiqs": r["key_inquiry_questions"] or [],
                    "prompt_package": r["prompt_context"] or {},
                })

            strands_tree = [{"name": k, "sub_strands": v} for k, v in strands_map.items()]
            return {
                "subject": subject,
                "grade": grade_slug,
                "strands": strands_tree,
                "source": "curriculum_blueprint_db",
            }

        # Fallback to dataset items
        dataset_items = self.get_grade_dataset(grade_slug)
        for item in dataset_items:
            inp = item.get("input", {})
            if isinstance(inp, dict) and inp.get("subject", "").lower() == subject.lower():
                return item.get("metadata", {})
            if isinstance(inp, str) and subject.lower() in inp.lower():
                return item.get("metadata", {})

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
        template_vars: dict | None = None,
    ) -> CompiledContextResult:
        # Layer 1: Global BECF Context
        master_ctx = self.get_master_context()
        if not master_ctx or len(master_ctx.strip()) < 20:
            master_ctx = _DEV_FALLBACK_MASTER_CONTEXT

        # Layer 2 & 3: Subject & Sub-strand Blueprint Context
        subject_ctx = self.get_subject_context(grade_slug, subject)

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
        from ..infra.db import fetch_all
        db_grades = fetch_all("SELECT DISTINCT grade FROM curriculum_designs ORDER BY grade ASC")
        if not db_grades:
            db_grades = fetch_all("SELECT DISTINCT grade FROM curriculum_substrands ORDER BY grade ASC")

        names = [r["grade"] for r in db_grades if r.get("grade")]
        if not names:
            names = ["grade-dte", "grade-7", "grade-8", "grade-9", "grade-4", "grade-pp1"]

        return [{"name": n} for n in names]

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
                logger.warning("Failed to upload dataset item to Langfuse: %s", exc)

        return {"status": "saved_locally", "dataset_name": grade_slug}

    def get_available_subjects(self, grade_slug: str) -> list[dict]:
        from ..infra.db import fetch_all
        db_subs = fetch_all(
            """
            SELECT DISTINCT subject, subject_code, essence_statement
            FROM curriculum_designs
            WHERE grade = :grade
            ORDER BY subject ASC
            """,
            {"grade": grade_slug},
        )
        if not db_subs:
            db_subs = fetch_all(
                """
                SELECT DISTINCT subject, '' as subject_code, '' as essence_statement
                FROM curriculum_substrands
                WHERE grade = :grade
                ORDER BY subject ASC
                """,
                {"grade": grade_slug},
            )

        if db_subs:
            return [
                {
                    "name": r["subject"],
                    "code": r.get("subject_code", ""),
                    "essence_statement": r.get("essence_statement", ""),
                }
                for r in db_subs
            ]

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
                    name="BECF",
                    prompt=text,
                    type="text",
                    labels=["production", "latest", "prod", settings.langfuse_env],
                )
                try:
                    # Also keep alias in sync
                    self._client.create_prompt(
                        name="cbc-master-context",
                        prompt=text,
                        type="text",
                        labels=["production", "latest", "prod", settings.langfuse_env],
                    )
                except Exception:
                    pass
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
