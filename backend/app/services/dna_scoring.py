"""Computed compliance metrics for DNA certificates.

Every score returned here carries the method that produced it and the evidence
it was drawn from. Nothing is asserted as a constant: a metric that cannot be
computed at generation time returns ``None`` with a ``pending`` method, which is
an honest answer, whereas a hardcoded ``0.98`` is not.

The lexical measures are deliberately simple and deterministic so they can be
unit tested. :func:`set_embedding_backend` swaps in a semantic backend without
changing any caller.
"""
from __future__ import annotations

import logging
import math
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

logger = logging.getLogger("cbc-dna-scoring")

_WORD = re.compile(r"[a-z0-9']+")

_STOPWORDS = frozenset("""
a an the and or but if then than that this these those of in on at to for from by with without
is are was were be been being am do does did done have has had having will would shall should
can could may might must it its as into over under about above below between during each such
which who whom whose what when where why how all any both few more most other some only own same
so too very not no nor own s t just don now learner learners pupil pupils grade
""".split())

# Pluggable semantic backend: (text_a, text_b) -> cosine similarity in [0, 1].
_embedding_similarity: Callable[[str, str], float] | None = None


def set_embedding_backend(fn: Callable[[str, str], float] | None) -> None:
    """Install a semantic similarity backend used in place of lexical overlap."""
    global _embedding_similarity
    _embedding_similarity = fn


@dataclass(slots=True)
class Score:
    """One metric, with how it was derived.

    ``value`` is ``None`` when the metric is not knowable at generation time.
    """

    value: float | None
    method: str
    evidence: str = ""
    sample_size: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ScoreSet:
    scores: dict[str, Score] = field(default_factory=dict)

    def add(self, name: str, score: Score) -> None:
        self.scores[name] = score

    def values_only(self) -> dict[str, float | None]:
        """Flat name → value map, for backward-compatible ``compliance_scores``."""
        return {name: s.value for name, s in self.scores.items()}

    def detail(self) -> dict[str, dict[str, Any]]:
        return {name: s.to_dict() for name, s in self.scores.items()}

    def mean(self) -> float | None:
        """Mean of the computable scores. Pending metrics are excluded, not zeroed."""
        computed = [s.value for s in self.scores.values() if s.value is not None]
        if not computed:
            return None
        return round(sum(computed) / len(computed), 4)

    def weakest(self, limit: int = 3) -> list[tuple[str, float]]:
        computed = [(n, s.value) for n, s in self.scores.items() if s.value is not None]
        return sorted(computed, key=lambda pair: pair[1])[:limit]


# ─────────────────────────────────────────────────────────────────────────────
# Text primitives
# ─────────────────────────────────────────────────────────────────────────────


# Light suffix stripping so "formation"/"forms"/"formed" and "horizon"/"horizons"
# count as the same concept. Deliberately crude — a real stemmer would be a
# dependency, and curriculum text is regular enough that suffix rules carry it.
_SUFFIXES = ("ational", "ization", "isation", "iveness", "fulness", "ousness",
             "ation", "ition", "ement", "ments", "ness", "tion", "sion",
             "ing", "ies", "ied", "est", "ers", "ment", "able", "ible",
             "ed", "es", "ly", "er", "s")


def _stem(word: str) -> str:
    for suffix in _SUFFIXES:
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def tokens(text: str) -> set[str]:
    return {
        _stem(w)
        for w in _WORD.findall((text or "").lower())
        if w not in _STOPWORDS and len(w) > 2
    }


def containment(needle: str, haystack: str) -> float:
    """Fraction of the needle's meaningful terms present in the haystack.

    Asymmetric on purpose: asking "is this SLO covered by these notes" is not the
    same question as "are these notes about this SLO".
    """
    a, b = tokens(needle), tokens(haystack)
    if not a:
        return 0.0
    return round(len(a & b) / len(a), 4)


