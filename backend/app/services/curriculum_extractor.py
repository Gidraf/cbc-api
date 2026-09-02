from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from ..errors import raise_api_error
from ..infra.db import execute, fetch_all, fetch_one, to_json
from ..services.artifact_dna import artifact_dna_service
from . import substrand_integrity
from .grade_order import grade_level as _grade_level_for, normalize_grade
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
    # Pre-Primary and Lower Primary run THEME x STRAND -> SUB-STRAND. A theme is
    # a third axis, not a strand and not a sub-strand.
    theme: str = ""
    pertinent_contemporary_issues: list[str] = field(default_factory=list)
    link_to_other_learning_areas: str = ""
    source_pages: list[int] = field(default_factory=list)


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



# ── Cover-page parsing ───────────────────────────────────────────────────────
# KICD covers put the learning area on its OWN line, between the words
# "CURRICULUM DESIGN" and the grade banner:
#
#     PRIMARY SCHOOL EDUCATION CURRICULUM DESIGN
#     FRENCH
#     GRADE 4
#
# Patterns that looked for "<SUBJECT> CURRICULUM DESIGN" therefore matched the
# level banner ("PRIMARY SCHOOL EDUCATION"), or spanned lines and were thrown
# away — which is why every document parsed as "General Curriculum".

# Lines naming the level, the programme or the publisher. None of these is a
# learning area, and accepting one is worse than finding nothing: sub-strands
# key on (grade, subject, strand, sub_strand), so every design that resolves to
# the same wrong subject overwrites the previous one's sub-strands.
_BANNER = re.compile(
    r"^(GRADE\b|SENIOR\b|JUNIOR\b|UPPER\b|LOWER\b|PRE\s*-?\s*PRIMARY\b|"
    r"DIPLOMA\b|CERTIFICATE\b|TEACHER\s+EDUCATION\b|"
    r"BASIC EDUCATION\b|PRIMARY SCHOOL\b|SECONDARY SCHOOL\b|EARLY YEARS\b|"
    r"KENYA INSTITUTE|A SKILLED|REPUBLIC OF|MINISTRY OF|CURRICULUM DESIGN)",
    re.IGNORECASE,
)

# A resolved subject that is really the level under another spelling.
_LEVEL_WORDS = re.compile(
    r"^(diploma|teacher\s+education|pre\s*-?\s*primary|lower\s+primary|"
    r"upper\s+primary|junior\s+school|senior\s+school|basic\s+education|"
    r"general\s+curriculum)",
    re.IGNORECASE,
)
# A pathway label carrying the index this pipeline assigned it, e.g.
# "Pure Sciences #2". That is a group, never a learning area.
_INDEXED_PATHWAY = re.compile(r"#\s*\d+\s*$")

# "Grade 9", "Grade9", "GRADE-9", "grade_9". The separator was a REQUIRED
# space, so this matched the words on a cover page and matched none of the
# slugs the system itself uses — which is how the fallback to the grade the
# operator declared could never fire.
_GRADE_NUM = re.compile(r"\bGRADE[\s\-_]*(\d{1,2})\b", re.IGNORECASE)

_LEVEL_BY_GRADE = {
    1: "Lower Primary", 2: "Lower Primary", 3: "Lower Primary",
    4: "Upper Primary", 5: "Upper Primary", 6: "Upper Primary",
    7: "Junior School", 8: "Junior School", 9: "Junior School",
    10: "Senior School", 11: "Senior School", 12: "Senior School",
}


def _looks_like_subject(line: str) -> bool:
    line = line.strip()
    if not (3 <= len(line) <= 45):
        return False
    if _BANNER.match(line) or _INDEXED_PATHWAY.search(line) or _LEVEL_WORDS.match(line):
        return False
    letters = sum(c.isalpha() for c in line)
    return letters >= 3 and letters / len(line) > 0.6


_MONTHS = (
    "january|february|march|april|may|june|july|august|september|october|"
    "november|december|jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec"
)
# Tokens that decorate a KICD filename without naming the learning area.
_FILENAME_NOISE = re.compile(
    rf"\.(pdf|docx?)$|\bgrades?\s*\d{{1,2}}(\s*[-–]\s*\d{{1,2}})?\b|\bdte\b|"
    rf"\bpp\s*[12]\b|\brevised\b|\bfinal\b|\bcurriculum\b|\bdesigns?\b|"
    rf"\b(20\d{{2}})\b|\b({_MONTHS})\b",
    re.IGNORECASE,
)


def _known_subjects() -> dict[str, str]:
    """Every learning area KICD publishes, keyed for case-insensitive lookup.

    The catalogue is the strongest signal available: a cover line that *is* a
    known learning area needs no heuristics, and a heuristic that disagrees with
    it is wrong.
    """
    from .curriculum_catalogue import EXPECTED_SUBJECTS

    out: dict[str, str] = {}
    for names in EXPECTED_SUBJECTS.values():
        for name in names:
            out[re.sub(r"[^a-z0-9]+", "", name.lower())] = name
    return out


def _match_known_subject(candidate: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "", (candidate or "").lower())
    return _known_subjects().get(key, "") if key else ""


def subject_from_filename(title: str) -> str:
    """The learning area named by a document's filename.

    KICD filenames say it plainly — "Grade 1-3 CRE - Revised.pdf",
    "Chemistry Grade 12 - March 2026.pdf", "DTE SOCIAL STUDIES.pdf" — once the
    grade, programme and revision tokens are stripped.
    """
    cleaned = _FILENAME_NOISE.sub(" ", title or "")
    cleaned = re.sub(r"[_\-–—]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .-")
    return cleaned


