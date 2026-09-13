"""Checks a subject's own examiner makes, for the subjects the engine cannot read.

The maths engine solves arithmetic and nothing else, so for Mathematics an
item's key is proved or disproved; for every other learning area the only
correctness check was a second model reading the first. A science examiner
and a language examiner have mechanical checks of their own, and these are
them — the things that fail an item on sight in a moderation room:

SCIENCES (Integrated Science, Science and Technology, Environmental
Activities, the senior sciences)
  - a numerical answer to a question set in units carries a unit, and one
    of the question's own units or a unit made from them (m and s → m/s);
  - SI symbols are written as symbols: kg not Kg, km not KM, s not sec;
  - a chemical equation given as an ANSWER balances — every element counts
    the same on both sides.

LANGUAGES (English, Kiswahili, English Activities, Literacy)
  - an item "according to the passage" has a passage — at the length the
    grade reads, in sentences of the length the grade reads;
  - "the word 'X' as used in the passage" — X is in the passage;
  - a Kiswahili paper is in Kiswahili and an English paper in English,
    item by item;
  - a cloze item has exactly one gap to fill.

SOCIAL STUDIES
  - a year in a stem, key or scheme is a year that can have happened.

Each finding names its item, in the form the rewrite loop already acts on.
Nothing here judges pedagogy; it judges what can be counted.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any

from .grade_order import grade_ordinal

logger = logging.getLogger("cbc-subject-checks")

# ── which family a learning area belongs to ────────────────────────────────

_SCIENCE = re.compile(r"science|biology|chemistry|physics|environmental|agricultur|home science|health", re.I)
_LANGUAGE = re.compile(r"english|kiswahili|literacy|language|swahili|french|german|arabic|mandarin|sign language|indigenous", re.I)
_KISWAHILI = re.compile(r"kiswahili|swahili", re.I)
_SOCIAL = re.compile(r"social|history|geograph|government|civics", re.I)
_MATHS = re.compile(r"math", re.I)


def family_of(subject: str) -> str:
    text = subject or ""
    if _MATHS.search(text):
        return "mathematics"
    if _SCIENCE.search(text):
        return "science"
    if _LANGUAGE.search(text):
        return "language"
    if _SOCIAL.search(text):
        return "social"
    return "other"


# ── reading an item ────────────────────────────────────────────────────────

def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _id(question: dict[str, Any]) -> str:
    return str(question.get("question_id") or question.get("display_label") or "")


def _label(question: dict[str, Any], index: int) -> str:
    return str(question.get("display_label") or f"Q{index}")


def _stem(question: dict[str, Any]) -> str:
    return " ".join(p for p in (_text(question.get("stimulus_context")),
                                _text(question.get("question_text"))) if p)


def _answers(question: dict[str, Any]) -> list[str]:
    """Every answer text an item commits to: the key, the model answer, the
    parts' model answers."""
    out: list[str] = []
    for option in question.get("options") or []:
        if isinstance(option, dict) and option.get("is_correct"):
            out.append(_text(option.get("text")))
    if _text(question.get("model_answer")):
        out.append(_text(question.get("model_answer")))
    for part in question.get("structured_parts") or []:
        if isinstance(part, dict) and _text(part.get("model_answer")):
            out.append(_text(part.get("model_answer")))
    return out


# ── sciences ───────────────────────────────────────────────────────────────

# Units as they appear in a Kenyan science paper. Keyed by the symbol as it
# should be written; the alternatives are what is written instead.
_UNITS: dict[str, tuple[str, ...]] = {
    "km": ("KM", "Km", "kms", "kilometres", "kilometers"),
    "m": ("metres", "meters", "mtrs"),
    "cm": ("CM", "cms", "centimetres", "centimeters"),
    "mm": ("MM", "millimetres", "millimeters"),
    "kg": ("Kg", "KG", "kgs", "kilograms", "kilogrammes"),
    "g": ("gm", "gms", "grams", "grammes"),
    "mg": ("Mg", "milligrams"),
    "l": ("L", "ltr", "ltrs", "litres", "liters"),
    "ml": ("mL", "ML", "mls", "millilitres", "milliliters"),
    "s": ("sec", "secs", "seconds"),
    "min": ("mins", "minutes"),
    "h": ("hr", "hrs", "hours"),
    "N": ("newtons", "newton"),
    "J": ("joules", "joule"),
    "W": ("watts", "watt"),
    "V": ("volts", "volt"),
    "A": ("amperes", "amps", "amp"),
    "Ω": ("ohms", "ohm"),
    "Pa": ("pascals", "pascal"),
    "°C": ("degrees celsius", "degrees centigrade", "oC", "deg C"),
    "m/s": ("m/sec", "ms-1", "metres per second", "meters per second"),
    "km/h": ("kph", "km/hr", "kmph", "kilometres per hour"),
    "g/cm³": ("g/cm3", "gcm-3", "g per cm3"),
    "kg/m³": ("kg/m3", "kgm-3"),
    "Hz": ("hertz",),
}
_WRONG_SYMBOL: dict[str, str] = {}
for _right, _wrongs in _UNITS.items():
    for _w in _wrongs:
        if _w != _right and re.fullmatch(r"[A-Za-z°/³\-0-9]+", _w) and len(_w) <= 5:
            _WRONG_SYMBOL[_w] = _right

