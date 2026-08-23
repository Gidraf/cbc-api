"""
Dynamic Content-Type Classifier & Pedagogical Profile Management Service.

All pedagogical profiles (persona, note style, diagram models, practical activities,
assessment rubrics, safety guidelines, empirical insights, case studies) are stored
and managed in the PostgreSQL `subject_profiles` database table.

Features:
  1. Full DB persistence (CRUD) for all subject profiles with web UI management.
  2. "✨ Ask AI to Enhance Profile" endpoint to iteratively refine and expand any profile.
  3. "⚡ Auto-Generate Profile" endpoint to synthesize bespoke profiles from Curriculum Design datasets.
  4. Automatic DB seeding of initial standard CBC disciplines on database initialization.
  5. Integration with Web Research engine for domain empirical data and case studies.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

try:
    from ..infra.db import execute, fetch_all, fetch_one, to_json
    HAS_DB = True
except Exception:
    execute = None
    fetch_all = None
    fetch_one = None
    to_json = json.dumps
    HAS_DB = False

logger = logging.getLogger("cbc-content-profile")


# ─────────────────────────────────────────────────────────────────────────────
# Content-Type Profile Dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(slots=True)
class ContentTypeProfile:
    """Complete pedagogical profile stored in database."""
    content_type: str
    persona: str
    note_style: str
    diagram_type: str
    activity_type: str
    question_type: str
    safety_focus: str
    grade_appropriate_tone: str = "formal academic and constructivist"
    special_directives: list[str] = field(default_factory=list)
    empirical_insights: list[dict[str, Any]] = field(default_factory=list)
    case_studies: list[dict[str, str]] = field(default_factory=list)
    subject: str = "General"
    grade: str = "all"
    id: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "subject": self.subject,
            "grade": self.grade,
            "content_type": self.content_type,
            "persona": self.persona,
            "note_style": self.note_style,
            "diagram_type": self.diagram_type,
            "activity_type": self.activity_type,
            "question_type": self.question_type,
            "safety_focus": self.safety_focus,
            "grade_appropriate_tone": self.grade_appropriate_tone,
            "special_directives": self.special_directives,
            "empirical_insights": self.empirical_insights,
            "case_studies": self.case_studies,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ContentTypeProfile:
        return cls(
            id=data.get("id"),
            subject=str(data.get("subject", "General")),
            grade=str(data.get("grade", "all")),
            content_type=str(data.get("content_type", "generic")),
            persona=str(data.get("persona", "Senior Curriculum Specialist & Teacher Educator.")),
            note_style=str(data.get("note_style", "Exhaustive conceptual exposition with pedagogical scaffolding.")),
            diagram_type=str(data.get("diagram_type", "Concept maps, process flowcharts, and annotated schematics.")),
            activity_type=str(data.get("activity_type", "Hands-on experiential investigations and practical tasks.")),
            question_type=str(data.get("question_type", "Criterion-referenced Bloom's taxonomy assessment items.")),
            safety_focus=str(data.get("safety_focus", "Standard classroom and laboratory safety precautions.")),
            grade_appropriate_tone=str(data.get("grade_appropriate_tone", "formal academic and constructivist")),
            special_directives=list(data.get("special_directives", []) if isinstance(data.get("special_directives"), list) else []),
            empirical_insights=list(data.get("empirical_insights", []) if isinstance(data.get("empirical_insights"), list) else []),
            case_studies=list(data.get("case_studies", []) if isinstance(data.get("case_studies"), list) else []),
            metadata=dict(data.get("metadata", {}) if isinstance(data.get("metadata"), dict) else {}),
        )

    def format_for_prompt(self) -> str:
        """Format as an authoritative directive block to inject into LLM prompts."""
        lines = [
            f"=== PEDAGOGICAL CONTENT-TYPE DIRECTIVES ({self.content_type.upper()}) ===",
            f"Agent Persona: {self.persona}",
            f"Note Writing Style: {self.note_style}",
            f"Diagram/Visual Type: {self.diagram_type}",
            f"Activity/Experiment Type: {self.activity_type}",
            f"Question/Assessment Type: {self.question_type}",
            f"Safety & Risk Focus: {self.safety_focus}",
            f"Tone & Register: {self.grade_appropriate_tone}",
        ]
        if self.special_directives:
            lines.append("Mandatory Subject Directives:")
            for d in self.special_directives:
                lines.append(f"  - {d}")
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Database CRUD Operations
# ─────────────────────────────────────────────────────────────────────────────

def list_all_profiles_from_db(search: str = "", grade: str = "") -> list[ContentTypeProfile]:
    """Retrieve all profiles from the subject_profiles database table."""
    _ensure_defaults_seeded()
    try:
        query = "SELECT * FROM subject_profiles WHERE 1=1"
        params: dict[str, Any] = {}
        if search:
            query += " AND (LOWER(subject) LIKE LOWER(:q) OR LOWER(content_type) LIKE LOWER(:q))"
            params["q"] = f"%{search.strip()}%"
        if grade and grade != "all":
            query += " AND (LOWER(grade) = LOWER(:g) OR grade = 'all')"
            params["g"] = grade.strip()
        query += " ORDER BY subject ASC"

        rows = fetch_all(query, params)
        return [_row_to_profile(r) for r in rows]
    except Exception as exc:
        logger.warning("Failed to list subject profiles from DB: %s", exc)
        return []


def get_profile_by_id(profile_id: int) -> ContentTypeProfile | None:
    """Retrieve a single profile by primary key ID."""
    _ensure_defaults_seeded()
    try:
        row = fetch_one("SELECT * FROM subject_profiles WHERE id = :id", {"id": profile_id})
        return _row_to_profile(row) if row else None
    except Exception as exc:
        logger.warning("Failed to get profile %d: %s", profile_id, exc)
        return None


def get_profile_from_db(subject: str, grade: str = "all") -> ContentTypeProfile | None:
    """Find the best matching profile for a subject and grade in the DB."""
    _ensure_defaults_seeded()
    subj_clean = subject.strip()
    grade_clean = grade.strip()
    try:
        # 1. Exact match for subject + specific grade
        row = fetch_one(
            "SELECT * FROM subject_profiles WHERE LOWER(subject) = LOWER(:s) AND LOWER(grade) = LOWER(:g) LIMIT 1",
            {"s": subj_clean, "g": grade_clean},
        )
        if row:
            return _row_to_profile(row)

        # 2. Match for subject + 'all' grade
        row = fetch_one(
            "SELECT * FROM subject_profiles WHERE LOWER(subject) = LOWER(:s) AND grade = 'all' LIMIT 1",
            {"s": subj_clean},
        )
        if row:
            return _row_to_profile(row)

        # 3. Partial subject substring match (e.g. 'Agriculture and Environment' -> 'Agriculture')
        rows = fetch_all("SELECT * FROM subject_profiles ORDER BY LENGTH(subject) DESC", {})
        for r in rows:
            r_subj = r.get("subject", "").lower()
            if r_subj and (r_subj in subj_clean.lower() or subj_clean.lower() in r_subj):
                return _row_to_profile(r)
    except Exception as exc:
        logger.warning("Error querying subject_profiles DB for '%s (%s)': %s", subject, grade, exc)

    return None


def upsert_profile_in_db(profile: ContentTypeProfile) -> ContentTypeProfile:
    """Insert or update a subject profile in the database."""
    _ensure_defaults_seeded()
    try:
        if profile.id:
            execute(
                """
                UPDATE subject_profiles SET
                    subject = :subject,
                    grade = :grade,
                    content_type = :content_type,
                    persona = :persona,
                    note_style = :note_style,
                    diagram_type = :diagram_type,
                    activity_type = :activity_type,
                    question_type = :question_type,
                    safety_focus = :safety_focus,
                    grade_appropriate_tone = :grade_appropriate_tone,
                    special_directives = CAST(:special_directives AS jsonb),
                    empirical_insights = CAST(:empirical_insights AS jsonb),
                    case_studies = CAST(:case_studies AS jsonb),
                    metadata = CAST(:metadata AS jsonb),
                    updated_at = NOW()
                WHERE id = :id
                """,
                {
                    "id": profile.id,
                    "subject": profile.subject,
                    "grade": profile.grade,
                    "content_type": profile.content_type,
                    "persona": profile.persona,
                    "note_style": profile.note_style,
                    "diagram_type": profile.diagram_type,
                    "activity_type": profile.activity_type,
                    "question_type": profile.question_type,
                    "safety_focus": profile.safety_focus,
                    "grade_appropriate_tone": profile.grade_appropriate_tone,
                    "special_directives": to_json(profile.special_directives),
                    "empirical_insights": to_json(profile.empirical_insights),
                    "case_studies": to_json(profile.case_studies),
                    "metadata": to_json(profile.metadata),
                },
            )
            return profile
        else:
            execute(
                """
                INSERT INTO subject_profiles (
                    subject, grade, content_type, persona, note_style,
                    diagram_type, activity_type, question_type, safety_focus,
                    grade_appropriate_tone, special_directives, empirical_insights,
                    case_studies, metadata
                ) VALUES (
                    :subject, :grade, :content_type, :persona, :note_style,
                    :diagram_type, :activity_type, :question_type, :safety_focus,
                    :grade_appropriate_tone, CAST(:special_directives AS jsonb),
                    CAST(:empirical_insights AS jsonb), CAST(:case_studies AS jsonb),
                    CAST(:metadata AS jsonb)
                )
                ON CONFLICT (subject, grade) DO UPDATE SET
                    content_type = EXCLUDED.content_type,
                    persona = EXCLUDED.persona,
                    note_style = EXCLUDED.note_style,
                    diagram_type = EXCLUDED.diagram_type,
                    activity_type = EXCLUDED.activity_type,
                    question_type = EXCLUDED.question_type,
                    safety_focus = EXCLUDED.safety_focus,
                    grade_appropriate_tone = EXCLUDED.grade_appropriate_tone,
                    special_directives = EXCLUDED.special_directives,
                    empirical_insights = EXCLUDED.empirical_insights,
                    case_studies = EXCLUDED.case_studies,
                    metadata = EXCLUDED.metadata,
                    updated_at = NOW()
                """,
                {
                    "subject": profile.subject,
                    "grade": profile.grade,
                    "content_type": profile.content_type,
                    "persona": profile.persona,
                    "note_style": profile.note_style,
                    "diagram_type": profile.diagram_type,
                    "activity_type": profile.activity_type,
                    "question_type": profile.question_type,
                    "safety_focus": profile.safety_focus,
                    "grade_appropriate_tone": profile.grade_appropriate_tone,
                    "special_directives": to_json(profile.special_directives),
                    "empirical_insights": to_json(profile.empirical_insights),
                    "case_studies": to_json(profile.case_studies),
                    "metadata": to_json(profile.metadata),
                },
            )
            saved = get_profile_from_db(profile.subject, profile.grade)
            return saved or profile
    except Exception as exc:
        logger.error("Failed to upsert subject profile in DB: %s", exc)
        raise


def delete_profile_from_db(profile_id: int) -> bool:
    """Delete a profile from the database by ID."""
    try:
        execute("DELETE FROM subject_profiles WHERE id = :id", {"id": profile_id})
        return True
    except Exception as exc:
        logger.error("Failed to delete profile %d: %s", profile_id, exc)
        return False


def _row_to_profile(r: dict[str, Any]) -> ContentTypeProfile:
    directives = r.get("special_directives")
    if isinstance(directives, str):
        try:
            directives = json.loads(directives)
        except Exception:
            directives = []

    empirical = r.get("empirical_insights")
    if isinstance(empirical, str):
        try:
            empirical = json.loads(empirical)
        except Exception:
            empirical = []

    case_studies = r.get("case_studies")
    if isinstance(case_studies, str):
        try:
            case_studies = json.loads(case_studies)
        except Exception:
            case_studies = []

    meta = r.get("metadata")
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}

    return ContentTypeProfile(
        id=r.get("id"),
        subject=r.get("subject", "General"),
        grade=r.get("grade", "all"),
        content_type=r.get("content_type", "generic"),
        persona=r.get("persona", ""),
        note_style=r.get("note_style", ""),
        diagram_type=r.get("diagram_type", ""),
        activity_type=r.get("activity_type", ""),
        question_type=r.get("question_type", ""),
        safety_focus=r.get("safety_focus", ""),
        grade_appropriate_tone=r.get("grade_appropriate_tone", "formal academic and constructivist"),
        special_directives=directives or [],
        empirical_insights=empirical or [],
        case_studies=case_studies or [],
        metadata=meta or {},
    )


# ─────────────────────────────────────────────────────────────────────────────
# AI Enhancement & Generation (Interactive AI Assistance)
# ─────────────────────────────────────────────────────────────────────────────

def ai_improve_profile(profile_data: dict[str, Any], instructions: str = "") -> ContentTypeProfile:
    """
    Uses the LLM to expand, deepen, and refine an existing profile based on user instructions.
    """
    from .llm_client import llm_client
    from .pipeline import pipeline_orchestrator

    system_prompt = (
        "You are an elite Senior KICD Curriculum Specialist, Master Teacher Educator, and Pedagogical Profile Architect. "
        "Your task is to refine, expand, and elevate the provided Pedagogical Profile JSON for a Kenyan CBC subject. "
        "Make it exhaustive, culturally authentic for Kenya (Vision 2030, Kenyan AEZs, counties, KICD BECF), "
        "technically precise, and tailored specifically to the subject.\n\n"
        "Ensure all fields are filled with comprehensive, actionable pedagogical directives:\n"
        "- persona: Authoritative expert persona\n"
        "- note_style: Specific guidelines for authoring lesson notes\n"
        "- diagram_type: Authentic SVG visual models and diagrams for this discipline\n"
        "- activity_type: Constructivist hands-on investigations, practicals, or performances\n"
        "- question_type: Criterion-referenced Bloom's taxonomy assessment questions with 4-level rubrics\n"
        "- safety_focus: Discipline-specific physical, biological, chemical, vocal, tool, or cyber hazard protocols\n"
        "- special_directives: List of 4-8 mandatory authoring rules\n"
        "- empirical_insights: List of 3-5 verified empirical research metrics/data points with sources\n"
        "- case_studies: List of 2-4 authentic Kenyan county case studies with scenarios and interventions\n\n"
        "Return ONLY a valid JSON object matching the profile schema."
    )

    user_prompt = (
        f"CURRENT PEDAGOGICAL PROFILE TO ENHANCE:\n{json.dumps(profile_data, indent=2)}\n\n"
        f"USER REFINEMENT INSTRUCTIONS:\n{instructions or 'Expand and enhance this profile with deep authentic Kenyan context, comprehensive pedagogical guidelines, verified empirical data, and rigorous safety protocols.'}\n\n"
        f"Return the enhanced, complete profile JSON now."
    )

    resolved = pipeline_orchestrator.router.resolve_for_stage("notes_generation")
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    resp = llm_client.generate(resolved, messages, temperature=0.1)
    raw = resp.content

    if isinstance(raw, dict) and "persona" in raw:
        if "subject" not in raw:
            raw["subject"] = profile_data.get("subject", "General")
        if "grade" not in raw:
            raw["grade"] = profile_data.get("grade", "all")
        if "content_type" not in raw:
            raw["content_type"] = profile_data.get("content_type", "generic")
        if profile_data.get("id"):
            raw["id"] = profile_data["id"]

        enhanced_profile = ContentTypeProfile.from_dict(raw)
        upsert_profile_in_db(enhanced_profile)
        return enhanced_profile

    return ContentTypeProfile.from_dict(profile_data)


def ai_generate_profile_from_dataset(
    subject: str,
    grade: str = "all",
    level: str = "Basic Education",
    essence_statement: str = "",
    general_learning_outcomes: list[str] | None = None,
    save_to_db: bool = True,
) -> ContentTypeProfile:
    """
    Synthesizes a brand new bespoke ContentTypeProfile dynamically from an uploaded Curriculum Design dataset.
    """
    from .llm_client import llm_client
    from .pipeline import pipeline_orchestrator

    outcomes_str = "\n".join([f"- {o}" for o in (general_learning_outcomes or [])])

    system_prompt = (
        "You are an elite Senior KICD Curriculum Specialist and Pedagogical Profile Architect. "
        "Analyze the provided Kenyan Curriculum Design dataset (Essence Statement, Learning Outcomes, Grade/Level) "
        "and generate a complete, bespoke Pedagogical ContentTypeProfile JSON. "
        "The profile instructs downstream AI generation agents (Notes, SVG Diagram, Activities/Experiments, Questions) "
        "on the exact persona, writing style, visual models, constructivist practical tasks, assessment rubrics, "
        "safety protocols, empirical statistics, and authentic Kenyan case studies for THIS SPECIFIC SUBJECT.\n\n"
        "Return ONLY a valid JSON object matching this exact schema:\n"
        "{\n"
        '  "subject": "' + subject + '",\n'
        '  "grade": "' + grade + '",\n'
        '  "content_type": "<slug_e.g._music_or_home_science_or_pre_technical>",\n'
        '  "persona": "<authoritative professor/specialist persona>",\n'
        '  "note_style": "<specific pedagogical guidance for lesson notes>",\n'
        '  "diagram_type": "<specific visual models, schematics, or notation>",\n'
        '  "activity_type": "<constructivist hands-on activities/practicals>",\n'
        '  "question_type": "<criterion-referenced Bloom\'s assessment format>",\n'
        '  "safety_focus": "<specific safety hazard protocols and precautions>",\n'
        '  "grade_appropriate_tone": "<e.g. musical and expressive, rigorous technical, etc.>",\n'
        '  "special_directives": ["<rule 1>", "<rule 2>", "<rule 3>", "<rule 4>"],\n'
        '  "empirical_insights": [{"metric": "...", "value": "...", "source": "..."}],\n'
        '  "case_studies": [{"county": "...", "scenario": "...", "intervention": "..."}]\n'
        "}"
    )

    user_prompt = (
        f"CURRICULUM DESIGN DATASET:\n"
        f"Subject: {subject}\n"
        f"Grade: {grade} (Level: {level})\n"
        f"Essence Statement:\n{essence_statement or f'Comprehensive curriculum framework for {subject}.'}\n\n"
        f"General Learning Outcomes:\n{outcomes_str or '(Standard KICD outcomes)'}\n\n"
        f"Synthesize the complete, bespoke Pedagogical Profile JSON now."
    )

    resolved = pipeline_orchestrator.router.resolve_for_stage("notes_generation")
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    resp = llm_client.generate(resolved, messages, temperature=0.1)
    raw = resp.content

    if isinstance(raw, dict) and "persona" in raw:
        raw["subject"] = subject
        raw["grade"] = grade
        if not raw.get("content_type"):
            raw["content_type"] = re.sub(r"[^a-z0-9]+", "_", subject.lower()).strip("_")
        profile = ContentTypeProfile.from_dict(raw)
        if save_to_db:
            upsert_profile_in_db(profile)
        return profile

    # Fallback to general constructivist profile if LLM fails
    fallback = ContentTypeProfile(
        subject=subject,
        grade=grade,
        content_type=re.sub(r"[^a-z0-9]+", "_", subject.lower()).strip("_"),
        persona=f"Senior Curriculum Specialist & Pedagogy Expert in {subject}.",
        note_style=f"Comprehensive conceptual exposition for {subject} with constructivist scaffolding and authentic Kenyan context.",
        diagram_type=f"Scientific and conceptual visual models for {subject}.",
        activity_type=f"Hands-on constructivist practical tasks and investigations in {subject}.",
        question_type=f"Criterion-referenced assessment items for {subject} with 4-level KICD rubrics.",
        safety_focus=f"Standard classroom, laboratory, and field safety protocols for {subject}.",
    )
    if save_to_db:
        upsert_profile_in_db(fallback)
    return fallback


# ─────────────────────────────────────────────────────────────────────────────
# Master Public Classifier Function (DB Driven)
# ─────────────────────────────────────────────────────────────────────────────

def classify_content_type(
    subject: str,
    grade: str = "all",
    sub_strand: str = "",
    design_context: dict[str, Any] | None = None,
    auto_generate: bool = True,
) -> ContentTypeProfile:
    """
    Resolves the pedagogical ContentTypeProfile for a given subject & grade directly from the database.
    If missing in DB and design context is available, auto-generates and persists it to the DB!
    """
    subject_clean = subject.strip()
    grade_clean = grade.strip() if grade else "all"

    # 1. Lookup in PostgreSQL subject_profiles table
    profile = get_profile_from_db(subject_clean, grade_clean)
    if profile:
        return profile

    # 2. Auto-generate from design_context if available
    if design_context and (design_context.get("essence_statement") or design_context.get("general_learning_outcomes")) and auto_generate:
        logger.info("Auto-generating and persisting profile for '%s (%s)' to database...", subject_clean, grade_clean)
        return ai_generate_profile_from_dataset(
            subject=subject_clean,
            grade=grade_clean,
            level=design_context.get("level", "Basic Education"),
            essence_statement=design_context.get("essence_statement", ""),
            general_learning_outcomes=design_context.get("general_learning_outcomes", []),
            save_to_db=True,
        )

    # 3. Check curriculum_designs table in DB for essence statement
    try:
        row = fetch_one(
            "SELECT essence_statement, general_learning_outcomes, level FROM curriculum_designs WHERE LOWER(subject) = LOWER(:s) LIMIT 1",
            {"s": subject_clean},
        )
        if row and row.get("essence_statement") and auto_generate:
            logger.info("Synthesizing dynamic profile from curriculum_designs table for '%s'...", subject_clean)
            return ai_generate_profile_from_dataset(
                subject=subject_clean,
                grade=grade_clean,
                level=row.get("level", "Basic Education"),
                essence_statement=row.get("essence_statement", ""),
                general_learning_outcomes=row.get("general_learning_outcomes", []),
                save_to_db=True,
            )
    except Exception as exc:
        logger.warning("DB check for design essence statement failed: %s", exc)

    # 4. Fallback default profile
    default_profile = ContentTypeProfile(
        subject=subject_clean,
        grade=grade_clean,
        content_type=re.sub(r"[^a-z0-9]+", "_", subject_clean.lower()).strip("_") or "generic",
        persona=f"Senior Curriculum Specialist & Master Teacher Educator for {subject_clean} at KICD.",
        note_style=f"Exhaustive conceptual exposition with pedagogical content knowledge (PCK), constructivist scaffolding, and real-world Kenyan context.",
        diagram_type=f"Clear conceptual diagrams, flowcharts, structural models, and illustrated process flows for {subject_clean}.",
        activity_type=f"Constructivist experiential investigations, collaborative group tasks, and practical problem-solving activities.",
        question_type=f"Criterion-referenced Bloom's taxonomy assessment items (MCQ and structured) with 4-level KICD rubrics.",
        safety_focus=f"Classroom safety protocols, risk assessment, and inclusive accommodations for special needs education (SNE).",
        grade_appropriate_tone="formal academic with practical constructivist application",
        special_directives=[
            "Follow KICD Basic Education Curriculum Framework (BECF) standards",
            "Include formative assessment cues and common learner misconception diagnostics",
            "Ground all examples in Kenyan cultural and economic development context",
        ],
    )
    try:
        upsert_profile_in_db(default_profile)
    except Exception:
        pass
    return default_profile


# ─────────────────────────────────────────────────────────────────────────────
# Initial Database Seeder
# ─────────────────────────────────────────────────────────────────────────────

_SEEDED = False

def _ensure_defaults_seeded() -> None:
    """Seeds initial baseline profiles into the subject_profiles DB table if empty."""
    global _SEEDED
    if _SEEDED or not HAS_DB or not fetch_one:
        return
    _SEEDED = True

    try:
        count_row = fetch_one("SELECT COUNT(*) AS cnt FROM subject_profiles")
        if count_row and count_row.get("cnt", 0) > 0:
            return  # Already seeded
    except Exception as exc:
        logger.debug("subject_profiles table check: %s", exc)
        return

    logger.info("Seeding initial baseline pedagogical profiles into database...")
    initial_profiles = [
        ContentTypeProfile(
            subject="Agriculture",
            grade="all",
            content_type="agriculture",
            persona="Senior Professor of Agricultural Sciences & Sustainable Development at a Kenyan university with 20+ years of field research across Kenya's agro-ecological zones (AEZs).",
            note_style="Technical scientific exposition with empirical Kenyan data, agro-ecological zone references (AEZ I-VII), KALRO research citations, crop/livestock enterprise analysis, and Vision 2030 development connections.",
            diagram_type="Scientific flowcharts (e.g. agricultural value chains), crop lifecycle diagrams, agro-ecological zone maps of Kenya, soil profile cross-sections, drip irrigation schematics.",
            activity_type="Field investigations (school farm plots), soil testing experiments (pH, moisture, texture), composting practicals, seed germination trials, farm record keeping.",
            question_type="Scenario-based farm management and ecological problem-solving: crop enterprise selection, pest/disease diagnosis, soil amendment calculations.",
            safety_focus="Biological hygiene (mandatory handwashing after soil/manure handling), safe tool handling (pangas, jembes), chemical safety (fertilizers, pesticides - MSDS compliance).",
            special_directives=["Reference specific Kenyan counties and AEZs", "Include KALRO, KEPHIS, and NEMA regulatory frameworks", "Connect to Vision 2030 agricultural transformation pillars"],
            empirical_insights=[
                {"metric": "Economic Contribution of Agriculture to Kenya GDP", "value": "33% direct contribution, 27% indirect contribution to GDP", "source": "Kenya National Bureau of Statistics (KNBS)"},
                {"metric": "National Employment", "value": "Employs >40% of total population, >70% of rural population", "source": "Kenya Vision 2030 / CAADP"},
                {"metric": "Soil pH & Fertility Dynamics", "value": "Optimum crop nutrient availability between pH 6.0 - 7.5; acidic soils treated with agricultural lime (CaCO3)", "source": "KALRO National Agricultural Research Laboratories"},
            ],
            case_studies=[
                {"county": "Nakuru & Uasin Gishu Counties", "scenario": "Commercial & smallholder maize rotation facing fall armyworm and soil acidity.", "intervention": "Integrated Pest Management (IPM), push-pull technology (Desmodium & Napier grass), and lime application."},
                {"county": "Machakos & Makueni Counties (ASAL)", "scenario": "Frequent erratic rainfall leading to crop moisture stress.", "intervention": "Zai pits, micro-catchment water harvesting, drip irrigation, and drought-tolerant sorghum (KALRO Seredo)."},
            ],
        ),
        ContentTypeProfile(
            subject="Science",
            grade="all",
            content_type="science",
            persona="Distinguished Professor of Natural Sciences & STEM Pedagogy at a Kenyan university with expertise in laboratory design, experimental physics, chemistry, and biology.",
            note_style="Inquiry-driven scientific explanations with mathematical formulations, chemical equations (balanced), biological taxonomy, physical laws, and empirical research citations.",
            diagram_type="Scientific vector schematics: laboratory apparatus setups, ray diagrams, anatomical biological cutaways, molecular chemical structures, circuit diagrams.",
            activity_type="Rigorous laboratory experiments with hypotheses, apparatus lists, step-by-step procedures, observation data tables, quantitative data analysis, and error analysis.",
            question_type="Scientific inquiry problems: hypothesis formulation, quantitative calculations with SI units, experimental error identification, graph plotting and interpretation.",
            safety_focus="Strict laboratory safety: mandatory PPE (goggles, lab coats), chemical hazard symbols (corrosive, flammable, toxic), safe disposal of reagents, fire extinguisher protocols.",
            special_directives=["All chemical formulas and physical units MUST use proper notation (e.g. H2SO4, m/s^2)", "Include dedicated Safety Hazard Warnings for every experiment"],
            empirical_insights=[
                {"metric": "Standard Atmospheric Parameters", "value": "STP: Temperature = 273.15 K (0°C), Pressure = 101.325 kPa (1 atm)", "source": "IUPAC Chemical Standards"},
                {"metric": "NEMA Drinking Water Quality Standard", "value": "pH 6.5 - 8.5, Turbidity < 5 NTU, Total Dissolved Solids < 1000 mg/L", "source": "National Environment Management Authority (NEMA Kenya)"},
            ],
            case_studies=[
                {"county": "Nairobi & Athi River Basin", "scenario": "Industrial effluent and municipal runoff affecting local freshwater ecosystems.", "intervention": "Biological water filtration using constructed wetlands with reed beds (Typha domingensis)."},
            ],
        ),
        ContentTypeProfile(
            subject="Literature in English",
            grade="all",
            content_type="literature",
            persona="Master Storyteller, Literature Professor & Children's Author specialising in East African literary traditions and children's literature.",
            note_style="Narrative analysis, character studies and development arcs, thematic exploration, story summaries with moral lessons, literary device identification (simile, metaphor, personification). For younger learners, include complete children's stories.",
            diagram_type="Story sequence maps (beginning, middle, end), character relationship webs, narrative arc diagrams (exposition, rising action, climax, falling action, resolution), plot timelines.",
            activity_type="Dramatic role-play and reader's theatre scripts, creative writing workshops (story starters, character diary entries), storytelling circles with Kenyan folktales, poetry recitation.",
            question_type="Reading comprehension (literal, inferential, evaluative), character analysis and motivation questions, theme identification, creative writing prompts.",
            safety_focus="Age-appropriate content screening (no violence, trauma, or mature themes beyond grade level), emotional sensitivity, inclusive and non-discriminatory language.",
            special_directives=["Write original children's stories or adapt Kenyan folktales", "DO NOT generate laboratory experiments or scientific apparatus for literature sub-strands"],
            empirical_insights=[
                {"metric": "Literacy & Narrative Development", "value": "Story-based comprehension increases language retention and vocabulary acquisition by >45% in early/middle learners", "source": "UNESCO Literacy Studies"},
            ],
            case_studies=[
                {"county": "Kakamega & Vihiga Counties", "scenario": "Oral storytelling traditions and folklore preservation in community cultural festivals.", "intervention": "Reader's theatre adaptation of traditional trickster narratives for classroom performance."},
            ],
        ),
        ContentTypeProfile(
            subject="Music",
            grade="all",
            content_type="music",
            persona="Senior Ethnomusicologist, Choir Master & Music Pedagogy Specialist with deep expertise in Kenyan traditional folk music, Western art music, and choral performance.",
            note_style="Music theory and analysis: staff notation, pitch and rhythm reading, time signatures, tonic solfa notation. Kenyan traditional instruments classification (nyatiti, orutu, kayamba), folk songs analysis, and Kenya Music Festival guidelines.",
            diagram_type="5-line musical staves with note heads, pitch charts, clef diagrams, indigenous instrument structural anatomy illustrations (e.g. tuning pegs and resonator of Nyatiti), rhythm tree charts.",
            activity_type="Vocal warm-ups and pitch matching drills, rhythm clapping and percussion ostinatos, playing traditional instruments, folk dance choreography, solfa sight-singing exercises.",
            question_type="Musical score reading and notation transcription, audio/lyric analysis of folk songs, instrument classification and cultural usage evaluation, performance critiquing rubrics.",
            safety_focus="Vocal hygiene (preventing vocal strain/nodules), safe tool handling during instrument making, hygienic sharing of wind instruments (aerophones sanitization).",
            special_directives=["Include both Western staff notation concepts AND Kenyan traditional music heritage", "Reference authentic Kenyan instruments (Nyatiti, Orutu, Kayamba, Isukuti drums)"],
            empirical_insights=[
                {"metric": "Kenya Music Festival Heritage", "value": "Over 600 indigenous folk song and dance classifications documented across 43 Kenyan communities", "source": "Kenya Music Festival Foundation / KICD"},
            ],
            case_studies=[
                {"county": "Siaya & Kisumu Counties", "scenario": "Preservation and pedagogical transmission of the Nyatiti (8-stringed lyre) playing techniques.", "intervention": "Structured finger-picking tablature and rhythmic transcription for junior secondary music classes."},
            ],
        ),
        ContentTypeProfile(
            subject="Home Science",
            grade="all",
            content_type="home_science",
            persona="Professor of Food Science, Human Nutrition & Textile Technology with extensive research in Kenyan traditional food fortification, culinary arts, and garment construction.",
            note_style="Food nutrients and deficiency diseases, meal planning for special dietary groups, culinary cooking methods, kitchen hygiene (HACCP), food preservation, clothing construction (stitches, seams, pleats), textile care.",
            diagram_type="Balanced plate / food pyramid charts with indigenous Kenyan staples (managu, terere, beans, fish), kitchen layout work triangles, sewing stitch diagrams, seam construction cross-sections.",
            activity_type="Culinary practicals: preparing balanced Kenyan meals using healthy cooking methods, needlework practicals (seam and stitch samplers, button attachment), laundry stain removal experiments.",
            question_type="Nutritional meal planning scenario problems, cooking method selection and rationale, garment construction flaw diagnosis, food safety and hygiene breach evaluation.",
            safety_focus="Kitchen safety: fire extinguisher usage, gas cylinder handling protocols, hot oil burn prevention, sharp knife claw grip, food cross-contamination prevention, sewing needle safety.",
            special_directives=["Promote indigenous Kenyan nutrient-dense foods (traditional leafy vegetables like managu, terere, sagaa; sorghum, millet)", "Include step-by-step culinary recipes with exact measurements"],
            empirical_insights=[
                {"metric": "Indigenous Vegetables Nutritional Value", "value": "African Nightshade (Managu) and Amaranth (Terere) contain 3x more iron and beta-carotene than exotic cabbage", "source": "KALRO & Ministry of Health Kenya"},
            ],
            case_studies=[
                {"county": "Kilifi & Kwale Counties", "scenario": "Maternal and child micro-nutrient deficiencies in coastal communities.", "intervention": "School gardening and meal planning integrating moringa leaf powder, sweet potatoes, and dried small fish (omena)."},
            ],
        ),
        ContentTypeProfile(
            subject="Pre-Technical Studies",
            grade="all",
            content_type="pre_technical",
            persona="Senior Industrial Engineer, Technical Drawing Instructor & Vocational Education Specialist with expertise in material science, workshop technology, and OSHA industrial safety standards.",
            note_style="Material science (timber, metals, plastics, composites), hand tools classification and maintenance, technical drawing fundamentals (isometric, oblique, orthographic projections), basic electrical circuits and solar PV systems.",
            diagram_type="Isometric 3D projections with 30° grid lines, 3-view orthographic drawings (front, end, plan elevation) with dimensioning lines, woodworking joint cross-sections, electrical circuit schematics with IEC symbols.",
            activity_type="Workshop practicals: measuring and marking out timber using try square and marking gauge, sawing and chiseling simple wood joints, metal filing, assembling series/parallel LED circuits.",
            question_type="Orthographic projection view identification and drafting problems, tool selection and maintenance scenarios, electrical circuit troubleshooting.",
            safety_focus="Mandatory Workshop Safety & PPE: safety goggles for grinding/sawing, dust masks for sanding, heavy-duty aprons, steel-toe boots, secure clamping on bench vices before cutting.",
            special_directives=["Adhere to ISO / BS 8888 technical drawing standards with clear line weights", "Always specify mandatory workshop Personal Protective Equipment (PPE)"],
            empirical_insights=[
                {"metric": "Technical Vocational Skills Demand", "value": "Technical drawing and basic electromechanical skills increase youth technical employment readiness by >60%", "source": "TVETA Kenya & Ministry of Education"},
            ],
            case_studies=[
                {"county": "Mombasa & Kisumu Ports / Industrial Zones", "scenario": "Fabrication of solar-powered drip irrigation controllers for smallholder agriculture.", "intervention": "Drafting circuit schematics and building breadboard prototypes using basic resistors, transistors, and photovoltaic cells."},
            ],
        ),
    ]

    for p in initial_profiles:
        try:
            upsert_profile_in_db(p)
        except Exception as p_exc:
            logger.debug("Initial profile seed for '%s': %s", p.subject, p_exc)