def _looks_like_a_heading(line: str) -> bool:
    """A title-page heading, not a sentence lifted out of the body.

    "Self-Awareness As Learners Talk About Their N" and "Of The Basic Education
    Curriculum." both passed the old test; both are prose.
    """
    line = line.strip()
    if not line or line.endswith((".", ",", ";", ":")):
        return False
    words = line.split()
    if not (1 <= len(words) <= 6):
        return False
    # Covers are set in capitals or title case; running prose is neither.
    letters = [c for c in line if c.isalpha()]
    if not letters:
        return False
    if sum(c.isupper() for c in letters) / len(letters) > 0.8:
        return True
    return all(w[:1].isupper() or not w[:1].isalpha() for w in words)


def _subject_from_cover(text: str) -> str:
    """The learning area as printed on the title page."""
    lines = [l.strip() for l in text.split("\n")[:60] if l.strip()]

    for line in lines:
        known = _match_known_subject(line)
        if known:
            return known

    for index, line in enumerate(lines):
        if not re.search(r"CURRICULUM\s+DESIGN", line, re.IGNORECASE):
            continue

        # Usual layout: the learning area is the next usable line.
        for candidate in lines[index + 1: index + 4]:
            if _looks_like_subject(candidate) and _looks_like_a_heading(candidate):
                return candidate

        # Diploma covers invert it, naming the area before the words.
        for candidate in reversed(lines[max(0, index - 3): index]):
            if _looks_like_subject(candidate) and _looks_like_a_heading(candidate):
                return candidate

    match = re.search(r"LEARNING AREA\s*:\s*([^\n]{3,45})", text, re.IGNORECASE)
    return match.group(1).strip() if match else ""


# Only the title page decides the grade. A design's body mentions other grades
# constantly ("as introduced in Grade 1"), so searching the whole document filed
# a Pre-Primary design under Grade 1.
_COVER_LINES = 60


def _cover_text(text: str) -> str:
    return "\n".join(text.split("\n")[:_COVER_LINES])


def _grade_number(grade: str) -> int:
    """The numeric grade in a slug, or 0 for pre-primary and DTE."""
    match = re.search(r"grade-(\d{1,2})$", str(grade or ""))
    return int(match.group(1)) if match else 0


def _grade_from_text(text: str, meta: dict[str, Any]) -> tuple[str, str]:
    """Grade and level, read as a number so 10-12 are not mistaken for 1-2."""
    cover = _cover_text(text)
    upper = cover.upper()

    if "DIPLOMA IN TEACHER EDUCATION" in upper:
        return "grade-dte", "Diploma in Teacher Education (Pre-Primary and Primary)"

    # Pre-primary first: those covers carry a bare "1" or "2" that a numeric
    # grade match would otherwise claim.
    if re.search(r"\bPP\s*2\b|PRE\s*-?\s*PRIMARY\s*2", upper):
        return "grade-pp2", "Pre-Primary"
    if re.search(r"\bPP\s*1\b|PRE\s*-?\s*PRIMARY", upper):
        return "grade-pp1", "Pre-Primary"

    match = _GRADE_NUM.search(cover)
    if match:
        number = int(match.group(1))
        if 1 <= number <= 12:
            return f"grade-{number}", _LEVEL_BY_GRADE[number]

    # Fall back to what the ingesting catalogue declared. Normalised first:
    # the declared value is usually already a slug, and a slug is exactly what
    # a text pattern is worst at reading.
    declared_slug = normalize_grade(str(meta.get("grade") or ""))
    if declared_slug:
        return declared_slug, _grade_level_for(declared_slug) or str(meta.get("level") or "")

    declared = str(meta.get("grade") or meta.get("level") or "")
    declared_match = _GRADE_NUM.search(declared)
    if declared_match:
        number = int(declared_match.group(1))
        if 1 <= number <= 12:
            return f"grade-{number}", _LEVEL_BY_GRADE[number]
    if "PP2" in declared.upper():
        return "grade-pp2", "Pre-Primary"
    if "PP1" in declared.upper() or "PRE-PRIMARY" in declared.upper():
        return "grade-pp1", "Pre-Primary"

    return "", ""


# An essence statement is a paragraph. These are the headings that follow one in
# the KICD designs, and the point at which it must stop.
_AFTER_ESSENCE = re.compile(
    r"^\s*(?:\d{1,4}:\d{1,5}\s\s)?\s*"
    r"(?:subject\s+general\s+learning\s+outcomes"
    r"|general\s+learning\s+outcomes"
    r"|summary\s+of\s+strands"
    r"|strand\s+\d"
    r"|lesson\s+allocation"
    r"|suggested\s+assessment"
    r"|level\s+learning\s+outcomes"
    r"|table\s+of\s+contents)",
    re.IGNORECASE,
)

# A hard ceiling, because a heading this does not know still must not swallow
# the document.
MAX_ESSENCE_CHARS = 2_500


