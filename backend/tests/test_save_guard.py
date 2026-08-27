"""A learning area's sub-strands must not be saved under the level's name.

Four rounds of generation produced four different partial pictures of PP1 —
first Hindu and Islamic RE, then Mathematics with Islamic RE gone — because all
seven learning areas were written under one subject, "Pre-Primary 1", and the
(grade, subject, strand, sub_strand) key made each save overwrite and prune the
last. Nothing objected, so the loop was invisible.
"""
from __future__ import annotations

import pytest

from app.errors import ApiError
from app.routes import curriculum as routes


def _payload(subject: str, grade: str = "grade-pp1"):
    return routes.FactorySaveSubstrandsRequest(
        grade=grade,
        subject=subject,
        strand_name="1.0 Pre-Number Activities",
        substrands=[{"sub_strand_name": "1.1 Sorting and Grouping"}],
    )


def _save(payload):
    return routes.factory_save_substrands.__wrapped__(payload, None) \
        if hasattr(routes.factory_save_substrands, "__wrapped__") \
        else routes.factory_save_substrands(payload, None)


def test_saving_under_the_level_name_is_refused() -> None:
    with pytest.raises(ApiError) as caught:
        _save(_payload("Pre-Primary 1"))

    error = caught.value
    assert error.code == "MISSING_PARENT_CONTEXT"
    assert error.status_code == 422
    message = error.message
    assert "not a learning area" in message
    assert "overwrite the last" in message
    # It names what to use instead, rather than only saying no.
    assert "Language Activities" in message
    assert "Mathematical Activities" in message
    # And it names the cause the operator can act on.
    assert "has not been re-ingested" in message


@pytest.mark.parametrize("subject", ["Pre-Primary 1", "Pre-Primary 2", "PP1", "pre-primary"])
def test_every_spelling_of_the_level_is_refused(subject: str) -> None:
    for grade in ("grade-pp1", "grade-pp2"):
        with pytest.raises(ApiError):
            _save(_payload(subject, grade))


@pytest.mark.parametrize(
    "subject",
    ["Language Activities", "Mathematical Activities", "Creative Activities",
     "Environmental Activities", "Christian Religious Education",
     "Hindu Religious Education", "Islamic Religious Education"],
)
def test_the_seven_real_learning_areas_pass_the_guard(subject: str, monkeypatch) -> None:
    """The guard must not block correct work; it fails at the DB write here,
    which is past the check and proves the check let it through."""
    with pytest.raises(Exception) as caught:
        _save(_payload(subject))

    assert not isinstance(caught.value, ApiError) or \
        "not a learning area" not in getattr(caught.value, "message", "")


def test_grades_whose_subjects_come_off_the_pdf_cover_are_not_policed(monkeypatch) -> None:
    """Senior-school designs are published by pathway; the real subject is only
    on each PDF's cover, so an unlisted name there is expected, not an error."""
    payload = routes.FactorySaveSubstrandsRequest(
        grade="grade-11",
        subject="Something Only The Cover Knows",
        strand_name="1.0 Whatever",
        substrands=[{"sub_strand_name": "1.1 Thing"}],
    )

    with pytest.raises(Exception) as caught:
        _save(payload)

    assert "not a learning area" not in getattr(caught.value, "message", "")
