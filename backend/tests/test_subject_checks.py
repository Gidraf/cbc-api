"""The checks a subject's own examiner makes, for the subjects the engine cannot read."""
from __future__ import annotations

from app.services import question_check, subject_checks


def _mcq(label, stem, options, key, *, qtype="multiple_choice", stimulus="", **extra):
    return {"question_id": f"q-{label.lower()}", "display_label": label, "question_type": qtype,
            "question_text": stem, "stimulus_context": stimulus,
            "options": [{"id": k, "text": v, "is_correct": k == key} for k, v in options.items()],
            "correct_answer": key, "pedagogy": {"max_marks": 1, "bloom_level": "Application"},
            "curriculum": {}, **extra}


def _written(label, stem, answer, scheme="", *, qtype="short_answer", stimulus=""):
    return {"question_id": f"q-{label.lower()}", "display_label": label, "question_type": qtype,
            "question_text": stem, "stimulus_context": stimulus, "model_answer": answer,
            "marking_scheme": scheme, "pedagogy": {"max_marks": 2, "bloom_level": "Application"},
            "curriculum": {}}


def _kinds(findings):
    return {f.kind: f for f in findings}


# ── sciences ────────────────────────────────────────────────────────────────

def test_a_science_answer_in_units_carries_a_unit_of_the_question() -> None:
    batch = [
        _written("Q1", "A car travels 120 km in 2 h. Find its speed.", "60 km/h"),
        _written("Q2", "A stone of mass 50 g has a volume of 20 cm3. Find its density.", "2.5"),
        _written("Q3", "A block is 4 cm long and 2 cm wide. Find its area.", "8 kg"),
    ]
    kinds = _kinds(subject_checks.check(batch, subject="Integrated Science", grade="grade-8"))

    assert "answer_without_unit" in kinds and kinds["answer_without_unit"].items == ["q-q2"]
    assert "answer_unit_not_in_question" in kinds and kinds["answer_unit_not_in_question"].items == ["q-q3"]


def test_units_written_as_words_or_wrong_case_are_named() -> None:
    batch = [_written("Q1", "A lorry carries 3 Kg of maize 12 KM to market. How far in metres?", "12000 m")]
    kinds = _kinds(subject_checks.check(batch, subject="Science and Technology", grade="grade-6"))

    assert "unit_symbol" in kinds
    assert "Kg → kg" in kinds["unit_symbol"].says and "KM → km" in kinds["unit_symbol"].says


def test_a_chemical_equation_given_as_an_answer_must_balance() -> None:
    assert subject_checks.balanced("2H2 + O2 -> 2H2O") is True
    assert subject_checks.balanced("H2 + O2 -> H2O") is False
    assert subject_checks.balanced("Ca(OH)2 + 2HCl -> CaCl2 + 2H2O") is True
    assert subject_checks.balanced("CaCO3 -> CaO + CO2 (g)") is True
    assert subject_checks.balanced("the reaction gives water") is None

    batch = [_written("Q1", "Write a balanced equation for hydrogen burning in oxygen.",
                      "H2 + O2 -> H2O", "H2 + O2 -> H2O (2 marks)")]
    kinds = _kinds(subject_checks.check(batch, subject="Integrated Science", grade="grade-9"))

    assert "equation_not_balanced" in kinds and kinds["equation_not_balanced"].items == ["q-q1"]


def test_a_stem_that_asks_the_learner_to_balance_is_not_the_answer() -> None:
    batch = [_written("Q1", "Balance the equation H2 + O2 -> H2O.", "2H2 + O2 -> 2H2O")]
    assert not subject_checks.check(batch, subject="Integrated Science", grade="grade-9")


# ── languages ───────────────────────────────────────────────────────────────

PASSAGE = ("Amina woke up early on Saturday. She helped her mother to fetch water from the river "
           "before the sun was hot. On the way back she saw a lorry stuck in the mud near the bridge. "
           "The driver was shouting for help, so Amina ran to call the men who were building the "
           "new classroom. Together they pushed the lorry out of the mud. The driver thanked them "
           "and gave Amina a ride home. Her mother was surprised to see her arrive in a lorry, and "
           "she laughed when Amina told her the whole story over breakfast.")


def test_an_item_about_a_passage_needs_the_passage() -> None:
    batch = [
        _mcq("Q1", "According to the passage, why did Amina run?", {"A": "x", "B": "y", "C": "z", "D": "w"}, "A"),
        _mcq("Q2", "According to the passage, why did Amina run?", {"A": "x", "B": "y", "C": "z", "D": "w"}, "A",
             stimulus=PASSAGE),
    ]
    kinds = {f.kind: f for f in subject_checks.check(batch, subject="English", grade="grade-5")}

    assert kinds["passage_missing"].items == ["q-q1"]