_UNIT_WORDS = {u.lower() for u in _UNITS} | {alt.lower() for alts in _UNITS.values() for alt in alts}
_NUMBER_UNIT = re.compile(
    r"(?<![A-Za-z])(-?\d+(?:[.,]\d+)?)\s*(°C|km/h|m/s|g/cm³|kg/m³|g/cm3|kg/m3|[A-Za-zΩ°]{1,4}(?:/[A-Za-z]{1,3})?)\b")
_BARE_NUMBER = re.compile(r"^\$?\s*-?\d+(?:[.,]\d+)?\s*\$?$")


def _units_in(text: str) -> set[str]:
    found: set[str] = set()
    for _, unit in _NUMBER_UNIT.findall(text):
        key = unit.strip()
        if key.lower() in _UNIT_WORDS or key in _WRONG_SYMBOL:
            found.add(_WRONG_SYMBOL.get(key, key))
    return found


def _derived_ok(answer_unit: str, stem_units: set[str]) -> bool:
    """A unit made from the question's units: m and s give m/s."""
    if answer_unit in stem_units:
        return True
    if "/" in answer_unit:
        top, bottom = answer_unit.split("/", 1)
        base = {"h": "h", "hr": "h", "s": "s", "cm³": "cm", "cm3": "cm", "m³": "m", "m3": "m"}
        return top in stem_units and base.get(bottom, bottom) in stem_units
    return False


def _science_units(questions: list[dict[str, Any]], findings: list) -> None:
    from .question_check import Finding

    for index, question in enumerate(questions, start=1):
        stem = _stem(question)
        stem_units = _units_in(stem)
        for answer in _answers(question):
            if not stem_units:
                break
            if _BARE_NUMBER.match(answer):
                findings.append(Finding(
                    "answer_without_unit",
                    f"{_label(question, index)} is set in {', '.join(sorted(stem_units))} and its answer "
                    f"\"{answer}\" carries no unit. A marker cannot award it.",
                    "Write the unit on the answer, and in the marking scheme.",
                    [_id(question)]))
                break
            answer_units = _units_in(answer)
            odd = [u for u in answer_units if not _derived_ok(u, stem_units)]
            if odd:
                findings.append(Finding(
                    "answer_unit_not_in_question",
                    f"{_label(question, index)} is set in {', '.join(sorted(stem_units))} and answers in "
                    f"{', '.join(sorted(odd))}.",
                    "Answer in the question's units, or state the conversion in the scheme.",
                    [_id(question)]))
                break


_SYMBOL_IN_TEXT = re.compile(r"(?<=\d)\s*(Kg|KG|kgs|KM|Km|kms|CM|cms|MM|sec|secs|hrs|hr|mins|gms|gm|ltrs|ltr|mL|ML|mls|kph|km/hr|kmph)\b")


def _science_symbols(questions: list[dict[str, Any]], findings: list) -> None:
    from .question_check import Finding

    for index, question in enumerate(questions, start=1):
        text = " ".join([_stem(question), *_answers(question), _text(question.get("marking_scheme"))])
        wrong = sorted({m for m in _SYMBOL_IN_TEXT.findall(text)})
        if wrong:
            fixes = ", ".join(f"{w} → {_WRONG_SYMBOL.get(w, w)}" for w in wrong[:4])
            findings.append(Finding(
                "unit_symbol",
                f"{_label(question, index)} writes a unit the way it is spoken, not as its symbol: {fixes}.",
                "SI symbols: kg, km, cm, mm, s, min, h, g, l, ml, km/h.",
                [_id(question)]))


# A chemical formula: element symbols with counts, brackets, a coefficient.
_ELEMENT = re.compile(r"([A-Z][a-z]?)(\d*)")
_FORMULA_TOKEN = re.compile(r"^\s*(\d*)\s*((?:[A-Z][a-z]?\d*|\((?:[A-Z][a-z]?\d*)+\)\d*)+)\s*(?:\((?:s|l|g|aq)\))?\s*$")
_ARROW = re.compile(r"\s*(?:->|→|⟶|=>|—>|-->)\s*")
_KNOWN = set("H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr "
             "Rb Sr Y Zr Nb Mo Ag Cd Sn Sb Te I Xe Cs Ba W Pt Au Hg Pb Bi U".split())