def similarity(text_a: str, text_b: str) -> tuple[float, str]:
    """Semantic similarity if a backend is installed, else lexical Jaccard."""
    if _embedding_similarity is not None:
        try:
            return round(float(_embedding_similarity(text_a, text_b)), 4), "embedding_cosine"
        except Exception as exc:  # noqa: BLE001
            logger.warning("Embedding backend failed, falling back to lexical: %s", exc)

    a, b = tokens(text_a), tokens(text_b)
    if not a or not b:
        return 0.0, "lexical_jaccard"
    return round(len(a & b) / len(a | b), 4), "lexical_jaccard"


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"[.!?]+", text or "") if s.strip()]


def _flatten(value: Any, depth: int = 0) -> str:
    """Collect all human-readable text out of a nested generation payload."""
    if depth > 6 or value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return ""
    if isinstance(value, dict):
        return " ".join(_flatten(v, depth + 1) for v in value.values())
    if isinstance(value, (list, tuple)):
        return " ".join(_flatten(v, depth + 1) for v in value)
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# Grade-appropriate reading level
# ─────────────────────────────────────────────────────────────────────────────

# Target mean words-per-sentence by grade ordinal band, from the Piaget staging
# in master_agent_context.md §2: concrete operations first, formal operations later.
_READING_TARGETS: list[tuple[int, float]] = [
    (2, 8.0),    # PP1–PP2
    (5, 11.0),   # Grades 1–3
    (8, 15.0),   # Grades 4–6
    (11, 19.0),  # Grades 7–9
    (14, 23.0),  # Grades 10–12
    (99, 25.0),  # DTE
]


def _reading_target(grade_ordinal: int) -> float:
    for ceiling, target in _READING_TARGETS:
        if grade_ordinal <= ceiling:
            return target
    return 25.0


# A teacher's guide is read by an adult professional, usually in a second
# language and under time pressure. Sixteen words a sentence is the register
# that fits: plain, but not a four-year-old's.
_TEACHER_TARGET = 16.0


