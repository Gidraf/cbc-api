from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from ..errors import raise_api_error
from ..infra.db import execute, fetch_all, fetch_one, to_json
from ..services.artifact_dna import artifact_dna_service
from ..services.langfuse_context import langfuse_context_service

logger = logging.getLogger("cbc-curriculum-extractor")


@dataclass(slots=True)
class ParsedSubstrand:
    strand_id: str
    strand_name: str
    sub_strand_id: str
    sub_strand_name: str
    allocated_hours: str
    slos: list[dict[str, str]]
    learning_experiences: list[str]
    key_inquiry_questions: list[str]
    core_competencies: list[str]
    values: list[str]
    assessment_rubrics: list[dict[str, Any]]
    required_diagrams: list[str]
    experiments: list[str]
    safety_hazards_to_check: list[str]
    pedagogical_guidance: dict[str, Any]
    prompt_package: dict[str, Any]
    raw_snippet: str
    substrand_dna_id: str = ""
    strand_dna_id: str = ""


@dataclass(slots=True)
class ParsedCurriculumDesign:
    design_id: str
    subject: str
    subject_code: str
    grade: str
    level: str
    essence_statement: str
    general_learning_outcomes: list[str]
    substrands: list[ParsedSubstrand]
    raw_payload: dict[str, Any]
    metadata: dict[str, Any]
    dataset_dna_id: str = ""
    subject_dna_id: str = ""