def _atoms(formula: str) -> Counter | None:
    """Element counts in one formula, or None if it is not a formula."""
    match = _FORMULA_TOKEN.match(formula)
    if not match:
        return None
    coefficient = int(match.group(1) or 1)
    body = match.group(2)
    counts: Counter = Counter()

    def read(chunk: str, mult: int) -> bool:
        pos = 0
        while pos < len(chunk):
            if chunk[pos] == "(":
                close = chunk.index(")", pos)
                inner = chunk[pos + 1:close]
                after = re.match(r"\d*", chunk[close + 1:]).group(0)
                if not read(inner, mult * int(after or 1)):
                    return False
                pos = close + 1 + len(after)
                continue
            m = _ELEMENT.match(chunk, pos)
            if not m or m.group(1) not in _KNOWN:
                return False
            counts[m.group(1)] += mult * int(m.group(2) or 1)
            pos = m.end()
        return True

    if not read(body, coefficient) or not counts:
        return None
    return counts


def balanced(equation: str) -> bool | None:
    """True/False for a chemical equation, None where it is not one."""
    sides = _ARROW.split(equation.strip(), maxsplit=1)
    if len(sides) != 2:
        return None
    totals = []
    for side in sides:
        total: Counter = Counter()
        for term in re.split(r"\s*\+\s*", side.strip()):
            atoms = _atoms(term)
            if atoms is None:
                return None
            total.update(atoms)
        totals.append(total)
    return totals[0] == totals[1]


_EQUATION_LINE = re.compile(r"[A-Za-z0-9()\s+]{2,60}?(?:->|→|⟶|=>|-->)[A-Za-z0-9()\s+]{2,60}")


def _science_equations(questions: list[dict[str, Any]], findings: list) -> None:
    from .question_check import Finding

    for index, question in enumerate(questions, start=1):
        for answer in [*_answers(question), _text(question.get("marking_scheme"))]:
            for candidate in _EQUATION_LINE.findall(answer):
                verdict = balanced(candidate)
                if verdict is False:
                    findings.append(Finding(
                        "equation_not_balanced",
                        f"{_label(question, index)} gives the equation \"{candidate.strip()}\" as an "
                        f"answer, and it does not balance.",
                        "Balance it; count every element on both sides.",
                        [_id(question)]))
                    break


# ── languages ──────────────────────────────────────────────────────────────

_REFERS_TO_PASSAGE = re.compile(
    r"\b(the|this) (passage|poem|story|text|extract|dialogue|conversation|letter|advertisement|notice|poster)\b"
    r"|\baccording to the (passage|writer|author|poem|text)\b"
    r"|\b(kifungu|shairi|habari|mazungumzo|makala|taarifa|barua|tangazo|hadithi)\b", re.I)
_QUOTED_WORD = re.compile(r"(?:the (?:word|phrase|expression)|neno|kifungu cha maneno|msemo)\s+['\"‘“]([^'\"’”]{2,40})['\"’”]", re.I)
_GAP = re.compile(r"_{3,}|…{1,}|\.{4,}|\bBLANK\b")

# Words that mark a language, common enough to appear in any three lines of it.
_EN = {"the", "and", "is", "of", "to", "which", "what", "in", "a", "are", "was", "that", "with", "for", "not"}
_SW = {"na", "ya", "wa", "ni", "kwa", "katika", "ambayo", "gani", "ipi", "hii", "huu", "kuwa", "yake", "lake",
       "za", "la", "cha", "vya", "kutoka", "au", "ili", "kama", "hapa", "yote", "mimi", "wewe", "yeye", "sisi"}

# How long a passage is at each band, in words, and how long its sentences run.
_PASSAGE_WORDS = {"lower": (30, 140), "upper": (100, 320), "junior": (180, 480), "senior": (250, 700)}
_SENTENCE_WORDS = {"lower": 12, "upper": 18, "junior": 24, "senior": 30}


def _band(grade: str) -> str:
    ordinal = grade_ordinal(grade)
    return "lower" if ordinal <= 5 else "upper" if ordinal <= 8 else "junior" if ordinal <= 11 else "senior"


def _language_of(text: str) -> str:
    words = re.findall(r"[a-zA-Z']+", text.lower())
    if len(words) < 6:
        return ""
    en = sum(1 for w in words if w in _EN)
    sw = sum(1 for w in words if w in _SW)
    if en >= 2 and en > sw * 2:
        return "en"
    if sw >= 2 and sw > en * 2:
        return "sw"
    return ""