def test_a_quoted_word_must_be_in_the_passage() -> None:
    batch = [
        _mcq("Q1", "The word 'stuck' as used in the passage means", {"A": "x", "B": "y", "C": "z", "D": "w"}, "A",
             stimulus=PASSAGE),
        _mcq("Q2", "The word 'furious' as used in the passage means", {"A": "x", "B": "y", "C": "z", "D": "w"}, "A",
             stimulus=PASSAGE),
    ]
    kinds = {f.kind: f for f in subject_checks.check(batch, subject="English", grade="grade-5")}

    assert kinds["word_not_in_passage"].items == ["q-q2"]


def test_a_passage_is_as_long_as_the_grade_reads() -> None:
    long_passage = " ".join([PASSAGE] * 5)
    batch = [_mcq("Q1", "According to the passage, who helped?", {"A": "x", "B": "y", "C": "z", "D": "w"}, "A",
                  stimulus=long_passage)]
    kinds = {f.kind: f for f in subject_checks.check(batch, subject="English", grade="grade-3")}

    assert "passage_length" in kinds and "30–140" in kinds["passage_length"].says
    # The same passage, four times over, is a Grade 9 length.
    batch[0]["stimulus_context"] = " ".join([PASSAGE] * 4)
    assert not any(f.kind == "passage_length"
                   for f in subject_checks.check(batch, subject="English", grade="grade-9"))


def test_a_kiswahili_paper_is_in_kiswahili() -> None:
    batch = [
        _mcq("Q1", "Neno 'kifaru' ni la ngeli gani katika sentensi hii?",
             {"A": "A-WA", "B": "KI-VI", "C": "LI-YA", "D": "U-I"}, "A"),
        _mcq("Q2", "Which of the following is the plural of the word mtoto?",
             {"A": "watoto", "B": "vitoto", "C": "matoto", "D": "mitoto"}, "A"),
    ]
    kinds = {f.kind: f for f in subject_checks.check(batch, subject="Kiswahili", grade="grade-6")}

    assert kinds["wrong_language"].items == ["q-q2"]
    assert not subject_checks.check(batch[:1], subject="Kiswahili", grade="grade-6")


def test_an_english_paper_is_in_english() -> None:
    batch = [_mcq("Q1", "Chagua jibu sahihi ili kukamilisha sentensi hii na neno lililo bora.",
                  {"A": "na", "B": "ya", "C": "wa", "D": "kwa"}, "A")]
    assert any(f.kind == "wrong_language" for f in subject_checks.check(batch, subject="English", grade="grade-6"))


def test_a_cloze_item_has_one_gap() -> None:
    batch = [
        _mcq("Q1", "The cat sat ______ the mat.", {"A": "on", "B": "at", "C": "in", "D": "by"}, "A"),
        _mcq("Q2", "The cat ______ on the ______.", {"A": "sat", "B": "sit", "C": "sits", "D": "sat mat"}, "A"),
    ]
    kinds = {f.kind: f for f in subject_checks.check(batch, subject="English", grade="grade-4")}

    assert kinds["cloze_gaps"].items == ["q-q2"]


# ── social studies ──────────────────────────────────────────────────────────

def test_a_year_that_has_not_happened_is_named() -> None:
    batch = [_mcq("Q1", "Kenya became independent in which year?", {"A": "1963", "B": "1964", "C": "2063", "D": "1952"}, "A"),
             _mcq("Q2", "In 2091 Kenya joined the East African Community. True or false?", {"A": "True", "B": "False"}, "B",
                  qtype="true_false")]
    kinds = {f.kind: f for f in subject_checks.check(batch, subject="Social Studies", grade="grade-7")}

    assert kinds["impossible_year"].items == ["q-q2"], "a distractor year may be wrong; a stem's may not"


# ── wiring ──────────────────────────────────────────────────────────────────

def test_the_subject_checks_run_inside_the_question_check() -> None:
    batch = [_written("Q1", "A car travels 120 km in 2 h. Find its speed.", "60")]
    report = question_check.check(batch, grade="grade-8", subject="Integrated Science",
                                  strand="Force and Energy", sub_strand="Speed")

    assert any(f.kind == "answer_without_unit" for f in report.findings)


def test_learning_areas_are_named_as_kicd_names_them() -> None:
    from app.services import assessment_format as af
    from app.services.curriculum_catalogue import EXPECTED_SUBJECTS

    assert "Integrated Science" in EXPECTED_SUBJECTS["grade-8"]
    assert "Science and Technology" in EXPECTED_SUBJECTS["grade-6"]
    assert "Pre-Technical Studies" in EXPECTED_SUBJECTS["grade-9"]
    assert af.masthead("grade-7", "CRE")["subject"] == "CHRISTIAN RELIGIOUS EDUCATION"
    assert af.masthead("grade-7", "Integrated Science")["subject"] == "INTEGRATED SCIENCE"
    assert subject_checks.family_of("Integrated Science") == "science"
    assert subject_checks.family_of("Science and Technology") == "science"
    assert subject_checks.family_of("Kiswahili") == "language"
    assert subject_checks.family_of("English Activities") == "language"
    assert subject_checks.family_of("Social Studies") == "social"
    assert subject_checks.family_of("Mathematics") == "mathematics"
