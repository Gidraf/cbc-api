"""A JSONB write must not lose work that has already been paid for.

A three-layer review failed at the INSERT: the model was called, the tokens
were spent, the verdict was computed — and it was thrown away because `usage`
held a TokenUsage dataclass and json.dumps raises on anything that is not a
primitive. The request returned 500 with nothing saved and nothing to retry
from, and every one of the 98 to_json call sites had the same exposure.
"""
from __future__ import annotations

import dataclasses
import datetime
import decimal
import json
import uuid

import pytest

from app.infra.db import to_json
from app.services.cost_tracker import TokenUsage
from app.services.review_layers import normalise_usage


def test_the_shape_that_actually_broke_it() -> None:
    stored = json.loads(to_json({"usage": TokenUsage(10, 20, 30)}))

    assert stored["usage"] == {
        "prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30,
    }


@dataclasses.dataclass
class _Nested:
    name: str
    counts: dict


def test_a_dataclass_keeps_its_structure() -> None:
    """Falling back to str() here would store "_Nested(name='x'…)" — readable
    by a person, useless to every query."""
    stored = json.loads(to_json({"row": _Nested("x", {"n": 1})}))

    assert stored["row"] == {"name": "x", "counts": {"n": 1}}


class _WithToDict:
    def to_dict(self):
        return {"kind": "profile", "ok": True}


def test_an_object_that_knows_its_own_dict_form_is_asked() -> None:
    assert json.loads(to_json(_WithToDict())) == {"kind": "profile", "ok": True}


@pytest.mark.parametrize("value,expected", [
    (datetime.date(2026, 8, 28), "2026-08-28"),
    (decimal.Decimal("1.5"), 1.5),
    (uuid.UUID(int=7), "00000000-0000-0000-0000-000000000007"),
    ({1, 2}, [1, 2]),
    ((1, 2), [1, 2]),
    (b"bytes", "bytes"),
])
def test_the_types_a_row_actually_carries(value, expected) -> None:
    assert json.loads(to_json({"v": value}))["v"] == expected


def test_an_unknown_type_degrades_rather_than_raising() -> None:
    """Losing fidelity on one field beats losing the whole write."""
    class Opaque:
        def __repr__(self):
            return "<opaque>"

    assert json.loads(to_json({"v": Opaque()}))["v"] == "<opaque>"


def test_primitives_are_untouched() -> None:
    payload = {"a": 1, "b": "two", "c": [3, None], "d": {"e": True}}

    assert json.loads(to_json(payload)) == payload


# ── The usage shape itself ──────────────────────────────────────────────────

@pytest.mark.parametrize("usage,expected", [
    (TokenUsage(1, 2, 3), {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}),
    ({"prompt_tokens": 4}, {"prompt_tokens": 4}),
    (None, {}),
])
def test_usage_is_normalised_whatever_the_provider_returned(usage, expected) -> None:
    """Providers return a dataclass, a pydantic model or a bare dict, and the
    review is worth keeping regardless of which."""
    assert normalise_usage(usage) == expected


def test_usage_from_an_object_with_plain_attributes() -> None:
    class Usage:
        prompt_tokens = 7
        completion_tokens = 8
        total_tokens = 15
        model = "gpt-4o"

    assert normalise_usage(Usage()) == {
        "prompt_tokens": 7, "completion_tokens": 8, "total_tokens": 15,
    }


def test_the_review_route_normalises_before_saving() -> None:
    """to_json would now cope either way, but storing the right shape is not the
    same as storing a shape that serialises."""
    route = open("app/routes/artifacts.py").read()

    assert "normalise_usage(response.usage)" in route
    assert "verdict.usage = response.usage" not in route