def reading_level_fit(text: str, grade_ordinal: int, audience: str = "learner") -> Score:
    """How close the prose sits to the expected complexity for its READER.

    Penalises both directions — text too dense for Grade 2 and text too thin for
    Grade 11 are both misaligned.

    Who the reader is has to be stated, because it is not always the learner.
    This measure marked a PP1 teacher's guide down to 0.65 for averaging 10.4
    words a sentence against a target of 8 — the target for a four-year-old, who
    is not going to read the guide. That is the same reader/learner confusion
    that once had pre-primary notes prescribing flowcharts, surviving in the
    validator after it was fixed in the prompt.
    """
    sents = _sentences(text)
    if len(sents) < 3:
        return Score(None, "pending_insufficient_text", "fewer than 3 sentences", len(sents))

    words_per_sentence = sum(len(_WORD.findall(s)) for s in sents) / len(sents)
    target = _TEACHER_TARGET if audience == "teacher" else _reading_target(grade_ordinal)
    # Gaussian falloff: within ~35% of target scores near 1.0.
    deviation = abs(words_per_sentence - target) / target
    value = round(math.exp(-((deviation / 0.45) ** 2)), 4)

    return Score(
        value,
        "sentence_length_vs_teacher_band" if audience == "teacher"
        else "sentence_length_vs_grade_band",
        f"{words_per_sentence:.1f} words/sentence against a target of {target:.0f} "
        f"for {'the teacher reading this' if audience == 'teacher' else 'this grade'}",
        len(sents),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Notes
# ─────────────────────────────────────────────────────────────────────────────


def score_notes(
    notes: dict[str, Any],
    blueprint_slos: list[Any],
    grade_ordinal: int,
    raw_source: str = "",
) -> ScoreSet:
    out = ScoreSet()
    body = _flatten(notes)
    word_count = len(_WORD.findall(body))

    slo_texts = [
        (s.get("text") or s.get("slo") or "") if isinstance(s, dict) else str(s)
        for s in (blueprint_slos or [])
    ]
    slo_texts = [t for t in slo_texts if t.strip()]

    if slo_texts:
        per_slo = [containment(t, body) for t in slo_texts]
        covered = sum(1 for c in per_slo if c >= 0.5)
        out.add("slo_coverage", Score(
            round(covered / len(slo_texts), 4),
            "slo_term_containment",
            f"{covered} of {len(slo_texts)} SLOs have at least half their key terms present",
            len(slo_texts),
        ))
        out.add("slo_depth", Score(
            round(sum(per_slo) / len(per_slo), 4),
            "mean_slo_term_containment",
            f"mean term coverage {sum(per_slo) / len(per_slo):.2f} across {len(slo_texts)} SLOs",
            len(slo_texts),
        ))
    else:
        out.add("slo_coverage", Score(None, "pending_no_blueprint_slos", "blueprint carried no SLOs"))

    modules = notes.get("modules") or notes.get("hour_modules") or notes.get("key_concepts") or notes.get("sections") or []
    module_count = len(modules) if isinstance(modules, list) else 0
    structural = [
        bool(notes.get("title")),
        module_count > 0,
        bool(notes.get("summary") or notes.get("intro")),
        any(isinstance(m, dict) and (m.get("common_misconceptions") or m.get("pedagogical_notes")) for m in modules)
        if isinstance(modules, list) else False,
        bool(notes.get("worked_examples") or notes.get("practical_connections")),
    ]
    out.add("structural_completeness", Score(
        round(sum(structural) / len(structural), 4),
        "required_section_presence",
        f"{sum(structural)} of {len(structural)} expected structures present, {module_count} modules",
        len(structural),
    ))

    # The guide is written TO the teacher. What is spoken to the learner is a
    # small, separate part of it, and the two are scored against the two
    # different people who have to understand them.
    out.add("reading_level_fit", reading_level_fit(body, grade_ordinal, audience="teacher"))

    learner_facing = _learner_facing_text(notes)
    if learner_facing.strip():
        out.add("learner_language_fit", reading_level_fit(learner_facing, grade_ordinal))
    else:
        out.add("learner_language_fit", Score(
            None, "pending_no_learner_text",
            "the guide names nothing said directly to the learner",
        ))

    if raw_source.strip():
        # Containment, not similarity. Symmetric Jaccard asks "how alike are
        # these two texts", and the design section holds five strands, twelve
        # sub-strands, four rubric tables and every page header — so a guide
        # correctly confined to ONE sub-strand is punished for every word of the
        # other eleven it properly left out. It scored 0.20 and the compliance
        # approver rejected the run on it, while the real defect (seven modules
        # under the depth floor) never reached the gate at all.
        #
        # The question worth asking is asymmetric: of what this guide asserts,
        # how much is in the design? That is what grounding means.
        out.add("source_grounding", Score(
            containment(body, raw_source),
            "notes_term_containment_in_design",
            f"fraction of the guide's key terms found in {len(raw_source)} chars "
            f"of curriculum design",
        ))
    else:
        out.add("source_grounding", Score(None, "pending_no_raw_source", "no curriculum source text supplied"))

    # Depth is measured over the teaching body, not the flattened payload. The
    # route mirrors `modules` into `hour_modules` and derives `key_concepts`
    # from it, so flattening counts the same guide twice and change: 4,299 real
    # characters were reported as 3,840 words and scored a full 1.0 for depth on
    # the same run that called all seven modules too thin to teach from.
    from .notes_coverage import MIN_BODY_CHARS, teaching_body

    body_chars = len(teaching_body(notes))
    if module_count:
        target_chars = module_count * MIN_BODY_CHARS
        out.add("content_depth", Score(
            round(min(1.0, body_chars / target_chars), 4),
            "body_chars_vs_module_floor",
            f"{body_chars:,} characters of teaching body against {target_chars:,} "
            f"({module_count} modules x {MIN_BODY_CHARS:,})",
            body_chars,
        ))
    else:
        out.add("content_depth", Score(
            round(min(1.0, word_count / 1200), 4),
            "word_count_vs_target",
            f"{word_count} words against a 1200-word target, no modules to measure",
            word_count,
        ))

    return out


# Fields a guide addresses to the child rather than to the teacher. These are
# the ones that have to land at the learner's own level.
_LEARNER_FACING = ("key_questions", "learning_intent")


def _learner_facing_text(notes: dict[str, Any]) -> str:
    parts: list[str] = []
    accessibility = notes.get("accessibility_support")
    if isinstance(accessibility, dict):
        parts.append(str(accessibility.get("plain_language_summary") or ""))
    modules = notes.get("modules") or notes.get("hour_modules") or []
    if isinstance(modules, list):
        for module in modules:
            if not isinstance(module, dict):
                continue
            for key in _LEARNER_FACING:
                value = module.get(key)
                if isinstance(value, str):
                    parts.append(value)
                elif isinstance(value, list):
                    parts += [str(v) for v in value if isinstance(v, str)]
    return " ".join(p for p in parts if p)


# ─────────────────────────────────────────────────────────────────────────────
# Diagrams
# ─────────────────────────────────────────────────────────────────────────────


def score_diagram(diagram: dict[str, Any], concept: str = "") -> ScoreSet:
    out = ScoreSet()
    svg = str(diagram.get("diagram_svg") or "")
    accessibility = diagram.get("accessibility") or {}
    alt = str(accessibility.get("alt_text") or diagram.get("alt_text") or "")
    tactile = str(accessibility.get("tactile_description") or diagram.get("tactile_description") or "")

    out.add("vector_validity", Score(
        1.0 if "<svg" in svg.lower() and "</svg>" in svg.lower() else 0.0,
        "svg_markup_presence",
        f"{len(svg)} chars of markup",
    ))

    access_parts = [bool(alt.strip()), bool(tactile.strip()), len(alt.split()) >= 8]
    out.add("sne_accessibility", Score(
        round(sum(access_parts) / len(access_parts), 4),
        "alt_and_tactile_presence",
        f"alt text {len(alt.split())} words, tactile description {'present' if tactile.strip() else 'missing'}",
    ))

    labels = re.findall(r">([^<>]{2,})<", svg)
    label_text = " ".join(labels)
    label_count = len([label for label in labels if label.strip()])
    out.add("label_density", Score(
        round(min(1.0, label_count / 6), 4),
        "text_node_count",
        f"{label_count} text labels (6+ expected for an assessable diagram)",
        label_count,
    ))

    scene = diagram.get("scene_document") or {}
    parts = scene.get("parts") if isinstance(scene, dict) else None
    if parts:
        assessable = sum(1 for p in parts if isinstance(p, dict) and p.get("assessable"))
        out.add("part_addressability", Score(
            round(min(1.0, assessable / 4), 4),
            "assessable_parts_in_scene_document",
            f"{assessable} individually addressable parts (4+ enables part-level questions)",
            len(parts),
        ))
    else:
        out.add("part_addressability", Score(
            0.0, "no_scene_document",
            "flat SVG with no addressable parts; cannot support part-level questions",
        ))

    if concept.strip():
        match, method = similarity(f"{diagram.get('diagram_title', '')} {label_text}", concept)
        out.add("concept_alignment", Score(
            match, method, f"diagram title and labels compared against '{concept[:80]}'"
        ))
    else:
        out.add("concept_alignment", Score(None, "pending_no_concept", "no target concept supplied"))

    return out


# ─────────────────────────────────────────────────────────────────────────────
# Activities and experiments
# ─────────────────────────────────────────────────────────────────────────────

_HAZARD_TERMS = frozenset("""
acid alkali corrosive flame burner bunsen heat boiling steam blade knife sharp glass
electricity voltage current chemical toxic poison fumes inhale sterile bacteria fungal
pesticide fertiliser fertilizer machete jembe panga hoe
""".split())

_PPE_TERMS = frozenset("""
goggles gloves apron coat mask supervision supervised ventilation ventilated wash rinse
caution careful safety hazard warning protective adult teacher
""".split())


def score_activity(activity_data: dict[str, Any], content_type: str = "generic") -> ScoreSet:
    out = ScoreSet()
    activities = activity_data.get("activities") or []
    experiments = activity_data.get("experiments") or []
    combined = activities + experiments if isinstance(activities, list) and isinstance(experiments, list) else []
    body = _flatten(activity_data)
    body_tokens = tokens(body)

    out.add("activity_volume", Score(
        round(min(1.0, len(combined) / 4), 4),
        "activity_count_vs_target",
        f"{len(combined)} activities and experiments against a target of 4",
        len(combined),
    ))

    if combined:
        with_procedure = sum(
            1 for a in combined
            if isinstance(a, dict) and (a.get("procedure_steps") or a.get("procedure") or a.get("methodology_steps"))
        )
        with_materials = sum(
            1 for a in combined
            if isinstance(a, dict) and (a.get("materials") or a.get("apparatus_required") or a.get("apparatus"))
        )
        out.add("procedure_completeness", Score(
            round(with_procedure / len(combined), 4),
            "procedure_presence_per_activity",
            f"{with_procedure} of {len(combined)} carry step-by-step procedures",
            len(combined),
        ))
        out.add("materials_specified", Score(
            round(with_materials / len(combined), 4),
            "materials_presence_per_activity",
            f"{with_materials} of {len(combined)} list required materials",
            len(combined),
        ))
    else:
        out.add("procedure_completeness", Score(None, "pending_no_activities", "no activities generated"))
        out.add("materials_specified", Score(None, "pending_no_activities", "no activities generated"))

    hazards_present = body_tokens & _HAZARD_TERMS
    ppe_present = body_tokens & _PPE_TERMS

    if hazards_present:
        # Where a hazard is described, protective guidance must accompany it.
        value = round(min(1.0, len(ppe_present) / max(2, len(hazards_present))), 4)
        out.add("safety_compliance", Score(
            value,
            "ppe_coverage_of_named_hazards",
            f"hazards {sorted(hazards_present)[:5]} against safety terms {sorted(ppe_present)[:5]}",
            len(hazards_present),
        ))
    else:
        out.add("safety_compliance", Score(
            1.0, "no_hazards_named", "no hazardous materials or procedures referenced",
        ))

    out.add("local_materials_emphasis", Score(
        round(min(1.0, len(body_tokens & {
            "local", "locally", "available", "improvise", "improvised", "household",
            "recycled", "community", "school", "kenya", "kenyan", "county",
        }) / 4), 4),
        "local_context_term_presence",
        "locally-sourced materials keep activities feasible in under-resourced schools",
    ))

    return out


# ─────────────────────────────────────────────────────────────────────────────
# Questions
# ─────────────────────────────────────────────────────────────────────────────


def score_question(
    question: dict[str, Any],
    slo_text: str = "",
    notes_body: str = "",
    grade_ordinal: int = 8,
) -> ScoreSet:
    out = ScoreSet()

    stem_parts = [
        str(question.get("question_text") or ""),
        str(question.get("stimulus_context") or ""),
        str((question.get("pedagogy") or {}).get("micro_concept") or question.get("micro_concept") or ""),
    ]
    parts = question.get("structured_parts") or []
    stem_parts += [str(p.get("sub_question") or "") for p in parts if isinstance(p, dict)]
    stem = " ".join(p for p in stem_parts if p)

    if slo_text.strip():
        # Directional on purpose: the question is congruent when it addresses the
        # SLO's concepts. Extra situating context in the stem is good pedagogy,
        # not a mismatch, so a symmetric measure would penalise the wrong thing.
        if _embedding_similarity is not None:
            congruence, method = similarity(stem, slo_text)
        else:
            congruence, method = containment(slo_text, stem), "slo_term_containment_in_stem"
        out.add("slo_congruence", Score(
            congruence, method, f"stem compared against SLO '{slo_text[:80]}'"
        ))
    else:
        out.add("slo_congruence", Score(None, "pending_no_slo_text", "no SLO text on the curriculum link"))

    if notes_body.strip():
        out.add("source_grounding", Score(
            containment(stem, notes_body),
            "stem_term_containment_in_notes",
            "fraction of the question's key terms that appear in the sub-strand notes",
        ))
    else:
        out.add("source_grounding", Score(None, "pending_no_notes", "no notes body supplied"))

    options = question.get("options") or []
    if options and len(options) >= 2:
        texts = [str(o.get("text") or "") for o in options if isinstance(o, dict)]
        lengths = [len(t.split()) for t in texts if t]

        if len(lengths) >= 2:
            mean_len = sum(lengths) / len(lengths)
            spread = max(lengths) - min(lengths)
            # A correct option markedly longer than its distractors is a giveaway.
            length_fairness = round(math.exp(-((spread / max(4.0, mean_len * 1.5)) ** 2)), 4)
        else:
            length_fairness = 0.0

        near_duplicates = 0
        for i in range(len(texts)):
            for j in range(i + 1, len(texts)):
                sim, _ = similarity(texts[i], texts[j])
                if sim > 0.8:
                    near_duplicates += 1
        pair_count = max(1, len(texts) * (len(texts) - 1) // 2)
        distinctness = round(1.0 - (near_duplicates / pair_count), 4)

        with_rationale = sum(
            1 for o in options
            if isinstance(o, dict) and str(o.get("distractor_rationale") or "").strip()
        )

        out.add("distractor_plausibility", Score(
            round((length_fairness + distinctness) / 2, 4),
            "length_fairness_and_distinctness",
            f"option lengths {lengths}, {near_duplicates} near-duplicate pair(s)",
            len(options),
        ))
        out.add("distractor_diagnostics", Score(
            round(with_rationale / len(options), 4),
            "rationale_presence_per_option",
            f"{with_rationale} of {len(options)} options explain why they are wrong",
            len(options),
        ))

        correct = [o for o in options if isinstance(o, dict) and o.get("is_correct")]
        out.add("answer_key_integrity", Score(
            1.0 if len(correct) == 1 else 0.0,
            "exactly_one_correct_option",
            f"{len(correct)} option(s) flagged correct",
            len(options),
        ))
    else:
        out.add("distractor_plausibility", Score(None, "not_applicable", "not a selected-response item"))
        out.add("answer_key_integrity", Score(
            1.0 if str(question.get("model_answer") or "").strip() else 0.0,
            "model_answer_presence",
            "constructed-response items are keyed by their model answer",
        ))

    rubric = question.get("rubric") or question.get("marking_guide") or {}
    if isinstance(rubric, dict):
        levels = [rubric.get(k) for k in ("exceeding", "meeting", "approaching", "below")]
        filled = sum(1 for level in levels if str(level or "").strip())
        out.add("rubric_completeness", Score(
            round(filled / 4, 4),
            "four_level_rubric_presence",
            f"{filled} of 4 criterion-referenced performance levels described",
        ))
    else:
        out.add("rubric_completeness", Score(0.0, "no_rubric", "no rubric attached"))

    out.add("scenario_authenticity", Score(
        round(min(1.0, len(str(question.get("stimulus_context") or "").split()) / 25), 4),
        "stimulus_word_count",
        "a situated scenario needs roughly 25 words to establish real context",
    ))

    out.add("reading_level_fit", reading_level_fit(stem, grade_ordinal))

    # Item discrimination is an empirical statistic computed from how learners of
    # differing ability actually perform. It is unknowable before the item is
    # sat, so it stays pending rather than being asserted.
    out.add("item_discrimination", Score(
        None,
        "pending_field_data",
        "requires learner response data; populate from assessment results",
    ))

    return out


# ─────────────────────────────────────────────────────────────────────────────
# Bundle
# ─────────────────────────────────────────────────────────────────────────────


def score_bundle(stage_score_sets: list[ScoreSet]) -> ScoreSet:
    out = ScoreSet()
    means = [s.mean() for s in stage_score_sets]
    computed = [m for m in means if m is not None]

    if computed:
        out.add("composite_fidelity", Score(
            round(sum(computed) / len(computed), 4),
            "mean_of_stage_means",
            f"averaged across {len(computed)} scored stages",
            len(computed),
        ))
        out.add("weakest_stage", Score(
            round(min(computed), 4),
            "minimum_stage_mean",
            "a bundle is only as publishable as its weakest layer",
            len(computed),
        ))
    else:
        out.add("composite_fidelity", Score(None, "pending_no_scored_stages", "no stage produced a computable score"))

    total_metrics = sum(len(s.scores) for s in stage_score_sets)
    pending = sum(1 for s in stage_score_sets for sc in s.scores.values() if sc.value is None)
    out.add("measurement_coverage", Score(
        round((total_metrics - pending) / total_metrics, 4) if total_metrics else None,
        "computed_metrics_ratio",
        f"{total_metrics - pending} of {total_metrics} metrics computed, {pending} pending",
        total_metrics,
    ))

    return out
