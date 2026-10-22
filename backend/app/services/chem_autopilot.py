"""Chemistry on autopilot: find where in the stored KICD curriculum each part
of the chemistry engine belongs (separating mixtures, atoms, bonding,
reactions), save the engine's questions there, and book them — videos into
the open room of each day from tomorrow, the photo series after — and keep
them booking (Auto-book), so nobody has to work out which grade or
sub-strand a video belongs to.

The placement reads the curriculum itself: each science sub-strand's name,
strand, learning outcomes and inquiry questions, scored for each kind's
words ("separating mixtures", "electron arrangement", "chemical bond",
"chemical reactions", "acids"...), the level counting too — Integrated
Science in Junior School for mixtures and atoms, Chemistry in Senior School
for bonding and reactions when the design is there.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any

logger = logging.getLogger("cbc-chem-autopilot")

# Each kind's words, with their weight, looked for in a sub-strand's name (×3), strand, outcomes and questions.
WORDS: dict[str, list[tuple[str, int]]] = {
    "separations": [("separat", 10), ("mixture", 7), ("filtration", 6), ("chromatograph", 6), ("distillation", 6),
                    ("crystallis", 5), ("decant", 4), ("evaporat", 3), ("sublimation", 5), ("pure substance", 4)],
    "atoms": [("atomic structure", 10), ("structure of the atom", 10), ("electron arrangement", 10), ("atom", 6),
              ("periodic table", 6), ("proton", 4), ("isotope", 4), ("element", 3), ("electron", 3)],
    "bonding": [("chemical bond", 10), ("bonding", 9), ("ionic", 6), ("covalent", 6), ("chemical formula", 5),
                ("compound", 3), ("valency", 5), ("formula", 3), ("bond", 4)],
    "reactions": [("chemical reaction", 10), ("reactivity", 8), ("acid", 5), ("base", 3), ("salt", 3), ("indicator", 2),
                  ("chemical change", 6), ("equation", 4), ("combustion", 4), ("metal", 2), ("neutralis", 5), ("oxide", 2)],
}
PREFER = {"separations": "Junior School", "atoms": "Junior School", "bonding": "Senior School", "reactions": "Senior School"}
SCIENCE = ("%integrated science%", "%chemistry%", "%science%")
KIND_LABEL = {"separations": "Separating mixtures", "atoms": "Electron arrangements", "bonding": "Bonding and formulae",
              "reactions": "Reactions"}


def _text(v: Any) -> str:
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            return v
    if isinstance(v, list):
        return " ".join(_text(x) for x in v)
    if isinstance(v, dict):
        return " ".join(_text(x) for x in v.values())
    return str(v or "")


def _rows() -> list[dict[str, Any]]:
    from ..infra.db import fetch_all

    return fetch_all("""SELECT grade, subject, strand_name, sub_strand_name, slos, key_inquiry_questions
                        FROM curriculum_substrands
                        WHERE LOWER(subject) LIKE ANY (CAST(:pats AS text[]))""", {"pats": list(SCIENCE)}) or []


def score(row: dict[str, Any], kind: str) -> int:
    from .grade_order import grade_level

    name = str(row.get("sub_strand_name") or "").lower()
    body = " ".join([str(row.get("strand_name") or ""), _text(row.get("slos")), _text(row.get("key_inquiry_questions"))]).lower()
    s = 0
    for word, w in WORDS[kind]:
        if word in name:
            s += 3 * w
        s += w * min(3, len(re.findall(re.escape(word), body)))
    level = grade_level(str(row.get("grade") or ""))
    if level == PREFER[kind]:
        s += 8
    subject = str(row.get("subject") or "").lower()
    if "chemistry" in subject:
        s += 12                                        # the subject named for it, when its design is in
    elif "integrated science" in subject:
        s += 4
    elif level in ("Upper Primary", "Lower Primary", "Pre-Primary"):
        s -= 15                                        # too young for these
    return s


def place(rows: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Each kind's best sub-strand in the stored curriculum (and how sure)."""
    from .grade_order import grade_label, normalize_grade

    rows = _rows() if rows is None else rows
    out = []
    for kind in WORDS:
        ranked = sorted(((score(r, kind), r) for r in rows), key=lambda x: -x[0])
        if not ranked or ranked[0][0] < 20:
            continue
        point = lambda sc, x: {"grade": normalize_grade(str(x["grade"])) or str(x["grade"]),  # noqa: E731
                               "grade_label": grade_label(str(x["grade"])), "subject": str(x["subject"]),
                               "strand": str(x.get("strand_name") or ""), "sub_strand": str(x.get("sub_strand_name") or ""),
                               "score": sc}
        s, r = ranked[0]
        options = [point(sc, x) for sc, x in ranked[:6] if sc >= 10]
        out.append({"kind": kind, "label": KIND_LABEL[kind], **point(s, r),
                    "next": [{"grade": o["grade_label"], "sub_strand": o["sub_strand"], "score": o["score"]} for o in options[1:3]],
                    "options": options})
    return out


