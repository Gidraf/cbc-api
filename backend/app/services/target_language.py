"""When the learning area IS a language, the words must be in that language.

A Grade 6 Arabic lesson came back with the teacher saying:

    "The first phrase is 'My name is...'. Now, say it with me: 'My name is...'"

The learners repeat "My name is" — in English — and learn no Arabic. The script
was written ABOUT the language instead of IN it, and every check passed: the
material was substantial, on topic, at the right register, grounded in the
design. It was simply not the lesson.

So a language area needs three things in every spoken line the learner repeats:
the phrase in its own script, a transliteration they can read aloud, and the
meaning. Two of the three is not enough — the script alone cannot be sounded
out by a teacher who does not read it, and the transliteration alone teaches a
spelling that does not exist.

Kenya Sign Language is the exception that proves it: there is no script to
write, and a lesson that "writes out the sign" is describing a photograph. It
is called out separately rather than squeezed into the same rule.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(slots=True)
class TargetLanguage:
    name: str
    script: str            # what the writing system is called
    pattern: str           # how to recognise it, "" when it is Latin
    example: str           # one phrase, in the shape a script should carry it


# The learning areas that ARE a language. Kiswahili and the indigenous
# languages are here too: they are taught in themselves, and a Kiswahili lesson
# scripted in English has the same defect as an Arabic one.
LANGUAGES: dict[str, TargetLanguage] = {
    "arabic": TargetLanguage(
        "Arabic", "the Arabic alphabet", r"[؀-ۿ]",
        "أَنَا اِسْمِي... (Ana ismee...) — My name is...",
    ),
    "mandarin": TargetLanguage(
        "Mandarin", "Chinese characters", r"[一-鿿]",
        "我叫… (Wǒ jiào…) — My name is…",
    ),
    "french": TargetLanguage(
        "French", "the Latin alphabet", "",
        "Je m'appelle… (zhuh mah-PELL) — My name is…",
    ),
    "german": TargetLanguage(
        "German", "the Latin alphabet", "",
        "Ich heiße… (ikh HYE-suh) — My name is…",
    ),
    "kiswahili": TargetLanguage(
        "Kiswahili", "the Latin alphabet", "",
        "Jina langu ni… — My name is…",
    ),
    "indigenous language": TargetLanguage(
        "the indigenous language of the catchment area", "the Latin alphabet", "",
        "the greeting as it is said locally, then its meaning",
    ),
    "kenya sign language": TargetLanguage(
        "Kenya Sign Language", "no written script — it is signed", "",
        "the handshape, where it is made, and how it moves",
    ),
}

_ALIASES = {
    "arabic language": "arabic", "french language": "french",
    "german language": "german", "mandarin chinese": "mandarin",
    "chinese": "mandarin", "ksl": "kenya sign language",
    "kenyan sign language": "kenya sign language",
    "indigenous languages": "indigenous language",
}


def for_subject(subject: str) -> TargetLanguage | None:
    """The language this learning area teaches, or None if it teaches a subject."""
    key = re.sub(r"\s+", " ", str(subject or "")).strip().lower()
    key = _ALIASES.get(key, key)
    if key in LANGUAGES:
        return LANGUAGES[key]
    # "Arabic Language", "Grade 6 French" — the name with something around it.
    for name, language in LANGUAGES.items():
        if re.search(rf"\b{re.escape(name)}\b", key):
            return language
    return None


def block_for(subject: str) -> str:
    """The instruction to put in a prompt, or "" for a non-language area."""
    language = for_subject(subject)
    if language is None:
        return ""

    if not language.pattern and "signed" in language.script:
        return (
            "=== THIS LEARNING AREA IS A LANGUAGE, AND IT IS SIGNED ===\n"
            f"{language.name} has no written script. Do not 'write out' a sign.\n"
            "Every sign the learner produces is described so a teacher can make "
            "it: the handshape, where on the body it is made, how it moves, and "
            "the facial expression that carries the grammar. Then its meaning.\n"
            f"Shape: {language.example}\n"
        )

    return "\n".join([
        "=== THIS LEARNING AREA IS A LANGUAGE. SCRIPT IT IN THAT LANGUAGE ===",
        f"The learners are learning {language.name}. Every word they are asked to "
        f"say, repeat, read or write must appear in the script IN {language.name.upper()} "
        f"— not described, not named, not translated and left at that.",
        "",
        "The failure this exists to stop: a teacher's script that reads \"The "
        "first phrase is 'My name is'. Now say it with me: 'My name is'\". The "
        "learners repeat English and learn nothing. It reads as a complete "
        "lesson and is not the lesson.",
        "",
        f"So every phrase the learner says carries three things, in this order:",
        f"  1. the phrase written in {language.script},",
        "  2. a transliteration a teacher who does not read that script can "
        "sound out,",
        "  3. what it means.",
        f"Like this: {language.example}",
        "",
        "Two of the three is not enough. The script alone cannot be read aloud "
        "by every teacher; the transliteration alone teaches a spelling that "
        "does not exist.",
        "",
        "English is for the INSTRUCTIONS around the language — 'now turn to your "
        f"partner', 'listen for the long vowel'. The moment a learner speaks, it "
        f"is {language.name}.",
    ])


def scripted(text: str, subject: str) -> bool:
    """Whether this text carries the target script at all.

    Only decidable where the script is not Latin. A French lesson written
    entirely in English looks, to a pattern, exactly like a French lesson.
    """
    language = for_subject(subject)
    if language is None or not language.pattern:
        return True
    return bool(re.search(language.pattern, str(text or "")))