def _language_items(questions: list[dict[str, Any]], subject: str, grade: str, findings: list) -> None:
    from .question_check import Finding

    band = _band(grade)
    wanted = "sw" if _KISWAHILI.search(subject or "") else "en" if re.search(r"english|literacy", subject or "", re.I) else ""
    low, high = _PASSAGE_WORDS[band]
    seen_passages: set[str] = set()

    for index, question in enumerate(questions, start=1):
        label, qid = _label(question, index), _id(question)
        stem_only = _text(question.get("question_text"))
        passage = _text(question.get("stimulus_context"))
        stem_words = len(re.findall(r"\w+", passage))

        # 1. Refers to a passage it does not carry.
        if _REFERS_TO_PASSAGE.search(stem_only) and stem_words < 30 and not question.get("diagram"):
            findings.append(Finding(
                "passage_missing",
                f"{label} asks about a passage and carries none ({stem_words} words of context).",
                "Put the passage in `stimulus_context`, in full, and set the items on it.",
                [qid]))
            continue

        # 2. A quoted word that is not in the passage.
        if passage:
            for quoted in _QUOTED_WORD.findall(stem_only):
                if quoted.lower() not in passage.lower():
                    findings.append(Finding(
                        "word_not_in_passage",
                        f"{label} asks about the word \"{quoted}\" as used in the passage, and the "
                        f"passage does not contain it.",
                        "Quote a word that is in the passage.",
                        [qid]))
                    break

        # 3. The passage's length and its sentences, once per passage.
        if passage and stem_words >= 30 and passage not in seen_passages:
            seen_passages.add(passage)
            if not (low <= stem_words <= high):
                findings.append(Finding(
                    "passage_length",
                    f"{label}'s passage is {stem_words} words; a passage at this grade runs "
                    f"{low}–{high}.",
                    "Cut it, or extend it, to the length the grade reads.",
                    [qid]))
            sentences = [s for s in re.split(r"[.!?]+\s", passage) if len(s.split()) > 2]
            if sentences:
                average = sum(len(s.split()) for s in sentences) / len(sentences)
                if average > _SENTENCE_WORDS[band] * 1.4:
                    findings.append(Finding(
                        "sentences_too_long",
                        f"{label}'s passage averages {average:.0f} words a sentence; this grade reads "
                        f"sentences of about {_SENTENCE_WORDS[band]}.",
                        "Shorten the sentences.",
                        [qid]))

        # 4. The language of the item.
        if wanted:
            text = " ".join([stem_only, *(_text(o.get("text")) for o in (question.get("options") or [])
                                         if isinstance(o, dict))])
            found = _language_of(text)
            if found and found != wanted:
                findings.append(Finding(
                    "wrong_language",
                    f"{label} is written in {'English' if found == 'en' else 'Kiswahili'} on a "
                    f"{'Kiswahili' if wanted == 'sw' else 'English'} paper.",
                    "Write the item, its options and its scheme in the paper's language.",
                    [qid]))

        # 5. A cloze item with the wrong number of gaps.
        gaps = len(_GAP.findall(stem_only))
        if (str(question.get("question_type") or "") == "cloze" or gaps) and gaps != 1 \
                and not question.get("structured_parts"):
            findings.append(Finding(
                "cloze_gaps",
                f"{label} has {gaps} gap(s) to fill and one answer.",
                "One gap per item, or letter the gaps and answer each.",
                [qid]))


# ── social studies ─────────────────────────────────────────────────────────

_YEAR = re.compile(r"\b(1[0-9]{3}|20[0-9]{2}|2[1-9][0-9]{2})\b")


def _social_years(questions: list[dict[str, Any]], findings: list) -> None:
    import datetime as _dt

    from .question_check import Finding

    this_year = _dt.date.today().year
    for index, question in enumerate(questions, start=1):
        text = " ".join([_stem(question), *_answers(question)])
        odd = sorted({y for y in _YEAR.findall(text) if int(y) > this_year + 1})
        if odd:
            findings.append(Finding(
                "impossible_year",
                f"{_label(question, index)} names the year {', '.join(odd)}, which has not happened.",
                "Check the date against the design and the notes.",
                [_id(question)]))


# ── entry ──────────────────────────────────────────────────────────────────

def check(questions: list[dict[str, Any]], *, subject: str, grade: str = "") -> list[Any]:
    """The subject's own checks over a batch. Never raises."""
    items = [q for q in (questions or []) if isinstance(q, dict)]
    findings: list[Any] = []
    if not items:
        return findings
    family = family_of(subject)
    try:
        if family == "science":
            _science_units(items, findings)
            _science_symbols(items, findings)
            _science_equations(items, findings)
        elif family == "language":
            _language_items(items, subject, grade, findings)
        elif family == "social":
            _social_years(items, findings)
        elif family == "mathematics":
            _science_symbols(items, findings)      # km/h written kph is wrong here too
    except Exception as exc:  # noqa: BLE001
        logger.warning("Subject checks for %s failed: %s", subject, exc)
    return findings