class CurriculumExtractorService:
    """Extracts curriculum specifications/blueprints from raw datasets.
    Generates tailored guidance, safety hazard criteria, and dynamic agent prompts
    (Generator, Reviewer with Hazard Check, Multi-Agent Approvers) for downstream pipeline stages."""

    def ingest_raw_curriculum(self, raw_input: dict[str, Any] | str) -> dict[str, Any]:
        raw_text = ""
        payload_meta = {}

        if isinstance(raw_input, dict):
            raw_text = raw_input.get("output") or raw_input.get("text") or raw_input.get("content") or ""
            payload_meta = {k: v for k, v in raw_input.items() if k not in {"output", "text", "content"}}
            if not raw_text and "raw_text" in raw_input:
                raw_text = raw_input["raw_text"]
        else:
            raw_text = str(raw_input)

        if not raw_text.strip():
            raise_api_error("DATASET_ITEM_NOT_FOUND", "Raw curriculum text payload is empty.")

        # 1. Generate Root Dataset DNA
        dataset_id = payload_meta.get("file_id") or f"ds_{hashlib.sha256(raw_text[:200].encode()).hexdigest()[:10]}"
        dataset_dna = artifact_dna_service.generate_dataset_dna(
            dataset_id=dataset_id,
            raw_text=raw_text,
            source_meta=payload_meta,
        )

        # 2. Parse curriculum metadata & structural sections
        design = self._parse_curriculum_text(raw_text, payload_meta, dataset_dna.dna_id)

        # 3. Synthesize Dynamic Pedagogical ContentTypeProfile from Curriculum Design Dataset
        try:
            from .content_type_classifier import ai_generate_profile_from_dataset
            dyn_profile = ai_generate_profile_from_dataset(
                subject=design.subject,
                grade=design.grade,
                level=design.level,
                essence_statement=design.essence_statement,
                general_learning_outcomes=design.general_learning_outcomes,
                save_to_db=True,
            )
            design.raw_payload["dynamic_profile"] = dyn_profile.to_dict()
        except Exception as p_exc:  # noqa: BLE001
            logger.warning("Dynamic profile synthesis during ingestion deferred: %s", p_exc)

        # 4. Generate Subject, Strand, and Substrand DNAs
        self._generate_curriculum_dna_tree(design, dataset_dna.dna_id, raw_text)

        # 5. Persist to PostgreSQL database
        self._persist_to_db(design)

        # 6. Synchronize with Langfuse dataset item
        langfuse_sync_result = self._sync_to_langfuse(design)

        logger.info(
            "Successfully ingested curriculum design '%s' (%s - %s) with %d sub-strand blueprints and prompt packages.",
            design.subject,
            design.grade,
            design.level,
            len(design.substrands),
        )

        return {
            "status": "success",
            "design_id": design.design_id,
            "subject": design.subject,
            "subject_code": design.subject_code,
            "grade": design.grade,
            "level": design.level,
            "essence_statement": design.essence_statement,
            "dataset_dna_id": design.dataset_dna_id,
            "subject_dna_id": design.subject_dna_id,
            "substrand_count": len(design.substrands),
            "substrands": [
                {
                    "strand": s.strand_name,
                    "strand_dna_id": s.strand_dna_id,
                    "sub_strand": s.sub_strand_name,
                    "substrand_dna_id": s.substrand_dna_id,
                    "hours": s.allocated_hours,
                    "slo_count": len(s.slos),
                    "diagrams_required": s.required_diagrams,
                    "experiments": s.experiments,
                    "safety_hazards_to_check": s.safety_hazards_to_check,
                    "kiqs": s.key_inquiry_questions,
                    "prompt_package": s.prompt_package,
                }
                for s in design.substrands
            ],
            "langfuse_sync": langfuse_sync_result,
        }

    def _generate_curriculum_dna_tree(
        self, design: ParsedCurriculumDesign, dataset_dna_id: str, raw_text: str
    ) -> None:
        subject_dna = artifact_dna_service.generate_subject_dna(
            subject=design.subject,
            grade=design.grade,
            level=design.level,
            essence_statement=design.essence_statement,
            general_outcomes=design.general_learning_outcomes,
            parent_dataset_dna_id=dataset_dna_id,
            raw_snippet=raw_text[:2000],
        )
        design.subject_dna_id = subject_dna.dna_id
        design.dataset_dna_id = dataset_dna_id

        strand_dnas: dict[str, str] = {}
        for s in design.substrands:
            if s.strand_name not in strand_dnas:
                strand_cert = artifact_dna_service.generate_strand_dna(
                    strand_id=s.strand_id,
                    strand_name=s.strand_name,
                    grade=design.grade,
                    subject=design.subject,
                    parent_subject_dna_id=subject_dna.dna_id,
                    raw_strand_snippet=s.raw_snippet[:500],
                )
                strand_dnas[s.strand_name] = strand_cert.dna_id

            s.strand_dna_id = strand_dnas[s.strand_name]

            sub_cert = artifact_dna_service.generate_substrand_dna(
                grade=design.grade,
                subject=design.subject,
                strand_name=s.strand_name,
                sub_strand_id=s.sub_strand_id,
                sub_strand_name=s.sub_strand_name,
                allocated_hours=s.allocated_hours,
                slos=s.slos,
                kiqs=s.key_inquiry_questions,
                diagrams_required=s.required_diagrams,
                experiments=s.experiments,
                parent_strand_dna_id=s.strand_dna_id,
                raw_substrand_snippet=s.raw_snippet,
            )
            s.substrand_dna_id = sub_cert.dna_id
            s.prompt_package["substrand_dna_id"] = sub_cert.dna_id
            s.prompt_package["subject_dna_id"] = subject_dna.dna_id

    def _parse_curriculum_text(
        self, text: str, meta: dict[str, Any], dataset_dna_id: str
    ) -> ParsedCurriculumDesign:
        subject = "General Curriculum"
        subject_patterns = [
            r"(?:DIPLOMA IN TEACHER EDUCATION[^\n]*\n(?:PRE-PRIMARY AND PRIMARY\n)?([A-Z\s]{3,30})\nCURRICULUM DESIGN)",
            r"([A-Z\s]{3,30})\s+CURRICULUM DESIGN",
            r"CURRICULUM DESIGN FOR\s+([A-Z\s]{3,30})",
            r"LEARNING AREA:\s*([A-Za-z\s]+)",
        ]
        for pat in subject_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                cand = m.group(1).strip()
                cand = re.sub(r"^(FOR|IN|THE|DIPLOMA|GRADE)\s+", "", cand, flags=re.IGNORECASE).strip()
                if len(cand) >= 3 and "\n" not in cand:
                    subject = cand.title()
                    break

        if subject == "General Curriculum" and meta.get("title"):
            subject = str(meta["title"]).replace(".pdf", "").title()

        grade = "grade-7"
        level = "Basic Education"
        if "DIPLOMA IN TEACHER EDUCATION" in text.upper() or "DTE" in text.upper():
            level = "Diploma in Teacher Education (Pre-Primary and Primary)"
            grade = "grade-dte"
        elif "JUNIOR SCHOOL" in text.upper() or "GRADE 7" in text.upper():
            level = "Junior School"
            grade = "grade-7"
        elif "GRADE 8" in text.upper():
            level = "Junior School"
            grade = "grade-8"
        elif "GRADE 9" in text.upper():
            level = "Junior School"
            grade = "grade-9"
        elif "GRADE 4" in text.upper() or "GRADE 5" in text.upper() or "GRADE 6" in text.upper():
            level = "Upper Primary"
            grade = "grade-4"
        elif "PRE-PRIMARY" in text.upper() or "PP1" in text.upper():
            level = "Pre-Primary"
            grade = "grade-pp1"

        subject_code = "".join([w[0] for w in subject.split() if w]).upper()[:4]

        essence_statement = ""
        essence_match = re.search(
            r"ESSENCE STATEMENT\s*\n+(.*?)(?=\n+[A-Z\s]{4,}\n|\Z)",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if essence_match:
            essence_statement = essence_match.group(1).strip()

        general_outcomes: list[str] = []
        glo_match = re.search(
            r"GENERAL LEARNING OUTCOMES\s*\n+(.*?)(?=\n+STRAND|\n+TABLE|\n+1\.0|\Z)",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if glo_match:
            glo_text = glo_match.group(1)
            general_outcomes = [
                line.strip()
                for line in re.split(r"\n\s*\d+\.\s*", glo_text)
                if line.strip() and len(line.strip()) > 10
            ]

        substrands = self._extract_substrands(text, subject, grade, level)

        design_id = f"cd_{grade}_{subject_code.lower()}_{hashlib.sha256(text[:500].encode()).hexdigest()[:8]}"

        return ParsedCurriculumDesign(
            design_id=design_id,
            subject=subject,
            subject_code=subject_code,
            grade=grade,
            level=level,
            essence_statement=essence_statement,
            general_learning_outcomes=general_outcomes,
            substrands=substrands,
            raw_payload={"meta": meta, "char_count": len(text)},
            metadata={"source": meta.get("source", "raw_ingest"), "file_id": meta.get("file_id", "")},
            dataset_dna_id=dataset_dna_id,
        )

    def _extract_substrands(
        self, text: str, subject: str, grade: str, level: str
    ) -> list[ParsedSubstrand]:
        substrands: list[ParsedSubstrand] = []

        strand_pattern = r"(STRAND\s+(\d+\.\d+)\s+([^\n]+))"
        strand_matches = list(re.finditer(strand_pattern, text, re.IGNORECASE))

        if not strand_matches:
            strand_matches = list(re.finditer(r"((\d+\.\d+)\s+([A-Z\s]{4,40}))", text))

        for i, sm in enumerate(strand_matches):
            strand_full = sm.group(1)
            strand_id = sm.group(2).strip()
            strand_name = f"{strand_id} {sm.group(3).strip()}"

            start_pos = sm.end()
            end_pos = strand_matches[i + 1].start() if i + 1 < len(strand_matches) else len(text)
            strand_section = text[start_pos:end_pos]

            substrand_pattern = r"(?:(?:Sub\s*Strand|1\.\d+|2\.\d+|3\.\d+|4\.\d+)\s*(\d+\.\d+)\.?\s*([^\n\(\)]+)(?:\(([^\)]+)\))?)"
            sub_matches = list(re.finditer(substrand_pattern, strand_section, re.IGNORECASE))

            if not sub_matches:
                parsed_sub = self._parse_single_substrand(
                    strand_id=strand_id,
                    strand_name=strand_name,
                    sub_id=f"{strand_id}.1",
                    sub_name=strand_name,
                    hours="4 hours",
                    body=strand_section,
                    subject=subject,
                    grade=grade,
                    level=level,
                )
                if parsed_sub:
                    substrands.append(parsed_sub)
                continue

            for j, sbm in enumerate(sub_matches):
                sub_id = sbm.group(1).strip()
                sub_name = sbm.group(2).strip()
                hours = sbm.group(3).strip() if sbm.group(3) else "4 hours"

                sub_start = sbm.end()
                sub_end = sub_matches[j + 1].start() if j + 1 < len(sub_matches) else len(strand_section)
                sub_body = strand_section[sub_start:sub_end]

                parsed_sub = self._parse_single_substrand(
                    strand_id=strand_id,
                    strand_name=strand_name,
                    sub_id=sub_id,
                    sub_name=f"{sub_id} {sub_name}",
                    hours=hours,
                    body=sub_body,
                    subject=subject,
                    grade=grade,
                    level=level,
                )
                if parsed_sub:
                    substrands.append(parsed_sub)

        return substrands

    def _parse_single_substrand(
        self,
        strand_id: str,
        strand_name: str,
        sub_id: str,
        sub_name: str,
        hours: str,
        body: str,
        subject: str,
        grade: str,
        level: str,
    ) -> ParsedSubstrand | None:
        if len(body.strip()) < 30:
            return None

        # 1. Extract Specific Learning Outcomes (SLOs)
        slos: list[dict[str, str]] = []
        clean_sub_code = re.sub(r"[^a-zA-Z0-9]", "-", sub_id).strip("-") or "SS"
        subj_code = re.sub(r"[^a-zA-Z0-9]", "", subject[:3]).upper() if subject else "CBC"
        slo_matches = re.findall(r"([a-h]\))\s*([^\n\.\;]+[\.\;]?)", body, re.IGNORECASE)
        for letter, content in slo_matches:
            let_code = letter.strip(")").lower()
            slo_id = f"{grade}-{subj_code}-{clean_sub_code}-{let_code}"
            slos.append({"id": slo_id, "code": let_code, "text": content.strip()})

        if not slos:
            bullet_matches = re.findall(r"(?:•|-|\*)\s*([^\n]+)", body)
            for k, bm in enumerate(bullet_matches[:6]):
                let_code = chr(ord("a") + k)
                slo_id = f"{grade}-{subj_code}-{clean_sub_code}-{let_code}"
                slos.append({"id": slo_id, "code": let_code, "text": bm.strip()})

        # 2. Extract Suggested Learning Experiences
        learning_experiences: list[str] = []
        exp_match = re.search(
            r"Suggested Learning\s*Experiences\s*(.*?)(?=Suggested Key|Core competencies|Values|Assessment|\Z)",
            body,
            re.DOTALL | re.IGNORECASE,
        )
        if exp_match:
            lines = [l.strip() for l in exp_match.group(1).split("\n") if l.strip()]
            for line in lines:
                if len(line) > 15 and not line.startswith("Page"):
                    learning_experiences.append(line.lstrip("•-* "))

        # 3. Extract Key Inquiry Questions (KIQs)
        kiqs: list[str] = []
        kiq_matches = re.findall(r"(?:How|Why|What|Which|Where)[^\?\n]+\?", body, re.IGNORECASE)
        for q in kiq_matches:
            clean_q = q.strip().replace("\n", " ")
            if clean_q not in kiqs and len(clean_q) > 12:
                kiqs.append(clean_q)

        # 4. Extract Core Competencies & Values
        competencies = []
        comp_match = re.search(
            r"Core competencies to be developed:?\s*\n*(.*?)(?=Values:|\n\n|\Z)",
            body,
            re.DOTALL | re.IGNORECASE,
        )
        if comp_match:
            competencies = [c.strip() for c in comp_match.group(1).split("\n") if c.strip() and len(c.strip()) > 8]

        values = []
        val_match = re.search(
            r"Values:?\s*\n*(.*?)(?=Suggested Formative|\n\n|\Z)",
            body,
            re.DOTALL | re.IGNORECASE,
        )
        if val_match:
            values = [v.strip() for v in val_match.group(1).split("\n") if v.strip() and len(v.strip()) > 6]

        # 5. Extract Assessment Rubrics
        rubrics = []
        rubric_match = re.search(
            r"Suggested Formative Assessment Rubrics?\s*\n*(.*?)(?=STRAND|\Z)",
            body,
            re.DOTALL | re.IGNORECASE,
        )
        if rubric_match:
            rubrics.append({"raw_rubric": rubric_match.group(1)[:1200]})

        # 6. Discover Required Diagrams & Visual Models
        required_diagrams = []
        diagram_keywords = [
            "structure", "model", "diagram", "chart", "map", "illustration", "setup",
            "drip irrigation", "compost", "zai pit", "scarecrow", "soil profile", "herbarium",
            "nursery bed", "container garden", "vertical garden", "seedbed", "water pan",
            "animal house", "plant morphology"
        ]
        for kw in diagram_keywords:
            if kw in body.lower():
                required_diagrams.append(f"{sub_name} - {kw.title()} visual model")
        required_diagrams = list(dict.fromkeys(required_diagrams))[:4]

        # 7. Discover Experiments & Practical Activities
        experiments = []
        exp_keywords = [
            "experiment", "project", "investigate", "test", "measure", "simulate", "prepare", "construct", "rear", "grow"
        ]
        for line in body.split("\n"):
            line_l = line.lower()
            if any(k in line_l for k in exp_keywords) and len(line.strip()) > 20:
                clean_exp = line.strip().lstrip("•-* ")
                if clean_exp not in experiments:
                    experiments.append(clean_exp)
                if len(experiments) >= 4:
                    break

        # 8. Discover Safety Hazards to Check (Hazard audit criteria)
        safety_hazards = [
            "Verify all chemical or biological materials are non-toxic and age-appropriate",
            "Ensure procedures with heat, fire, or smoke specify adult supervision and fire safety",
            "Ensure tools/equipment (cutters, hoes, knives) include explicit handling precautions",
            "Check that soil/manure activities mandate washing hands with soap and water afterwards",
            "Verify animal handling steps include hygiene, gentle restraint, and rabies/bite precautions",
        ]

        # 9. Build Comprehensive Dynamic Prompt Package for all downstream agents (fetched from Langfuse)
        slo_texts = [s.get("text", str(s)) if isinstance(s, dict) else str(s) for s in slos]
        first_slo_id = (slos[0].get("id") or slos[0].get("code")) if slos and isinstance(slos[0], dict) else f"{grade}-{subj_code}-01"
        prompt_vars = {
            "level": level,
            "grade": grade,
            "subject": subject,
            "subject_code": subj_code,
            "strand": strand_name,
            "sub_strand": sub_name,
            "slo_id": first_slo_id,
            "difficulty": 0.65,
            "diagram_id": f"diag_{first_slo_id}",
            "notes_title": f"Revision Notes for {sub_name}",
            "concept": required_diagrams[0] if required_diagrams else sub_name,
            "subject_context": {
                "subject": subject,
                "strand": strand_name,
                "sub_strand": sub_name,
                "hours": hours,
                "slos": slo_texts,
                "kiqs": kiqs,
                "diagrams": required_diagrams,
                "experiments": experiments,
                "safety_hazards": safety_hazards,
            },
        }

        def _get_rendered_langfuse_prompt(pname: str, fallback: str) -> str:
            try:
                tpl = langfuse_context_service.get_agent_prompt(pname)
                return langfuse_context_service._render_template(tpl, prompt_vars)
            except Exception:
                return fallback

        prompt_package = {
            "subject": subject,
            "grade": grade,
            "level": level,
            "strand": strand_name,
            "sub_strand": sub_name,
            "allocated_hours": hours,
            "slos": slo_texts,
            "kiqs": kiqs,
            "diagram_guidance": required_diagrams,
            "experiment_guidance": experiments,
            "safety_hazard_criteria": safety_hazards,
            # Agent-specific customized prompt templates compiled directly from Langfuse prompt management
            "notes_prompt": _get_rendered_langfuse_prompt("note-generator", f"Generate revision notes for {sub_name}"),
            "diagram_prompt": _get_rendered_langfuse_prompt("diagram-generator", f"Generate vector SVG diagram for {sub_name}"),
            "experiment_activity_prompt": _get_rendered_langfuse_prompt("activity-generator", f"Generate practical experiments with safety checks for {sub_name}"),
            "question_prompt": _get_rendered_langfuse_prompt("question-generator", f"Generate criterion-referenced questions for {sub_name}"),
            "reviewer_prompt": _get_rendered_langfuse_prompt("reviewer-panel", f"Perform safety and quality audit for {sub_name}"),
            "approver_agent1_prompt": _get_rendered_langfuse_prompt("approver-agent1", f"Auditor 1 evaluation for {sub_name}"),
            "approver_agent2_prompt": _get_rendered_langfuse_prompt("approver-agent2", f"Auditor 2 consensus evaluation for {sub_name}"),
        }

        return ParsedSubstrand(
            strand_id=strand_id,
            strand_name=strand_name,
            sub_strand_id=sub_id,
            sub_strand_name=sub_name,
            allocated_hours=hours,
            slos=slos,
            learning_experiences=learning_experiences,
            key_inquiry_questions=kiqs,
            core_competencies=competencies,
            values=values,
            assessment_rubrics=rubrics,
            required_diagrams=required_diagrams,
            experiments=experiments,
            safety_hazards_to_check=safety_hazards,
            pedagogical_guidance={"competencies": competencies, "values": values},
            prompt_package=prompt_package,
            raw_snippet=body,
        )

    def _persist_to_db(self, design: ParsedCurriculumDesign, status: str = "draft_pending_human_review") -> None:
        review_status = design.metadata.get("review_status") or status

        execute(
            """
            INSERT INTO curriculum_designs (
                design_id, subject, subject_code, grade, level, essence_statement,
                general_learning_outcomes, raw_payload, metadata, review_status, updated_at
            )
            VALUES (
                :design_id, :subject, :subject_code, :grade, :level, :essence_statement,
                CAST(:glo AS jsonb), CAST(:raw_payload AS jsonb), CAST(:metadata AS jsonb), :review_status, NOW()
            )
            ON CONFLICT (design_id) DO UPDATE SET
                subject = EXCLUDED.subject,
                subject_code = EXCLUDED.subject_code,
                grade = EXCLUDED.grade,
                level = EXCLUDED.level,
                essence_statement = EXCLUDED.essence_statement,
                general_learning_outcomes = EXCLUDED.general_learning_outcomes,
                raw_payload = EXCLUDED.raw_payload,
                metadata = EXCLUDED.metadata,
                review_status = EXCLUDED.review_status,
                updated_at = NOW()
            """,
            {
                "design_id": design.design_id,
                "subject": design.subject,
                "subject_code": design.subject_code,
                "grade": design.grade,
                "level": design.level,
                "essence_statement": design.essence_statement,
                "glo": to_json(design.general_learning_outcomes),
                "raw_payload": to_json(
                    {
                        **design.raw_payload,
                        "dataset_dna_id": design.dataset_dna_id,
                        "subject_dna_id": design.subject_dna_id,
                    }
                ),
                "metadata": to_json(design.metadata),
                "review_status": review_status,
            },
        )

        for s in design.substrands:
            execute(
                """
                INSERT INTO curriculum_substrands (
                    design_id, grade, subject, strand_id, strand_name, sub_strand_id, sub_strand_name,
                    allocated_hours, slos, learning_experiences, key_inquiry_questions,
                    core_competencies, values, assessment_rubrics, required_diagrams,
                    experiments, pedagogical_guidance, prompt_context, updated_at
                )
                VALUES (
                    :design_id, :grade, :subject, :strand_id, :strand_name, :sub_strand_id, :sub_strand_name,
                    :allocated_hours, CAST(:slos AS jsonb), CAST(:learning_exp AS jsonb),
                    CAST(:kiqs AS jsonb), CAST(:competencies AS jsonb), CAST(:values AS jsonb),
                    CAST(:rubrics AS jsonb), CAST(:diagrams AS jsonb), CAST(:experiments AS jsonb),
                    CAST(:pedagogical AS jsonb), CAST(:prompt_context AS jsonb), NOW()
                )
                ON CONFLICT (grade, subject, strand_name, sub_strand_name) DO UPDATE SET
                    design_id = EXCLUDED.design_id,
                    strand_id = EXCLUDED.strand_id,
                    sub_strand_id = EXCLUDED.sub_strand_id,
                    allocated_hours = EXCLUDED.allocated_hours,
                    slos = EXCLUDED.slos,
                    learning_experiences = EXCLUDED.learning_experiences,
                    key_inquiry_questions = EXCLUDED.key_inquiry_questions,
                    core_competencies = EXCLUDED.core_competencies,
                    values = EXCLUDED.values,
                    assessment_rubrics = EXCLUDED.assessment_rubrics,
                    required_diagrams = EXCLUDED.required_diagrams,
                    experiments = EXCLUDED.experiments,
                    pedagogical_guidance = EXCLUDED.pedagogical_guidance,
                    prompt_context = EXCLUDED.prompt_context,
                    updated_at = NOW()
                """,
                {
                    "design_id": design.design_id,
                    "grade": design.grade,
                    "subject": design.subject,
                    "strand_id": s.strand_id,
                    "strand_name": s.strand_name,
                    "sub_strand_id": s.sub_strand_id,
                    "sub_strand_name": s.sub_strand_name,
                    "allocated_hours": s.allocated_hours,
                    "slos": to_json(s.slos),
                    "learning_exp": to_json(s.learning_experiences),
                    "kiqs": to_json(s.key_inquiry_questions),
                    "competencies": to_json(s.core_competencies),
                    "values": to_json(s.values),
                    "rubrics": to_json(s.assessment_rubrics),
                    "diagrams": to_json(s.required_diagrams),
                    "experiments": to_json(s.experiments),
                    "pedagogical": to_json(s.pedagogical_guidance),
                    "prompt_context": to_json(
                        {
                            **s.prompt_package,
                            "substrand_dna_id": s.substrand_dna_id,
                            "strand_dna_id": s.strand_dna_id,
                        }
                    ),
                },
            )

    def _sync_to_langfuse(self, design: ParsedCurriculumDesign) -> dict[str, Any]:
        strands_tree: list[dict[str, Any]] = []
        strand_map: dict[str, list[dict[str, Any]]] = {}

        for s in design.substrands:
            if s.strand_name not in strand_map:
                strand_map[s.strand_name] = []
            strand_map[s.strand_name].append(
                {
                    "name": s.sub_strand_name,
                    "hours": s.allocated_hours,
                    "slos": [item.get("text", str(item)) if isinstance(item, dict) else str(item) for item in s.slos],
                    "diagrams_required": s.required_diagrams,
                    "experiments": s.experiments,
                    "safety_hazards_to_check": s.safety_hazards_to_check,
                    "kiqs": s.key_inquiry_questions,
                    "substrand_dna_id": s.substrand_dna_id,
                    "strand_dna_id": s.strand_dna_id,
                    "prompt_package": s.prompt_package,
                }
            )

        for s_name, sub_list in strand_map.items():
            strands_tree.append({"name": s_name, "sub_strands": sub_list})

        langfuse_payload = {
            "subject": design.subject,
            "subject_code": design.subject_code,
            "level": design.level,
            "essence_statement": design.essence_statement,
            "general_learning_outcomes": design.general_learning_outcomes,
            "strands": strands_tree,
            "dataset_dna_id": design.dataset_dna_id,
            "subject_dna_id": design.subject_dna_id,
            "metadata": {
                "source": "curriculum_extractor",
                "design_id": design.design_id,
                "substrand_count": len(design.substrands),
            },
        }

        try:
            from .langfuse_context import langfuse_context_service
            return langfuse_context_service.upload_dataset_item(
                grade_slug=design.grade,
                subject_data=langfuse_payload,
            )
        except Exception as exc:
            logger.warning("Langfuse sync skipped for design '%s': %s", design.design_id, exc)
            return {"status": "skipped", "reason": str(exc)}

    def set_blueprint_decision(self, design_id: str, decision: str, notes: str = "") -> dict[str, Any]:
        """Human reviewer accepts or rejects the AI-generated curriculum blueprint."""
        from ..infra.db import execute, fetch_one

        status = "accepted_active" if decision.lower() in {"accept", "approved", "active", "accepted"} else "rejected"
        execute(
            """
            UPDATE curriculum_designs
            SET review_status = :status, human_review_notes = :notes, updated_at = NOW()
            WHERE design_id = :design_id
            """,
            {"design_id": design_id, "status": status, "notes": notes},
        )
        row = fetch_one("SELECT * FROM curriculum_designs WHERE design_id = :design_id", {"design_id": design_id})
        return {
            "design_id": design_id,
            "status": status,
            "decision": decision,
            "human_review_notes": notes,
            "updated_design": row,
        }


curriculum_extractor = CurriculumExtractorService()