def _extract_essence_statement(text: str) -> str:
    """The essence paragraph, not the rest of the design.

    The old pattern ended at a line of four or more capitals. Every line of a
    rendered design is prefixed with its "200:12  " address, so no line ever
    matched that lookahead and the capture ran to the end of the document —
    which is how a 31,689-character design was stored as its own essence
    statement, and then injected into every prompt TWICE on top of the copy
    already there. That is the context-duplication defect this codebase was
    built to prevent, arriving through a field nobody suspected.
    """
    match = re.search(r"ESSENCE STATEMENT\s*\n+", text, re.IGNORECASE)
    if not match:
        return ""

    collected: list[str] = []
    for line in text[match.end():].split("\n"):
        if _AFTER_ESSENCE.match(line):
            break
        stripped = line.strip()
        if stripped.startswith("[PAGE ") and collected:
            # A page break inside the paragraph is fine; one before any prose
            # means the statement was empty.
            continue
        collected.append(line)
        if sum(len(c) for c in collected) > MAX_ESSENCE_CHARS:
            break

    return "\n".join(collected).strip()[:MAX_ESSENCE_CHARS]




# Each criterion, and the words in a sub-strand's own text that make it apply.
_HAZARD_CRITERIA: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Verify all chemical or biological materials are non-toxic and age-appropriate",
     ("chemical", "reagent", "acid", "solution", "specimen", "culture", "fertilizer",
      "pesticide", "paint", "glue", "dye")),
    ("Ensure procedures with heat, fire, or smoke specify adult supervision and fire safety",
     ("heat", "flame", "fire", "burner", "boil", "candle", "smoke", "cook", "stove")),
    ("Ensure tools/equipment (cutters, hoes, knives) include explicit handling precautions",
     ("knife", "cutter", "scissors", "blade", "hoe", "panga", "saw", "needle", "nail")),
    ("Check that soil/manure activities mandate washing hands with soap and water afterwards",
     ("soil", "manure", "compost", "digging", "planting", "garden", "seedling")),
    ("Verify animal handling steps include hygiene, gentle restraint, and bite precautions",
     ("animal", "livestock", "poultry", "goat", "cattle", "rabbit", "pet", "insect")),
    ("Ensure any walk outside the classroom is supervised and the route is checked first",
     ("nature walk", "field trip", "excursion", "visit", "outdoor", "neighbourhood")),
    ("Ensure physical movement has space, a non-slip surface and no forced posture",
     ("yoga", "asana", "posture", "stretch", "exercise", "dance", "athletic")),
)


def _hazard_criteria(text: str, experiments: list[str]) -> list[str]:
    """The hazard checks this sub-strand's own content actually warrants."""
    haystack = (text + " " + " ".join(experiments)).lower()
    return [
        criterion for criterion, signals in _HAZARD_CRITERIA
        if any(signal in haystack for signal in signals)
    ]




