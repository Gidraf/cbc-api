"""Level and difficulty worked out from the item, not taken from the writer.
qwen3:14b filed all seventeen of its first items at 0.65, and half a level
too high."""
from __future__ import annotations

from app.services import item_difficulty as d


def _mcq(stem, **extra):
    return {"question_type": "multiple_choice", "question_text": stem,
            "options": [{"id": "A", "text": "x"}, {"id": "B", "text": "y"}], **extra}


def test_a_recognition_item_is_recall_however_it_was_labelled():
    m = d.measure(_mcq("Which of the following is a formal greeting used in the evening?"))
    assert m.bloom == "Recall" and m.difficulty <= 0.25


def test_the_command_word_sets_the_level():
    assert d.measure(_mcq("Explain the role of the nucleus.")).bloom == "Understanding"
    assert d.measure(_mcq("Explain why the nucleus is dense.")).bloom == "Analysis", "the ladder ranks explain-why as analysis"
    assert d.measure({"question_type": "structured_scenario",
                      "question_text": "Compare the two isotopes and justify which is heavier."}).bloom == "Evaluation"


def test_a_calculation_is_at_least_application_even_without_a_verb():
    stem = "An atom has 14 protons and 16 neutrons. What is its mass number?"
    plain = d.measure(_mcq(stem))
    worked = d.measure(_mcq(stem, worked_solution=[{"step": "Mass number = protons + neutrons", "why": "definition"},
                                                   {"step": "14 + 16 = 30", "why": "add"}]))
    assert plain.bloom == "Recall" and worked.bloom == "Application"


def test_difficulty_rises_with_what_the_item_makes_a_learner_do():
    simple = d.measure({"question_type": "structured_scenario", "question_text": "Describe an atom.",
                        "max_marks": 2})
    harder = d.measure({"question_type": "structured_scenario", "question_text": "Describe an atom.",
                        "max_marks": 6, "figure": {"kind": "atom", "protons": 16, "neutrons": 16},
                        "structured_parts": [{"sub_question": "a"}, {"sub_question": "b"}, {"sub_question": "c"}],
                        "worked_solution": [{"step": s} for s in "abcde"]})
    assert simple.bloom == harder.bloom == "Understanding"
    assert harder.difficulty > simple.difficulty + 0.2
    assert harder.basis["figure"] and harder.basis["parts"] == 3 and harder.basis["walk_through_steps"] == 5


def test_the_normaliser_measures_and_keeps_the_writers_claim():
    from app.services.question_normalizer import question_normalizer

    batch = question_normalizer.normalize_batch(
        [{"question_id": "Q1", "question_type": "multiple_choice",
          "question_text": "Which of the following is a formal greeting used in the evening?",
          "options": [{"id": "A", "text": "早上好"}, {"id": "B", "text": "晚上好", "is_correct": True}],
          "correct_answer": "B", "bloom_level": "Application", "difficulty_index": 0.65, "max_marks": 1}],
        grade="grade-9", subject="Mandarin", strand="Listening", sub_strand="Greetings")
    p = batch.items[0].pedagogy
    assert p.bloom_level == "Recall" and p.difficulty_index <= 0.25
    assert p.bloom_claimed == "Application" and p.difficulty_claimed == 0.65
    assert "no command word" in p.difficulty_basis["level"]
