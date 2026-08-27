"""Keep each religious education area inside its own faith.

KICD publishes Christian, Hindu and Islamic Religious Education as separate
learning areas inside one Pre-Primary document. Ingested together they shared a
subject, and a generator asked about one was handed the strands of another — so
a Language Activities request came back with "4.0 CHRISTIAN VALUES", and an
Islamic sub-strand sat beside "1.0 Creation" and "6.0 Yoga" in the same prompt.

For most learning areas that is a correctness bug. Here it is also a matter of
respect: a child sitting an IRE paper must not be asked about the Bible, and a
CRE paper must not cite the Qur'an. The designs share a framework — the same
BECF competencies, values and rubrics — and differ entirely in content. This
module holds that line.

One nuance from the design itself: Hindu Religious Education deliberately covers
four faiths — "Hinduism/Sanatan, Jain, Buddhist, and Sikh" (PP1 p.213). Their
scriptures and figures appear together in the same KICD design, so within HRE
they are in scope, not contamination.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class FaithScope:
    """What one religious learning area may and may not draw on."""

    subject: str
    faiths: list[str]
    scriptures: list[str]
    reverent_terms: list[str]
    markers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "faiths": list(self.faiths),
            "scriptures": list(self.scriptures),
            "reverent_terms": list(self.reverent_terms),
        }


# Drawn from the PP1 design's own strands, sub-strands and resource lists.
_SCOPES: dict[str, FaithScope] = {
    "christian religious education": FaithScope(
        subject="Christian Religious Education",
        faiths=["Christianity"],
        scriptures=["The Holy Bible (Good News Bible, The Children's Bible)"],
        reverent_terms=["God", "Jesus Christ", "the Holy Bible", "the Church"],
        markers=[
            "bible", "jesus", "christ", "christian", "church", "gospel",
            "adam and eve", "david and goliath", "matthew", "luke", "mark",
            "exodus", "hebrews", "proverbs", "samuel", "commandment",
        ],
    ),
    "hindu religious education": FaithScope(
        subject="Hindu Religious Education",
        # The design covers four faiths together; this is KICD's own scope.
        faiths=["Hinduism/Sanatan", "Jain", "Buddhist", "Sikh"],
        scriptures=[
            "Ramayan", "Bhagwad Gita", "Kalpasutra", "Dhammapada",
            "Tipitaka", "Sri Guru Granth Sahib Ji",
        ],
        reverent_terms=[
            "Paramatma", "Trimurti (Brahma, Vishnu, Mahesh)", "Enlightened Beings",
            "Shri Ram", "Shri Krishna", "Lord Mahavir", "Lord Buddha",
            "Sri Guru Nanak Dev Ji",
        ],
        markers=[
            "paramatma", "trimurti", "brahma", "vishnu", "mahesh", "ramayan",
            "bhagwad", "kalpasutra", "dhammapada", "tipitaka", "guru granth",
            "sadachaar", "sewa", "yoga", "asana", "namaste", "hindu", "jain",
            "buddhist", "sikh", "krishna", "mahavir", "buddha", "waheguru",
        ],
    ),
    "islamic religious education": FaithScope(
        subject="Islamic Religious Education",
        faiths=["Islam"],
        scriptures=["The Holy Qur'an", "Books of Hadith"],
        reverent_terms=[
            "Allah (S.W.T.)", "Prophet Muhammad (S.A.W.)", "the Holy Qur'an",
            "the Masjid",
        ],
        markers=[
            "qur'an", "quran", "allah", "muhammad", "islam", "muslim", "masjid",
            "shahadah", "swalah", "zakat", "sawm", "hajj", "akhlaq", "siirah",
            "eid", "bismillah", "alhamdulillah", "shukran", "ma shaa allah",
            "dua", "anashid", "qasida", "iman",
        ],
    ),
}


# The same three areas are printed differently at every level: "CRE" in the
# Grade 1-9 catalogues, "Christian Religious Education" for DTE and Pre-Primary,
# "Christian Religious Activities" in some PP tables, and whatever the senior
# pathway PDF puts on its cover. Matching exact strings recognised Pre-Primary
# and silently returned nothing for Grades 1 to 9 — the isolation would simply
# not have applied there.
_FAITH_SIGNALS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    # (scope key, substrings, exact abbreviations)
    ("islamic religious education", ("islam", "islamic", "quran", "qur'an"), ("ire", "i r e", "i.r.e")),
    ("hindu religious education", ("hindu", "sanatan"), ("hre", "h r e", "h.r.e")),
    ("christian religious education", ("christian", "christianity"), ("cre", "c r e", "c.r.e")),
)


def _normalise_subject(subject: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", str(subject).lower()).strip()


def scope_for(subject: str | None) -> FaithScope | None:
    """The faith scope for a religious learning area, at any grade.

    Driven entirely by the area's own name, so it applies identically to PP1
    "Christian Religious Education", Grade 4 "CRE" and a senior-school design
    whose cover reads "Christian Religious Education".
    """
    if not subject:
        return None

    flat = _normalise_subject(subject)
    if not flat:
        return None

    direct = _SCOPES.get(flat)
    if direct is not None:
        return direct

    collapsed = flat.replace(" ", "")
    for key, substrings, abbreviations in _FAITH_SIGNALS:
        if flat in abbreviations or collapsed in {a.replace(" ", "").replace(".", "") for a in abbreviations}:
            return _SCOPES[key]
        if any(word in flat for word in substrings):
            return _SCOPES[key]

    return None


def is_religious_area(subject: str | None) -> bool:
    return scope_for(subject) is not None


def prompt_block(subject: str | None) -> str:
    """The isolation directive injected into every prompt for this area.

    Empty for non-religious areas, so the block only appears where it applies.
    """
    scope = scope_for(subject)
    if scope is None:
        return ""

    others = [o for o in _SCOPES.values() if o.subject != scope.subject]
    forbidden = "; ".join(
        f"{o.subject} ({', '.join(o.scriptures[:2])})" for o in others
    )
    faiths = " and ".join(scope.faiths) if len(scope.faiths) <= 2 else ", ".join(scope.faiths)

    lines = [
        f"FAITH SCOPE: this is {scope.subject}. Its content comes from {faiths}.",
        f"  Scriptures in scope: {', '.join(scope.scriptures)}.",
        f"  Refer to: {', '.join(scope.reverent_terms)}.",
        "",
        "  You must NOT draw on any other faith's scriptures, figures, festivals,"
        " prayers or practices. Specifically not: " + forbidden + ".",
        "  A learner sitting this paper follows this faith. Content from another"
        " tradition is not a lesser answer, it is the wrong one, and it is"
        " disrespectful to the child and the family.",
        "  The BECF framework is shared across all three areas — the same"
        " competencies, the same eight core values, the same four-level rubric."
        " The framework is common; the content is not. Follow the KICD design for"
        f" {scope.subject} and nothing else.",
    ]
    if len(scope.faiths) > 1:
        lines.append(
            f"  Note: KICD scopes this single learning area across {faiths}."
            " All of them are in scope here; that is the design's own intent."
        )
    return "\n".join(lines)


def cross_faith_terms(text: str, subject: str | None) -> list[str]:
    """Markers of another faith found in content written for this one.

    Used to catch contamination after generation, because a prompt instruction
    is a request and this is a check.
    """
    scope = scope_for(subject)
    if scope is None or not text:
        return []

    haystack = " " + re.sub(r"[^a-z0-9']+", " ", str(text).lower()) + " "
    found: list[str] = []
    for other in _SCOPES.values():
        if other.subject == scope.subject:
            continue
        for marker in other.markers:
            if marker in scope.markers:
                continue  # shared vocabulary is not contamination
            if re.search(rf"(?<![a-z]){re.escape(marker)}(?![a-z])", haystack):
                found.append(marker)
    return sorted(set(found))
