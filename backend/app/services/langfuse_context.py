from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

from ..errors import raise_api_error
from ..settings import settings

logger = logging.getLogger("cbc-langfuse")


# A sub-strand's stored prompt_context carries the full instruction template for
# every downstream agent — notes, diagram, question, reviewer, both approvers.
# Those belong to those agents at their own call time; carried here they are
# ~90% of the subject context by size (19k tokens on a full PP1 design) and no
# generator reads another agent's prompt as curriculum. Keep the curriculum
# facts, drop the templates.
_TEMPLATE_KEYS_SUFFIX = "_prompt"



def focus_subject_context(subject_ctx: dict, strand: str) -> dict:
    """Narrow the stored blueprint to the strand being worked on.

    A generator asked about Language Activities was handed, as a SYSTEM message,
    the strands of Christian Religious Education — higher-authority context
    contradicting the actual request. Worse, it modelled by example what an SLO
    looks like, and those stored SLOs included fragments like "," and "6".

    Sending nothing is better than sending a contradiction: an absent blueprint
    makes the agent read the design, which is what it should have been doing.
    """
    if not isinstance(subject_ctx, dict) or not strand:
        return subject_ctx

    wanted = re.sub(r"[^a-z0-9]+", " ", str(strand).lower()).strip()
    if not wanted:
        return subject_ctx

    kept = []
    for entry in subject_ctx.get("strands") or []:
        name = re.sub(r"[^a-z0-9]+", " ", str(entry.get("name") or "").lower()).strip()
        if not name:
            continue
        if name == wanted or name in wanted or wanted in name:
            kept.append(entry)

    focused = {**subject_ctx, "strands": kept, "focused_on": strand}
    if not kept:
        focused["note"] = (
            f"No stored blueprint matches the strand '{strand}' for this learning area. "
            "Read the curriculum design document instead; do not substitute another strand."
        )
    return focused


def focus_sub_strand_context(subject_ctx: dict, strand: str, sub_strand: str) -> dict:
    """Narrow the blueprint to ONE sub-strand, keeping its siblings by name only.

    Writing the guide for "Our God" was handed the full blueprint of all twelve
    CRE sub-strands — every outcome, every learning experience, and a
    `prompt_package` duplicating each field inside itself. 20,606 characters, of
    which about 18,000 described sub-strands the guide is not about.

    That budget is not free. The same prompt gave the model a 4,000-character
    EXCERPT of the design, cut mid-table, and then the quality gate scored its
    source grounding against all 31,689 characters. It scored 0.20, correctly:
    the model was shown a twentieth of the source and eighteen thousand
    characters about other sub-strands.

    Siblings are kept as bare names because a guide should know what comes
    before and after it — "do not pre-empt 1.2" needs 1.2 to have a name — and
    for nothing else.
    """
    focused = focus_subject_context(subject_ctx, strand)
    if not isinstance(focused, dict) or not sub_strand:
        return focused

    wanted = re.sub(r"[^a-z0-9]+", " ", str(sub_strand).lower()).strip()
    if not wanted:
        return focused

    narrowed = []
    siblings: list[str] = []
    for entry in focused.get("strands") or []:
        kept_subs = []
        for sub in entry.get("sub_strands") or []:
            name = re.sub(r"[^a-z0-9]+", " ", str(sub.get("name") or "").lower()).strip()
            if name and (name == wanted or name in wanted or wanted in name):
                # The stored package duplicates every field of the sub-strand
                # inside itself; one copy is a blueprint, two is padding.
                kept_subs.append({k: v for k, v in sub.items() if k != "prompt_package"})
            elif sub.get("name"):
                siblings.append(str(sub["name"]))
        narrowed.append({**entry, "sub_strands": kept_subs})

    return {
        **focused,
        "strands": narrowed,
        "focused_on_sub_strand": sub_strand,
        "other_sub_strands_in_this_strand": siblings,
        "note": (
            "Only the sub-strand being written is given in full. The others are "
            "named so this guide knows what precedes and follows it, and for "
            "nothing else — do not teach their content here."
        ),
    }