# How many of each kind to save: 0 is every one the engine makes (separations, 56,000+, would be decades of posts).
DEFAULT_COUNTS = {"separations": 1000, "reactions": 0, "bonding": 0, "atoms": 0}


def run(*, dry: bool = False, counts: dict[str, int] | None = None, per_day: int = 0, keep_booking: bool = False,
        photo_days: int = 0, by: str = "", now: datetime | None = None,
        overrides: dict[str, dict[str, str]] | None = None) -> dict[str, Any]:
    """Place, save, book. `dry` shows the plan and writes nothing. `overrides`:
    a kind's own choice of grade/subject/strand/sub-strand instead of the best match."""
    from . import chem_bank, platform_settings, social_export
    from .grade_order import grade_label, normalize_grade

    placements = place()
    for p in placements:
        o = (overrides or {}).get(p["kind"])
        if o and o.get("sub_strand") and o.get("subject") and o.get("grade"):
            p.update({"grade": normalize_grade(o["grade"]) or o["grade"], "grade_label": grade_label(o["grade"]),
                      "subject": o["subject"], "strand": o.get("strand", ""), "sub_strand": o["sub_strand"], "chosen": True})
    if not placements:
        raise ValueError("No science sub-strands in the stored curriculum mention mixtures, atoms, bonding or reactions — "
                         "ingest the KICD Integrated Science (or Chemistry) designs first.")
    counts = {**DEFAULT_COUNTS, **(counts or {})}
    have = {k: v["questions"] for k, v in chem_bank.summary().items()}
    plan = [{**p, "available": have.get(p["kind"], 0),
             "questions": have.get(p["kind"], 0) if not counts.get(p["kind"]) else min(counts[p["kind"]], have.get(p["kind"], 0))}
            for p in placements]
    if dry:
        return {"dry": True, "placements": plan, "booked": None}
    saved = []
    for p in plan:
        r = chem_bank.bank(p["kind"], {k: p[k] for k in ("grade", "subject", "strand", "sub_strand")}, max(1, p["questions"]), by=by,
                           cap=None)
        saved.append({**p, "saved": r["saved"], "already": r["already"]})
    scopes = list(dict.fromkeys((p["grade"], p["subject"], p["sub_strand"]) for p in plan))
    rules = social_export.auto_book_rules()
    per_day = max(1, min(int(per_day or rules["per_day"]), social_export.HARD_DAILY_CAP))
    now = now or datetime.now(social_export.EAT)
    booked = []
    for i in range(2):                                   # this month and next: the open room of each day from tomorrow
        y, m = (now.year + (now.month - 1 + i) // 12, (now.month - 1 + i) % 12 + 1)
        days = social_export.month_view(y, m, platforms=["facebook"], per_day=per_day)["days"]
        r = social_export.fill_days(days, scopes, per_day=per_day, platforms=["facebook"], created_by=by or "chem-autopilot")
        booked.append({"month": f"{y}-{m:02d}", "videos": r.get("videos", 0), "posts": r.get("posts", 0),
                       "to_render": r.get("to_render", 0), "notes": r.get("notes", [])})
    photos = []
    if photo_days > 0:
        for p in plan:
            try:
                r = social_export.book_series(p["grade"], p["subject"], p["sub_strand"], days=photo_days,
                                              created_by=by or "chem-autopilot")
                photos.append({"kind": p["kind"], "photos": r.get("photos", 0), "videos": r.get("videos", 0),
                               "first_day": r.get("first_day"), "last_day": r.get("last_day")})
            except ValueError as exc:
                photos.append({"kind": p["kind"], "error": str(exc)})
    auto = {"enabled": bool(rules["enabled"]), "added": []}
    if keep_booking:
        existing = [f"{g}|{s}|{ss}" for g, s, ss in (rules["scopes"] or social_export._scopes_booked_before())]
        add = [f"{g}|{s}|{ss}" for g, s, ss in scopes if f"{g}|{s}|{ss}" not in existing]
        platform_settings.set_many({"poster_auto_book_scopes": existing + add, "poster_auto_book": True}, updated_by=by or "chem-autopilot")
        auto = {"enabled": True, "added": add}
    return {"dry": False, "placements": saved, "booked": booked, "photos": photos, "auto_book": auto, "per_day": per_day}
