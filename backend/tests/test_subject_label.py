"""The subject as CBC names it on a video: by grade, or by the topic's level."""
from __future__ import annotations

import pytest

from app.services.social import brand_name, subject_label


@pytest.mark.parametrize("curriculum, chemistry, label", [
    ({"grade": "Grade 8", "subject": "Chemistry"}, None, "Integrated Science"),     # no Chemistry in Junior School
    ({"grade": "Grade 7", "subject": "Integrated Science"}, {"separate": ["sand", "salt"]}, "Integrated Science"),
    ({"grade": "Grade 10", "subject": "Chemistry"}, None, "Chemistry"),
    ({"grade": "Grade 11", "subject": "Physics"}, None, "Physics"),
    ({"grade": "Grade 5", "subject": "Science"}, None, "Science and Technology"),
    ({"grade": "Grade 2", "subject": "Science"}, None, "Environmental Activities"),
    ({"subject": "Chemistry"}, {"separate": ["sand", "salt"]}, "Integrated Science"),  # no grade: by the topic
    ({"subject": "Chemistry"}, {"atom": "Mg"}, "Integrated Science"),
    ({"subject": "Chemistry"}, {"bond": ["Na", "Cl"]}, "Chemistry"),
    ({"subject": "Chemistry"}, {"reactants": ["Zn", "HCl"]}, "Chemistry"),
    ({"grade": "Grade 7", "subject": "Mathematics"}, None, "Mathematics"),
])
def test_the_subject_as_cbc_names_it(curriculum, chemistry, label) -> None:
    q = {"curriculum": curriculum, **({"chemistry": chemistry} if chemistry else {})}
    assert subject_label(q) == label


def test_the_brand_follows_it() -> None:
    b = {"name": "CBC Maths"}
    assert brand_name(b, {"curriculum": {"grade": "Grade 9", "subject": "Chemistry"}}) == "CBC Integrated Science"
    assert brand_name(b, {"curriculum": {"grade": "Grade 12", "subject": "Chemistry"}}) == "CBC Chemistry"
    assert brand_name(b, {"curriculum": {"grade": "Grade 6", "subject": "Mathematics"}}) == "CBC Maths"
    assert brand_name({"name": "Mwalimu Hub"}, {"curriculum": {"grade": "Grade 9", "subject": "Chemistry"}}) == "Mwalimu Hub"
