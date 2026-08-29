"""Which generator produced a piece of content.

Queued work is held in the jobs table until somebody accepts it, so a draft
outlives the code that made it. That is the point — a run survives a refresh, a
deploy and a restart — but it has a consequence nobody sees coming: after the
generator is fixed, the console still shows drafts produced by the old one, and
they look exactly like fresh output.

That cost four rounds of "how accurate is this" on output that had already been
diagnosed, because nothing in a draft said which generator wrote it.

BUMP THIS whenever a change alters what generation produces — a new extractor,
a changed prompt, a repaired parser. Do not bump it for refactors that cannot
change output. Drafts stamped with an older version are marked stale in the
console rather than silently served as current.
"""
from __future__ import annotations

# Date plus what changed, so a stale draft says what it is missing rather than
# only that it is old.
VERSION = "2026-08-29.rubric-page-scoping"

# What changed at each bump, newest first. Shown to the operator so a stale
# draft explains itself.
HISTORY: tuple[tuple[str, str], ...] = (
    ("2026-08-29.rubric-page-scoping",
     "Rubric rows are matched on topic words rather than assessment verbs and "
     "must come from the sub-strand's own rubric page; wrapped fragments no "
     "longer pass as rubric levels; source pages are bounded."),
    ("2026-08-28.rubric-tables",
     "KICD's own rubric tables are read from the pages they are printed on, "
     "and page references are resolved rather than guessed."),
    ("2026-08-27.baseline",
     "Sub-strand generation before rubric tables were read."),
)


def describe(version: str) -> str:
    """What a draft stamped with this version was missing."""
    if version == VERSION:
        return "current"
    for known, summary in HISTORY:
        if known == version:
            return summary
    return "produced before generator versions were recorded"


def is_current(version: str | None) -> bool:
    return str(version or "") == VERSION