class CurriculumExtractorService:
    """Extracts curriculum specifications/blueprints from raw datasets.
    Generates tailored guidance, safety hazard criteria, and dynamic agent prompts
    (Generator, Reviewer with Hazard Check, Multi-Agent Approvers) for downstream pipeline stages."""

    def ingest_raw_curriculum(
        self, raw_input: dict[str, Any] | str, strict: bool = True
    ) -> dict[str, Any]:
        """Ingest a design. With ``strict`` (the default), an incomplete result
        raises PARTIAL_INGEST after the work that succeeded has been persisted.

        Raising instead of persisting would throw away four good learning areas
        in order to report three bad ones. Persisting and returning quietly let
        a half-ingested grade look finished, which is how three learning areas
        sat unnoticed through several rounds of generation. So: keep the work,
        then fail loudly.
        """
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

        # KICD publishes Pre-Primary as one document holding seven learning
        # areas. Ingested whole, all seven were filed under the cover title and
        # overwrote one another's sub-strands, so a request for Language
        # Activities came back with Christian Religious Education. Split first.
        from .curriculum_catalogue import expected_subjects
        from .design_sections import split_learning_areas

        # Give the splitter the grade's published names so a banner reading
        # "CHRISTIAN RELIGIOUS EDUCATION ACTIVITIES" is filed as "Christian
        # Religious Education" — the name the catalogue, the save guard and the
        # structure report all use. Filed under the banner's own wording, a
        # correctly-split learning area reads as "not ingested".
        probe_grade, _probe_level = _grade_from_text(raw_text, payload_meta)
        published = expected_subjects(probe_grade) if probe_grade else []

        try:
            sections = split_learning_areas(raw_text, published)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not test for combined learning areas: %s", exc)
            sections = []

        if len(sections) < 2:
            return self._ingest_one(raw_text, payload_meta)

        grade = probe_grade
        from .design_sections import missing_learning_areas

        absent = missing_learning_areas(sections, published) if published else []
        if absent:
            # The catalogue says these exist for this grade and the document did
            # not yield them. Saying so at ingest is the difference between a
            # console that reads "(not ingested)" with no explanation and one
            # that names what is missing and from where.
            logger.error(
                "Design for %s yielded %d of %d published learning areas. MISSING: %s. "
                "Their content will be absent from every downstream generation.",
                grade, len(sections), len(published), ", ".join(absent),
            )
        logger.info(
            "Design holds %d learning areas; ingesting each separately: %s",
            len(sections), ", ".join(s.learning_area for s in sections),
        )

        results: list[dict[str, Any]] = []
        for section in sections:
            section_meta = {
                **payload_meta,
                "grade": grade or payload_meta.get("grade", ""),
                "learning_area": section.learning_area,
                "section_pages": f"{section.start_page}-{section.end_page}",
            }
            try:
                results.append(
                    self._ingest_one(
                        section.text, section_meta,
                        learning_area=section.learning_area,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                # One unreadable learning area must not cost the other six.
                logger.warning("Learning area '%s' failed to ingest: %s", section.learning_area, exc)
                results.append({
                    "status": "failed",
                    "subject": section.learning_area,
                    "error": str(exc)[:300],
                })

        succeeded = [r for r in results if r.get("status") == "success"]
        primary = succeeded[0] if succeeded else results[0]

        # An area the splitter never produced fails differently from one that
        # was produced and then failed to parse. Both must be visible, and both
        # must be named, or the only symptom is a dropdown entry reading
        # "(not ingested)" with nothing to act on.
        never_split = [
            {"subject": name, "status": "not_found_in_document",
             "detail": "The splitter did not locate this learning area in the design."}
            for name in absent
        ]
        areas = [
            {"subject": r.get("subject"), "status": r.get("status"),
             "design_id": r.get("design_id"), "substrand_count": r.get("substrand_count", 0),
             "extraction_status": r.get("extraction_status", "")}
            for r in results
        ] + never_split
        complete = bool(published) and not absent and not [
            r for r in results if r.get("status") != "success"
        ]

        outcome = {
            **primary,
            "combined_design": True,
            "learning_areas": areas,
            "learning_area_count": len(areas),
            "expected_learning_areas": list(published),
            "learning_areas_ingested": len(succeeded),
            "learning_areas_missing": absent,
            "complete": complete,
            "status": "success" if complete else "partial",
        }

        if strict and not complete:
            # "not_found_in_document" is already reported as missing; counting
            # it again as a parse failure named the same three areas twice and
            # made the message read as six problems instead of three.
            failed = [
                a for a in areas
                if a.get("status") not in ("success", "not_found_in_document", None)
            ]
            summary = []
            if absent:
                summary.append(f"not found in the document: {', '.join(absent)}")
            if failed:
                summary.append(
                    "failed to parse: "
                    + ", ".join(str(a.get("subject")) for a in failed)
                )
            raise_api_error(
                "PARTIAL_INGEST",
                f"Ingested {len(succeeded)} of {len(published)} learning areas for "
                f"{grade}. Everything that succeeded has been saved; "
                + "; ".join(summary)
                + ". Generation for the missing areas would be ungrounded.",
                detail=outcome,
            )

        return outcome

    def _ingest_one(
        self, raw_text: str, payload_meta: dict[str, Any], learning_area: str = "",
    ) -> dict[str, Any]:
        """Ingest one learning area — the whole document when it holds only one."""
        # 1. Generate Root Dataset DNA
        dataset_id = payload_meta.get("file_id") or f"ds_{hashlib.sha256(raw_text[:200].encode()).hexdigest()[:10]}"
        if learning_area:
            dataset_id = f"{dataset_id}::{re.sub(r'[^a-z0-9]+', '-', learning_area.lower()).strip('-')}"
        dataset_dna = artifact_dna_service.generate_dataset_dna(
            dataset_id=dataset_id,
            raw_text=raw_text,
            source_meta=payload_meta,
        )

        # 2. Parse curriculum metadata & structural sections
        #
        # Narrated from here on. "Read but no design" was diagnosed across four
        # sessions by inference — a count is wrong on one screen, so something
        # upstream must be misreading something — because an ingest ran twenty
        # seconds and said nothing about what it did.
        from .run_log import step

        design = self._parse_curriculum_text(
            raw_text, payload_meta, dataset_dna.dna_id, learning_area=learning_area
        )
        step(
            "Read the cover",
            f"{design.subject or 'no learning area'} · {design.grade or 'NO GRADE'} · "
            f"{design.level or 'no level'}",
            "ok" if design.subject and design.grade else "warn",
        )
        step(
            "Read the structure",
            f"{len(design.substrands)} sub-strand(s) across "
            f"{len({s.strand_name for s in design.substrands if s.strand_name})} strand(s)",
            "ok" if design.substrands else "warn",
        )

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

        # 3b. Where the patterns did not reach, read it with the agent.
        #
        # The regex reads the designs it was written against and returns
        # nothing for the rest: a Grade 9 design whose PDF reader flattened the
        # four-column table came back with zero sub-strands, and an empty
        # design is indistinguishable in the console from one nobody has run.
        # A model does not care how the columns landed.
        #
        # Only where it is needed. Reading every design with a model costs a
        # call per document for designs the patterns already read correctly,
        # and this runs inside the ingest job, so it is on Celery and its steps
        # appear in the same progress the operator is already watching.
        self._read_with_agent_if_thin(design, raw_text)

        # 4. Generate Subject, Strand, and Substrand DNAs
        self._generate_curriculum_dna_tree(design, dataset_dna.dna_id, raw_text)

        # 5. Persist to PostgreSQL database
        self._persist_to_db(design)
        step("Design stored", f"{design.design_id} under {design.grade}", "ok")

        # 6. Synchronize with Langfuse dataset item
        langfuse_sync_result = self._sync_to_langfuse(design)
        step("Filed to Langfuse", str(langfuse_sync_result or "skipped"), "ok")

        # The regex extractor cannot read every design. KICD's PDFs render each
        # sub-strand table as wrapped columns, so a Pre-Primary sub-strand
        # arrives as "1.1.1", "Greetings", "and Farewell", "(3 lessons)" on four
        # separate lines and matches nothing. Reporting that as a successful
        # ingest is how a learning area with zero sub-strands looked identical
        # in the console to a complete one.
        from .curriculum_catalogue import expected_structure

        found = len(design.substrands)
        expected = expected_structure(design.grade, design.subject).get("sub_strand_count", 0)
        if not expected:
            extraction_status = "complete" if found else "empty"
        elif found >= expected:
            extraction_status = "complete"
        elif found:
            extraction_status = "partial"
        else:
            extraction_status = "empty"

        if extraction_status != "complete":
            logger.warning(
                "Ingested '%s' (%s) with %d sub-strand(s)%s. Structural extraction is "
                "unreliable on this design; generate the strands and sub-strands with the "
                "curriculum agents and save them.",
                design.subject, design.grade, found,
                f" against {expected} expected" if expected else "",
            )
        else:
            logger.info(
                "Successfully ingested curriculum design '%s' (%s - %s) with %d sub-strand blueprints.",
                design.subject, design.grade, design.level, found,
            )

        # Sections the parser could not read. Previously each of these became a
        # fabricated sub-strand named after its strand, so an unreadable design
        # and a readable one produced the same count and nothing said which was
        # which. Naming them is what tells the operator where to point the
        # generators.
        unparsed = list(getattr(self, "_last_unparsed", []) or [])

        return {
            "status": "success",
            "extraction_status": extraction_status,
            "expected_substrand_count": expected,
            "unparsed_sections": unparsed,
            "next_step": (
                f"{len(unparsed)} section(s) could not be parsed into sub-strands "
                f"({', '.join(unparsed[:6])}). Generate them with "
                f"/factory/generate-substrands, which reads the design with a model "
                f"rather than a regex."
            ) if unparsed else "",
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
        self, text: str, meta: dict[str, Any], dataset_dna_id: str,
        learning_area: str = "",
    ) -> ParsedCurriculumDesign:
        # A section of a combined design has no cover of its own — the document's
        # banner page already said which learning area this is, and that beats
        # every other signal.
        subject = learning_area.strip()

        # The document's own cover is the authority on what it teaches. The
        # ingesting catalogue only knows the pathway a link sat under, which for
        # senior school is a group ("Pure Sciences") rather than a learning area.
        if not subject:
            subject = _subject_from_cover(text)

        if not subject and meta.get("title") and not learning_area:
            from_name = subject_from_filename(str(meta["title"]))
            subject = _match_known_subject(from_name) or (
                from_name if _looks_like_subject(from_name) else ""
            )

        if not subject:
            declared = str(meta.get("subject") or "").strip()
            if declared and _looks_like_subject(declared):
                subject = declared

        if not subject:
            logger.warning(
                "Could not read a learning area from the cover of '%s' (file_id=%s). "
                "Filing as 'General Curriculum' — check the extraction, because designs "
                "sharing a subject overwrite each other's sub-strands.",
                meta.get("title", "?"), meta.get("file_id", "?"),
            )
        subject = subject.title() if subject else "General Curriculum"

        if learning_area:
            # A section of a combined design has no cover of its own. Its text
            # is prose, and that prose says things like "...prepare learners to
            # learn similar concepts at PP2" — a transition sentence, not a
            # declaration. Reading a grade out of it filed Mathematical
            # Activities, CRE and HRE under grade-pp2 while the operator was
            # ingesting PP1, so they read as "(not ingested)" for the grade
            # they belong to. The whole document's cover already settled this.
            grade = normalize_grade(str(meta.get("grade") or ""))
            level = _grade_level_for(grade) or str(meta.get("level") or "")
            if not grade:
                grade, level = _grade_from_text(text, meta)
        else:
            grade, level = _grade_from_text(text, meta)

        if not grade:
            # Guessing a grade silently files a design under the wrong cohort,
            # which is invisible until questions are generated from it — and
            # this defaulted to grade-7, so Grade 9 designs went into Grade 7
            # while Grade 9 itself read as empty. The dataset the operator
            # chose is a fact, not a guess: use it, and refuse only when there
            # is nothing at all to go on.
            declared = normalize_grade(str(meta.get("grade") or ""))
            if declared:
                grade = declared
                level = _grade_level_for(declared) or str(meta.get("level") or "")
                logger.warning(
                    "No grade on the cover of '%s' (file_id=%s); filing under %s, "
                    "the dataset it was ingested from.",
                    subject, meta.get("file_id", "?"), grade,
                )
            else:
                raise_api_error(
                    "INVALID_GRADE_DATASET",
                    f"No grade could be read from the cover of '{subject}', and "
                    f"the dataset it came from names none either. Filing it "
                    f"under a guess would put this design in another cohort's "
                    f"curriculum, where it stays invisible until questions are "
                    f"generated from it.",
                )

        subject_code = "".join([w[0] for w in subject.split() if w]).upper()[:4]

        essence_statement = _extract_essence_statement(text)

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
            # The document itself, not just its size. Every downstream agent —
            # strand architect, sub-strand generator, reviewer — needs the
            # source to work from, and without it they generate from prior
            # knowledge instead of from the design KICD published.
            raw_payload={
                "meta": meta,
                "char_count": len(text),
                "source_text": text[:400_000],
            },
            metadata={"source": meta.get("source", "raw_ingest"), "file_id": meta.get("file_id", "")},
            dataset_dna_id=dataset_dna_id,
        )



    # KICD's own summary table, which every design carries and which is the
    # only place the whole spine appears in one clean list:
    #
    #   1.0 Conservation of Resources 1.1 Conserving Animal Feed: Hay 12
    #   1.2 Conserving Leftover Food 11
    #   1.3 Integrated Farming 12
    #
    # The detail pages that follow are a four-column table flattened by the PDF
    # reader, so a sub-strand arrives as "1.1 Conserving" / "Animal Feed:" /
    # "Hay" / "(12 lessons)" on four lines and matches nothing. That is why a
    # Grade 9 design ingested with zero sub-strands and looked, in the console,
    # exactly like one that had never been run.
    _SUMMARY_ROW = re.compile(
        r"^[ \t]*(?:(\d+\.0)\s+([A-Za-z][A-Za-z ,'&/()-]{3,60}?)\s+)?"
        r"(\d+\.[1-9]\d?)\s+([A-Za-z][^\n]{3,80}?)\s+(\d{1,3})[ \t]*$",
        re.MULTILINE,
    )

    def _substrands_from_summary(
        self, text: str, subject: str, grade: str, level: str
    ) -> list[ParsedSubstrand]:
        """The strands and sub-strands, read off the design's own summary."""
        window = text
        head = re.search(r"SUMMARY OF STRANDS AND SUB[\s-]*STRANDS", text, re.IGNORECASE)
        if head:
            # Stop at the first strand heading: the detail pages repeat these
            # numbers in wrapped columns and would be read as more rows.
            tail = re.search(r"\n[ \t]*STRAND\s+\d+\.\d", text[head.end():], re.IGNORECASE)
            window = text[head.end(): head.end() + (tail.start() if tail else 4000)]

        out: list[ParsedSubstrand] = []
        strand_id, strand_label = "", ""
        for row in self._SUMMARY_ROW.finditer(window):
            if row.group(1) and row.group(2):
                strand_id = row.group(1)
                strand_label = row.group(2).strip()
            name = row.group(4).strip().rstrip(".")
            if not strand_label or not name:
                continue
            out.append(ParsedSubstrand(
                strand_id=strand_id,
                strand_name=strand_label,
                sub_strand_id=row.group(3),
                sub_strand_name=name,
                allocated_hours=f"{row.group(5)} lessons",
                slos=[], learning_experiences=[], key_inquiry_questions=[],
                core_competencies=[], values=[], assessment_rubrics={},
                required_diagrams=[], experiments=[], safety_hazards_to_check=[],
                pedagogical_guidance="", prompt_package={},
                raw_snippet=row.group(0).strip(),
            ))
        return out

    def _extract_substrands(
        self, text: str, subject: str, grade: str, level: str
    ) -> list[ParsedSubstrand]:
        substrands: list[ParsedSubstrand] = []
        unparsed: list[str] = []
        # Cleared here, not appended to, so one design's failures are never
        # reported against the next one ingested in the same process.
        self._last_unparsed = []

        # "Sub Strand 1.1 Our God" contains "Strand 1.1 Our God", so this used to
        # match every SUB-strand heading as a strand — splitting the design at
        # each one and leaving the real sub-strands unreachable inside sections
        # that were themselves sub-strands. A strand heading starts a line.
        # "STRAND 1.0: CONSERVATION OF RESOURCES" — the colon is how KICD
        # writes it, and requiring whitespace straight after the number matched
        # none of the Grade 9 designs.
        strand_pattern = r"(?:^|\n)[ \t]*(STRAND\s+(\d+\.\d+)\s*[:.\-]?\s*([^\n]+))"
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
                # This used to fabricate ONE sub-strand named after the strand,
                # carrying the strand's whole body — every outcome of every
                # real sub-strand shredded into one list. That is where
                # "1.0 CREATION / 1.0 CREATION" with 54 fragments came from,
                # and Language Activities' six themes read as six strands each
                # holding itself.
                #
                # A strand whose sub-strands cannot be read has NO sub-strands
                # as far as this parser is concerned. Storing a placeholder puts
                # something in the database that looks like content and is not,
                # and everything downstream then measures it as if it were. The
                # LLM strand and sub-strand generators exist precisely for these
                # layouts; leaving the strand empty is what routes the operator
                # to them.
                unparsed.append(strand_name)
                logger.warning(
                    "No sub-strand could be read under '%s' (%s, %s). Recording "
                    "none — generate them with /factory/generate-substrands.",
                    strand_name, subject, grade,
                )
                continue

            for j, sbm in enumerate(sub_matches):
                sub_id = sbm.group(1).strip()
                sub_name = sbm.group(2).strip()
                # The design's own figure, in the design's own unit, or nothing.
                hours = sbm.group(3).strip() if sbm.group(3) else ""

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

        # A record that parsed but came out shredded is no better than one that
        # was fabricated: its outcomes are column fragments, and everything
        # downstream will measure them as if they were outcomes. Drop it and
        # leave the strand to the generators.
        kept: list[ParsedSubstrand] = []
        for candidate in substrands:
            report = substrand_integrity.check(
                grade, subject, candidate.strand_name, candidate.sub_strand_name,
                slos=candidate.slos, allocated=candidate.allocated_hours,
            )
            if report.usable:
                kept.append(candidate)
                continue
            unparsed.append(candidate.sub_strand_name)
            logger.warning(
                "Dropped '%s' (%s, %s): %s",
                candidate.sub_strand_name, subject, grade,
                "; ".join(p["check"] for p in report.problems),
            )

        if unparsed:
            logger.warning(
                "%s (%s): %d section(s) could not be parsed into sub-strands — %s. "
                "Generate them with /factory/generate-substrands.",
                subject, grade, len(unparsed), ", ".join(unparsed[:6]),
            )
        self._last_unparsed = unparsed

        # The detail pages are a four-column table flattened by the PDF reader,
        # so a sub-strand arrives as "1.1 Conserving" / "Animal Feed:" / "Hay"
        # / "(12 lessons)" on four lines and matches nothing. When that happens
        # the design's own SUMMARY table still holds the whole spine in one
        # clean list — strand, sub-strand and lesson count — and a design with
        # the spine and no detail is worth immeasurably more than an empty one,
        # which is what a Grade 9 ingest produced and what looked, in the
        # console, exactly like a design that had never been run.
        summary = self._substrands_from_summary(text, subject, grade, level)
        if summary:
            have = {s.sub_strand_name.strip().lower() for s in kept}
            added = [s for s in summary if s.sub_strand_name.strip().lower() not in have]
            if added:
                logger.info(
                    "%s (%s): %d sub-strand(s) read from the design's summary table "
                    "that the detail pages did not yield.",
                    subject, grade, len(added),
                )
                kept = kept + added
        return kept

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
        # "Suggested Assessment Rubric", "Rubrics", and "Rubric s" — the stray
        # space is the PDF's letter spacing. The word "Formative" appears in no
        # KICD design; searching for it matched nothing, in every subject, and
        # every rubric was silently generated instead of read.
        rubric_match = re.search(
            r"Suggested\s+(?:Formative\s+)?Assessment\s+Rubric\s*s?\s*\n*(.*?)(?=STRAND|\Z)",
            body,
            re.DOTALL | re.IGNORECASE,
        )
        if rubric_match:
            rubrics.append({"raw_rubric": rubric_match.group(1)[:1200]})

        # 6. Discover Required Diagrams & Visual Models
        # What the design ITSELF asks to be looked at, not a list of things one
        # subject happens to need. The keywords were "drip irrigation", "zai
        # pit", "scarecrow", "compost", "nursery bed", "soil profile" — an
        # agriculture syllabus, scanned for in every learning area, so diagram
        # discovery was agriculture-shaped for Religious Education, Language
        # Activities and everything else.
        #
        # Every design states its own visual requirements in the learning
        # experiences: "observe pictures of Adam and Eve", "identify the
        # parents of Jesus from a chart", "observe charts of children
        # participating in church activities". Those are the diagrams, and they
        # are already in the document.
        required_diagrams = []
        _VISUAL = re.compile(
            r"\b(picture|pictures|chart|charts|diagram|diagrams|drawing|drawings|"
            r"illustration|illustrations|map|maps|photograph|photographs|poster|"
            r"posters|model|models|flashcard|flashcards|graph|graphs|table|"
            r"wallchart|wallcharts)\b",
            re.IGNORECASE,
        )
        for line in body.split("\n"):
            cleaned = re.sub(r"^\s*[\u2022\-\*\u25cf]\s*", "", line).strip()
            if len(cleaned) < 12 or not _VISUAL.search(cleaned):
                continue
            # The experience as the design words it, so the brief that follows
            # is grounded in an instruction KICD actually gave.
            required_diagrams.append(cleaned[:180])
        required_diagrams = list(dict.fromkeys(required_diagrams))[:6]

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

        # 8. Hazard audit criteria — only the ones this sub-strand can incur.
        #
        # All five were attached to every sub-strand of every subject, so a
        # Pre-Primary lesson about greetings and yoga carried rabies precautions
        # and hoe-handling criteria. A hazard list that does not apply teaches
        # the reader to skip the field where it does.
        safety_hazards = _hazard_criteria(body, experiments)

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
                # Deliberately partial: notes_content, diagram_info and the rest
                # are bound at generation time, not here. They must survive as
                # placeholders in the stored template.
                return langfuse_context_service._render_template(
                    tpl, prompt_vars, partial=True
                )
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

    def _read_with_agent_if_thin(
        self, design: ParsedCurriculumDesign, raw_text: str,
    ) -> None:
        """Fill in what the patterns could not read, from the agent's reading.

        Additive only. A sub-strand the regex read carries its SLOs, its
        learning experiences and its own citations; the agent's version of the
        same sub-strand is not better, and replacing it would trade a parse
        that worked for one that costs money. Only names the regex never
        produced are added.
        """
        from ..settings import settings

        if not getattr(settings, "design_agent_enabled", True):
            return

        from .curriculum_catalogue import expected_structure

        expected = expected_structure(design.grade, design.subject).get("sub_strand_count", 0)
        found = len(design.substrands)
        # Thin enough to be worth a call: nothing at all, or well short of what
        # KICD publishes for this learning area.
        if found and (not expected or found >= expected):
            return

        from . import design_agent

        try:
            reading = design_agent.read(raw_text, grade=design.grade)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "The design agent could not read %s (%s): %s. Keeping the %d "
                "sub-strand(s) the patterns found.",
                design.subject, design.grade, exc, found,
            )
            return

        have = {s.sub_strand_name.strip().lower() for s in design.substrands}
        added = 0
        for strand in reading.design.get("strands") or []:
            for sub in strand.get("sub_strands") or []:
                name = str(sub.get("sub_strand_name") or "").strip()
                if not name or name.lower() in have:
                    continue
                design.substrands.append(ParsedSubstrand(
                    strand_id="", strand_name=str(strand.get("strand_name") or "").strip(),
                    sub_strand_id="", sub_strand_name=name,
                    allocated_hours=str(sub.get("allocated_time") or ""),
                    slos=list(sub.get("slos") or []),
                    learning_experiences=list(sub.get("learning_experiences") or []),
                    key_inquiry_questions=list(sub.get("key_inquiry_questions") or []),
                    core_competencies=list(sub.get("core_competencies") or []),
                    values=list(sub.get("values") or []),
                    assessment_rubrics={},
                    required_diagrams=list(sub.get("required_diagrams") or []),
                    experiments=list(sub.get("experiments") or []),
                    safety_hazards_to_check=list(sub.get("safety_hazards_to_check") or []),
                    pedagogical_guidance="",
                    prompt_package={},
                    theme=str(sub.get("theme") or ""),
                    pertinent_contemporary_issues=list(
                        sub.get("pertinent_and_contemporary_issues") or []),
                    source_pages=list(sub.get("source_pages") or []),
                    raw_snippet="",
                ))
                have.add(name.lower())
                added += 1

        design.raw_payload["design_agent"] = {
            **reading.to_dict(), "added": added, "found_by_patterns": found,
        }
        if added:
            logger.info(
                "The design agent added %d sub-strand(s) to %s (%s) that the "
                "patterns did not read; %d%% of its citations resolve.",
                added, design.subject, design.grade, reading.citation_percentage,
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

        # Prove it landed. An INSERT that ran without raising is not the same
        # fact as a row being there — a transaction rolled back elsewhere, a
        # different database than the reader is looking at, a constraint that
        # turned the write into a no-op — and every one of those looked like a
        # successful ingest with no design at the end of it. Sixteen documents
        # read, zero designs, no error anywhere.
        landed = fetch_one(
            "SELECT design_id, grade FROM curriculum_designs WHERE design_id = :design_id",
            {"design_id": design.design_id},
        )
        if not landed:
            raise_api_error(
                "SCHEMA_VALIDATION_FAILED",
                f"The design for {design.subject} ({design.grade}) was written and "
                f"is not there when read back. Nothing downstream can be built "
                f"from it, so this is a failed ingest rather than a quiet one.",
            )
        logger.info("Design %s stored for %s (%s).",
                    design.design_id, design.subject, landed.get("grade"))

        # Re-ingesting a design must leave it looking exactly as this run
        # describes it. Sub-strands upsert by name, so a renamed or dropped
        # sub-strand would otherwise survive forever and keep counting towards
        # the grade's required work, quietly inflating every coverage figure.
        written_keys: list[str] = []

        for s in design.substrands:
            written_keys.append(f"{s.strand_name}||{s.sub_strand_name}")
            execute(
                """
                INSERT INTO curriculum_substrands (
                    design_id, grade, subject, strand_id, strand_name, sub_strand_id, sub_strand_name,
                    theme, allocated_hours, slos, learning_experiences, key_inquiry_questions,
                    core_competencies, values, assessment_rubrics, required_diagrams,
                    experiments, pertinent_contemporary_issues, link_to_other_learning_areas,
                    source_pages, pedagogical_guidance, prompt_context, updated_at
                )
                VALUES (
                    :design_id, :grade, :subject, :strand_id, :strand_name, :sub_strand_id, :sub_strand_name,
                    :theme, :allocated_hours, CAST(:slos AS jsonb), CAST(:learning_exp AS jsonb),
                    CAST(:kiqs AS jsonb), CAST(:competencies AS jsonb), CAST(:values AS jsonb),
                    CAST(:rubrics AS jsonb), CAST(:diagrams AS jsonb), CAST(:experiments AS jsonb),
                    CAST(:pcis AS jsonb), :link_other, CAST(:source_pages AS jsonb),
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
                    theme = EXCLUDED.theme,
                    pertinent_contemporary_issues = EXCLUDED.pertinent_contemporary_issues,
                    link_to_other_learning_areas = EXCLUDED.link_to_other_learning_areas,
                    source_pages = EXCLUDED.source_pages,
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
                    "theme": s.theme,
                    "pcis": to_json(s.pertinent_contemporary_issues),
                    "link_other": s.link_to_other_learning_areas,
                    "source_pages": to_json(s.source_pages),
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

        self._prune_stale_substrands(design, written_keys)

    def _prune_stale_substrands(
        self, design: "ParsedCurriculumDesign", written_keys: list[str]
    ) -> None:
        """Drop sub-strands this design no longer contains.

        Deleting by design_id alone would be simpler, but sub-strands are keyed
        on (grade, subject, strand, sub_strand) and can legitimately be claimed
        by a newer design_id, so only rows still attributed to *this* design and
        absent from this run are removed.
        """
        if not written_keys:
            # An extraction that found nothing is far more likely to be a bad
            # parse than a genuinely empty design; deleting on that basis would
            # destroy good data.
            logger.warning(
                "Design %s produced no sub-strands; leaving existing rows untouched.",
                design.design_id,
            )
            return

        rows = fetch_all(
            """
            SELECT id, strand_name, sub_strand_name
            FROM curriculum_substrands
            WHERE design_id = :design_id
            """,
            {"design_id": design.design_id},
        )
        keep = set(written_keys)
        stale = [
            r["id"] for r in rows
            if f"{r['strand_name']}||{r['sub_strand_name']}" not in keep
        ]
        if not stale:
            return

        execute(
            "DELETE FROM curriculum_substrands WHERE id = ANY(:ids)",
            {"ids": stale},
        )
        logger.info(
            "Removed %d sub-strand(s) from %s that this re-ingest no longer contains.",
            len(stale), design.design_id,
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