def context_safe_package(package: Any) -> dict:
    """The curriculum half of a stored prompt package, without the templates."""
    if not isinstance(package, dict):
        return {}
    return {k: v for k, v in package.items() if not k.endswith(_TEMPLATE_KEYS_SUFFIX)}


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

    def ensure_master_context_seeded(self) -> None:
        """Ensures that BECF master prompt and core agent prompts exist in Langfuse on startup."""
        try:
            from .langfuse_seed import seed_langfuse
            seed_langfuse()
        except Exception as exc:
            logger.info("Automatic Langfuse prompt seed completed or skipped: %s", exc)

    def get_master_context(self) -> str:
        cached = self._get_from_cache("master_context")
        if cached:
            return cached

        from .langfuse_seed import SEED_MASTER_CONTEXT

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
                            if text and len(text.strip()) > 50:
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
                        if text and len(text.strip()) > 50:
                            self._set_cache("master_context", text)
                            logger.info("Loaded master context from Langfuse prompt '%s' (default)", pname)
                            return text
                except Exception:
                    pass

            # Auto-seed to Langfuse if missing
            try:
                self._client.create_prompt(
                    name="BECF",
                    prompt=SEED_MASTER_CONTEXT,
                    type="text",
                    labels=["production", "latest", "prod", "staging", "dev"],
                )
                logger.info("Auto-seeded BECF prompt to Langfuse.")
            except Exception as exc:
                logger.info("Auto-seed BECF skipped or already exists: %s", exc)

        self._set_cache("master_context", SEED_MASTER_CONTEXT)
        return SEED_MASTER_CONTEXT

    def fetch_raw_datasets_from_langfuse(self) -> list[dict[str, Any]]:
        """Fetches all raw dataset items directly from Langfuse project by querying the real datasets list first."""
        import httpx
        from urllib.parse import quote

        found_items: list[dict[str, Any]] = []

        if not (settings.langfuse_public_key and settings.langfuse_secret_key):
            logger.info("Langfuse credentials not configured; skipping Langfuse dataset sync.")
            return found_items

        base_url = settings.langfuse_host.rstrip("/")
        auth = (settings.langfuse_public_key, settings.langfuse_secret_key)

        try:
            # 1. Discover all datasets actually present in Langfuse project
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(f"{base_url}/api/public/datasets?limit=100", auth=auth)
                if resp.status_code != 200:
                    logger.warning("Could not list datasets from Langfuse (HTTP %d): %s", resp.status_code, resp.text[:200])
                    return found_items

                res_json = resp.json()
                datasets_list = res_json.get("data", []) if isinstance(res_json, dict) else []

                logger.info("Found %d datasets in Langfuse project.", len(datasets_list))

                # 2. Fetch items for each real dataset
                for ds in datasets_list:
                    ds_name = ds.get("name")
                    if not ds_name:
                        continue

                    # Fetch dataset details & items
                    encoded_name = quote(ds_name, safe="")
                    ds_resp = client.get(f"{base_url}/api/public/datasets/{encoded_name}", auth=auth)
                    if ds_resp.status_code == 200:
                        ds_data = ds_resp.json()
                        items = ds_data.get("items", [])
                        logger.info("Dataset '%s' contains %d items.", ds_name, len(items))

                        for itm in items:
                            inp = itm.get("input") if isinstance(itm.get("input"), dict) else {"input": itm.get("input")}
                            out = itm.get("expectedOutput") or (inp.get("output") if isinstance(inp, dict) else "") or ""
                            meta = itm.get("metadata") or {}

                            found_items.append({
                                "dataset_name": ds_name,
                                "item_id": itm.get("id"),
                                **inp,
                                "output": out if out else (inp.get("output") or meta.get("output") or ""),
                                "metadata": meta,
                            })

        except Exception as exc:
            logger.warning("Error fetching datasets from Langfuse: %s", exc)

        return found_items

    def _fetch_dataset_items_http(self, dataset_name: str) -> list[dict]:
        """Read a dataset's items straight from the Langfuse HTTP API.

        The dataset detail endpoint returns items inline; the separate
        /dataset-items collection is not served by every Langfuse version and
        answers with an empty list rather than an error.
        """
        if not (settings.langfuse_public_key and settings.langfuse_secret_key):
            return []

        try:
            import httpx
            from urllib.parse import quote

            base_url = settings.langfuse_host.rstrip("/")
            auth = (settings.langfuse_public_key, settings.langfuse_secret_key)
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(
                    f"{base_url}/api/public/datasets/{quote(dataset_name, safe='')}", auth=auth
                )
            if resp.status_code != 200:
                return []

            return [
                {
                    "id": item.get("id"),
                    "input": item.get("input"),
                    "expected_output": item.get("expectedOutput") or item.get("expected_output") or "",
                    "metadata": item.get("metadata") or {},
                }
                for item in (resp.json().get("items") or [])
            ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("HTTP read of dataset '%s' failed: %s", dataset_name, exc)
            return []

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
                # Not a routine event: a missing grade dataset means the whole
                # pipeline for that grade has nothing to work from. Logged at
                # debug, this was invisible while the fallback below made the
                # console look populated.
                logger.warning(
                    "Langfuse SDK could not read dataset '%s' (%s); trying the HTTP API.",
                    grade_slug, exc,
                )

        # The SDK and the HTTP API do not always agree — fetch_raw_datasets_from_langfuse
        # reads datasets over HTTP successfully in deployments where the SDK call
        # returns nothing. Falling back to the proven path costs one request and
        # removes a whole class of "the data is there but the app cannot see it".
        http_items = self._fetch_dataset_items_http(grade_slug)
        if http_items:
            self._set_cache(cache_key, http_items)
            return http_items

        logger.warning(
            "No dataset named '%s' in Langfuse. Curriculum designs must be uploaded "
            "to one dataset per grade before this grade can be produced.",
            grade_slug,
        )

        if self._is_strict:
            # Never invent curriculum in production. An empty grade is the truth
            # and shows up as 0 coverage rather than as a subject nobody ingested.
            self._set_cache(cache_key, [])
            return []

        fallback = [
            {
                "id": f"itm_{grade_slug}_default",
                "is_placeholder": True,
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
        alt_grade = grade_slug.replace("grade-", "") if grade_slug.startswith("grade-") else f"grade-{grade_slug}"
        rows = fetch_all(
            """
            SELECT strand_name, sub_strand_id, sub_strand_name, allocated_hours, slos,
                   learning_experiences, key_inquiry_questions, required_diagrams,
                   experiments, pedagogical_guidance, prompt_context,
                   theme, pertinent_contemporary_issues, link_to_other_learning_areas,
                   source_pages
            FROM curriculum_substrands
            WHERE (grade = :grade OR grade = :alt_grade OR :grade = '' OR :grade IS NULL) AND LOWER(subject) = LOWER(:subject)
            ORDER BY strand_id ASC, sub_strand_id ASC
            """,
            {"grade": grade_slug, "alt_grade": alt_grade, "subject": subject},
        )

        strands_map: dict[str, list[dict]] = {}
        seen_ss: set[str] = set()

        for r in rows:
            s_name = r["strand_name"] or "Strand"
            if s_name not in strands_map:
                strands_map[s_name] = []
            ss_name = r["sub_strand_name"]
            if ss_name:
                seen_ss.add(ss_name.lower().strip())
                strands_map[s_name].append({
                    "name": ss_name,
                    "theme": r.get("theme") or "",
                    "hours": r["allocated_hours"],
                    "pertinent_contemporary_issues": r.get("pertinent_contemporary_issues") or [],
                    "link_to_other_learning_areas": r.get("link_to_other_learning_areas") or "",
                    "source_pages": r.get("source_pages") or [],
                    "slos": [item.get("text", "") if isinstance(item, dict) else str(item) for item in (r["slos"] or [])],
                    "diagrams_required": r["required_diagrams"] or [],
                    "experiments": r["experiments"] or [],
                    "kiqs": r["key_inquiry_questions"] or [],
                    "prompt_package": context_safe_package(r["prompt_context"]),
                })

        # Also search curriculum_designs for additional strands/substrands
        design_rows = fetch_all(
            """
            SELECT metadata, raw_payload FROM curriculum_designs
            WHERE (REPLACE(LOWER(grade), 'grade-', '') = REPLACE(LOWER(:grade), 'grade-', '')) AND LOWER(subject) = LOWER(:subject)
            """,
            {"grade": grade_slug, "alt_grade": alt_grade, "subject": subject},
        )
        for dr in design_rows:
            meta = dr.get("metadata") or {}
            raw = dr.get("raw_payload") or {}
            strands_list = meta.get("strands") or raw.get("strands") or []
            for st in strands_list:
                st_name = st.get("name") or st.get("strand_name") or "Strand"
                if st_name not in strands_map:
                    strands_map[st_name] = []
                for ss in st.get("sub_strands") or []:
                    ss_name = ss if isinstance(ss, str) else (ss.get("sub_strand_name") or ss.get("name") or ss.get("title"))
                    if ss_name and ss_name.lower().strip() not in seen_ss:
                        seen_ss.add(ss_name.lower().strip())
                        strands_map[st_name].append({
                            "name": ss_name,
                            "hours": (ss.get("allocated_time") or ss.get("allocated_hours") or ss.get("hours") or "") if isinstance(ss, dict) else "",
                            "slos": (ss.get("slos") or []) if isinstance(ss, dict) else [],
                            "diagrams_required": (ss.get("required_diagrams") or []) if isinstance(ss, dict) else [],
                            "experiments": (ss.get("experiments") or []) if isinstance(ss, dict) else [],
                            "kiqs": (ss.get("key_inquiry_questions") or ss.get("kiqs") or []) if isinstance(ss, dict) else [],
                            "prompt_package": {},
                        })

        if strands_map:
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

    def get_prompt(self, name: str, label: str | None = None, version: int | None = None) -> Any:
        """Fetches a prompt object from Langfuse SDK with fallback label cascade and seed defaults."""
        from .langfuse_seed import SEED_AGENT_PROMPTS, SEED_MASTER_CONTEXT

        if self._client:
            labels_to_try = [label, settings.langfuse_env, "production", "latest", "prod", "staging", "dev"] if label else [settings.langfuse_env, "production", "latest", "prod", "staging", "dev"]

            # Try by explicit version if provided
            if version is not None:
                try:
                    p = self._client.get_prompt(name, version=version)
                    if p:
                        return p
                except Exception as exc:
                    logger.debug("Prompt %s v%s lookup: %s", name, version, exc)

            # Try by label cascade
            for lbl in labels_to_try:
                if not lbl:
                    continue
                try:
                    p = self._client.get_prompt(name, label=lbl)
                    if p:
                        return p
                except Exception:
                    continue

            # Try unlabelled default
            try:
                p = self._client.get_prompt(name)
                if p:
                    return p
            except Exception:
                pass

        # Local seed fallback
        fallback_text = SEED_MASTER_CONTEXT if name in {"BECF", "cbc-master-context"} else SEED_AGENT_PROMPTS.get(name, "")
        if fallback_text:
            class LocalPromptMock:
                def __init__(self, prompt_str: str, p_name: str) -> None:
                    self.prompt = prompt_str
                    self.name = p_name
                    self.version = 1

                def compile(self, **kwargs) -> str:
                    rendered = self.prompt
                    for k, v in kwargs.items():
                        val_str = json.dumps(v, indent=2) if isinstance(v, (dict, list)) else str(v or "")
                        rendered = rendered.replace(f"{{{{ {k} }}}}", val_str).replace(f"{{{{{k}}}}}", val_str)
                    return rendered

            return LocalPromptMock(fallback_text, name)

        if self._is_strict:
            raise_api_error("PROMPT_NOT_FOUND", f"Prompt '{name}' not found in Langfuse in strict mode.")

        raise_api_error("PROMPT_NOT_FOUND", f"Prompt '{name}' not found in Langfuse or seed templates.")

    def compile_prompt(
        self,
        name: str,
        variables: dict[str, Any],
        label: str | None = None,
        version: int | None = None,
    ) -> tuple[str, str, str]:
        """Dynamically fetches and compiles a prompt template from Langfuse with variables."""
        prompt_obj = self.get_prompt(name, label=label, version=version)
        version_str = str(getattr(prompt_obj, "version", "latest"))
        label_str = label or settings.langfuse_env or "latest"

        # Format variables so dicts and lists are clean JSON strings for mustache/jinja templates
        formatted_vars: dict[str, Any] = {}
        for k, v in variables.items():
            if isinstance(v, (dict, list)):
                formatted_vars[k] = json.dumps(v, indent=2)
            else:
                formatted_vars[k] = v

        try:
            if hasattr(prompt_obj, "compile"):
                compiled_text = prompt_obj.compile(**formatted_vars)
            elif hasattr(prompt_obj, "prompt"):
                compiled_text = self._render_template(prompt_obj.prompt, formatted_vars)
            else:
                compiled_text = str(prompt_obj)
        except Exception as exc:
            logger.warning("Error compiling Langfuse prompt '%s': %s. Falling back to template rendering.", name, exc)
            raw_text = getattr(prompt_obj, "prompt", str(prompt_obj))
            compiled_text = self._render_template(raw_text, formatted_vars)

        return compiled_text, version_str, label_str

    # Langfuse has no folders: a prompt's NAME is its path, and a slash in it
    # is what the console renders as a folder. Nineteen prompts in one flat
    # list is a list nobody edits; the same nineteen under `generate/`,
    # `review/` and `extract/` is a place to work.
    #
    # Both names are accepted, foldered first. Renaming outright would orphan
    # every edit already made in Langfuse against the old name — which is the
    # work this is supposed to make easier, thrown away to make it tidier.
    FOLDERS: dict[str, str] = {
        "curriculum-extractor": "extract/curriculum",
        "grade-scope-extractor": "extract/grade-scope",
        "rubric-generator": "extract/rubrics",
        "strand-generator": "structure/strands",
        "substrand-generator": "structure/sub-strands",
        "slo-aligner": "structure/slo-alignment",
        "note-generator": "generate/lesson-plan",
        "diagram-generator": "generate/diagrams",
        "media-prompt-generator": "generate/photos-and-videos",
        "simulation-generator": "generate/simulations",
        "activity-generator": "generate/activities",
        "question-generator": "generate/questions",
        "content-repair": "generate/repair",
        "layer-reviewer": "review/layered",
        "reviewer-panel": "review/panel",
        "approver-agent1": "review/approver-1",
        "approver-agent2": "review/approver-2",
    }

    def folder_name(self, agent_name: str) -> str:
        """Where this prompt lives in the Langfuse console."""
        return self.FOLDERS.get(agent_name, agent_name)

    def get_agent_prompt(self, agent_name: str) -> str:
        """The prompt, by its foldered name if there is one, else its flat name.

        Order matters: an operator who has edited `generate/lesson-plan` should
        get that edit, and one who has only ever edited `note-generator` should
        keep getting theirs. Falling back the other way would silently serve a
        stale prompt to whoever migrated first.
        """
        foldered = self.FOLDERS.get(agent_name)
        if foldered:
            try:
                found = self.get_prompt(foldered)
                text = getattr(found, "prompt", "")
                if text and "{{" in text:
                    return text
            except Exception as exc:  # noqa: BLE001
                logger.debug("No foldered prompt %s (%s); using %s.",
                             foldered, exc, agent_name)
        prompt_obj = self.get_prompt(agent_name)
        return getattr(prompt_obj, "prompt", str(prompt_obj))

    def _render_template(
        self, template: str, variables: dict[str, Any], partial: bool = False
    ) -> str:
        """Fill a prompt template.

        ``partial`` is for building a template that will be filled later — the
        extractor stores per-sub-strand prompts at ingest time with only the
        curriculum variables bound, and the rest MUST survive as placeholders.
        Stripping them there both destroyed the stored template and logged a
        warning for a case that is working exactly as intended.
        """
        rendered = template
        for k, v in variables.items():
            val_str = json.dumps(v, indent=2) if isinstance(v, (dict, list)) else str(v or "")
            rendered = rendered.replace(f"{{{{ {k} }}}}", val_str)
            rendered = rendered.replace(f"{{{{{k}}}}}", val_str)

        # A placeholder the caller forgot to supply used to reach the model as the
        # literal text "{{ level_register }}" — a prompt that silently told the
        # agent nothing about its audience while looking complete in the console.
        # Strip it and say which one, so the gap is visible instead of invisible.
        missing = sorted(set(re.findall(r"\{\{\s*(\w+)\s*\}\}", rendered)))
        if missing and partial:
            logger.debug(
                "Template stored with %d placeholder(s) left for later: %s",
                len(missing), ", ".join(missing),
            )
        elif missing:
            logger.warning(
                "Prompt rendered with %d unsupplied variable(s): %s. They have been "
                "removed rather than sent to the model as literal text.",
                len(missing), ", ".join(missing),
            )
            rendered = re.sub(r"\{\{\s*\w+\s*\}\}", "", rendered)
        return rendered

    def assemble_agent_context(
        self,
        agent_name: str,
        grade_slug: str,
        subject: str,
        template_vars: dict | None = None,
        focus_strand: str = "",
        focus_sub_strand: str = "",
    ) -> CompiledContextResult:
        # Layer 1: Global BECF Context dynamically loaded from Langfuse
        master_ctx = self.get_master_context()

        # Layer 2 & 3: Subject & Sub-strand Blueprint Context
        subject_ctx = self.get_subject_context(grade_slug, subject)
        if focus_strand and focus_sub_strand:
            # Writing ONE sub-strand's guide does not need the other eleven in
            # full; that budget belongs to the design itself.
            subject_ctx = focus_sub_strand_context(
                subject_ctx, focus_strand, focus_sub_strand
            )
        elif focus_strand:
            subject_ctx = focus_subject_context(subject_ctx, focus_strand)

        vars_dict = {
            "grade": grade_slug,
            "subject": subject,
            "subject_context": subject_ctx,
            **(template_vars or {}),
        }

        # Dynamic prompt compilation directly from Langfuse
        user_prompt, prompt_version, prompt_label = self.compile_prompt(agent_name, vars_dict)
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
            prompt_version=prompt_version,
            prompt_label=prompt_label,
            prompt_hash=prompt_hash,
        )

    def list_datasets(self) -> list[dict]:
        """Grades in CBC progression order, lowest first.

        ``ORDER BY grade`` on a text column sorts grade-1, grade-10, grade-11,
        grade-12, grade-2, so the ordering is applied in Python against the
        canonical ordinal instead.
        """
        from ..infra.db import fetch_all
        from .curriculum_catalogue import all_grade_slugs, expected_design_count
        from .grade_order import describe, normalize_grade

        # Every grade KICD publishes for, not only the ones already ingested.
        # Listing only what is in the database hides the grades that most need
        # work, and the old fallback list happened to name exactly the six a
        # since-fixed parser bug could produce.
        counts: dict[str, int] = {}
        for row in fetch_all(
            "SELECT grade, COUNT(*) AS n FROM curriculum_designs GROUP BY grade"
        ):
            slug = normalize_grade(row.get("grade"))
            if slug:
                counts[slug] = counts.get(slug, 0) + int(row.get("n") or 0)

        processed: dict[str, int] = {}
        for row in fetch_all(
            "SELECT grade, COUNT(*) AS n FROM dataset_ingest_status "
            "WHERE status = 'ingested' GROUP BY grade"
        ) or []:
            slug = normalize_grade(row.get("grade"))
            if slug:
                processed[slug] = processed.get(slug, 0) + int(row.get("n") or 0)

        if not counts:
            for row in fetch_all(
                "SELECT DISTINCT grade FROM curriculum_substrands"
            ):
                slug = normalize_grade(row.get("grade"))
                if slug:
                    counts.setdefault(slug, 0)

        datasets = []
        for slug in all_grade_slugs():
            ingested = counts.get(slug, 0)
            expected = expected_design_count(slug)
            datasets.append({
                "name": slug,
                **describe(slug),
                "design_count": ingested,
                "expected_design_count": expected,
                # How many documents were PROCESSED, which is a different fact
                # from how many designs came out of them. A grade reading "16
                # of 16 ingested" beside "1/16" had no way to show that the
                # two numbers count different things.
                "ingested_count": processed.get(slug, 0),
                "has_data": ingested > 0,
            })

        # A grade ingested under a slug outside the published ladder still has
        # to be reachable, or its content becomes invisible.
        for slug, ingested in sorted(counts.items()):
            if slug not in {d["name"] for d in datasets}:
                datasets.append({
                    "name": slug,
                    **describe(slug),
                    "design_count": ingested,
                    "expected_design_count": 0,
                    "ingested_count": processed.get(slug, 0),
                    "has_data": ingested > 0,
                })

        return datasets

    @staticmethod
    def blueprint_dataset_name(grade_slug: str) -> str:
        """Where parsed designs are written back for provenance.

        Deliberately NOT the grade dataset. That one holds the raw curriculum
        text waiting to be ingested; writing results into it mixes input and
        output in one namespace, and the results — which carry no document text
        — then look like empty documents queued for processing.
        """
        return f"{grade_slug}-blueprints"

    def upload_dataset_item(self, grade_slug: str, subject_data: dict) -> dict:
        dataset_name = self.blueprint_dataset_name(grade_slug)
        if self._client:
            try:
                # Langfuse 404s when writing an item to a dataset that does not
                # exist yet, so make sure it does. Creating an existing dataset
                # is a no-op.
                try:
                    self._client.create_dataset(name=dataset_name)
                except Exception:
                    pass

                design_id = str((subject_data.get("metadata") or {}).get("design_id") or "").strip()
                self._client.create_dataset_item(
                    dataset_name=dataset_name,
                    # Deterministic id: re-ingesting a design updates its record
                    # instead of leaving another copy behind on every run.
                    id=design_id or None,
                    input={
                        "subject": subject_data.get("subject", "General"),
                        "grade": grade_slug,
                        "design_id": design_id,
                    },
                    metadata=subject_data,
                )
                self._cache.pop(f"dataset_{dataset_name}", None)
                return {"status": "created", "dataset_name": dataset_name}
            except Exception as exc:
                logger.warning("Failed to upload dataset item to Langfuse: %s", exc)

        return {"status": "saved_locally", "dataset_name": dataset_name}

    def get_available_subjects(self, grade_slug: str) -> list[dict]:
        from ..infra.db import fetch_all
        db_subs = fetch_all(
            """
            SELECT DISTINCT subject, subject_code, essence_statement
            FROM curriculum_designs
            WHERE REPLACE(LOWER(grade), 'grade-', '') = REPLACE(LOWER(:grade), 'grade-', '')
            ORDER BY subject ASC
            """,
            {"grade": grade_slug},
        )
        if not db_subs:
            db_subs = fetch_all(
                """
                SELECT DISTINCT subject, '' as subject_code, '' as essence_statement
                FROM curriculum_substrands
                WHERE REPLACE(LOWER(grade), 'grade-', '') = REPLACE(LOWER(:grade), 'grade-', '')
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

    def get_expected_subjects(self, grade_slug: str) -> list[dict]:
        """Every subject KICD publishes for this grade, ingested or not.

        Ingested subjects are matched case-insensitively against the published
        list so a design can be seen to be missing rather than merely absent.
        """
        from .curriculum_catalogue import (
            GRADES_WITH_PATHWAY_LABELS,
            expected_design_count,
            expected_subjects,
        )

        ingested = self.get_available_subjects(grade_slug)
        by_key = {str(s.get("name", "")).strip().lower(): s for s in ingested if s.get("name")}

        rows: list[dict] = []
        for name in expected_subjects(grade_slug):
            match = by_key.pop(name.strip().lower(), None)
            rows.append({
                "name": match["name"] if match else name,
                "code": (match or {}).get("code", ""),
                "essence_statement": (match or {}).get("essence_statement", ""),
                "expected": True,
                "ingested": match is not None,
            })

        # Anything ingested that the published list does not name. For senior
        # school this is the normal case, not an anomaly: KICD lists pathways,
        # and the real learning area is read off each design's cover.
        for leftover in by_key.values():
            rows.append({
                "name": leftover.get("name", ""),
                "code": leftover.get("code", ""),
                "essence_statement": leftover.get("essence_statement", ""),
                "expected": False,
                "ingested": True,
            })

        return sorted(rows, key=lambda r: (not r["ingested"], r["name"].lower()))

    def get_grade_subject_summary(self, grade_slug: str) -> dict:
        from .curriculum_catalogue import GRADES_WITH_PATHWAY_LABELS, expected_design_count

        rows = self.get_expected_subjects(grade_slug)
        return {
            "subjects": rows,
            "ingested_count": sum(1 for r in rows if r["ingested"]),
            "expected_subject_count": sum(1 for r in rows if r["expected"]),
            "expected_design_count": expected_design_count(grade_slug),
            "subjects_are_pathways": grade_slug in GRADES_WITH_PATHWAY_LABELS,
        }

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
            "master_context": master_ctx,
            "prompt_name": "BECF",
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
