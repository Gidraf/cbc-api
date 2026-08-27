"""Photographs and videos: planned here, produced elsewhere, attached back.

A diagram is SVG — generated as code, deterministic, editable afterwards. A
photograph and a video are none of those. What the factory can author is the
prompt, the shot list, the alt text and the narration; the asset itself comes
from an image or video model, or a teacher with a phone.
"""
from __future__ import annotations

import pytest

from app.services import media_registry as media


def _photo(**over):
    entry = {
        "title": "An open Bible on a classroom desk",
        "purpose": "identify the Holy Bible from other books",
        "generation_prompt": "A worn Good News Bible lying open on a wooden desk "
                             "in a Kenyan pre-primary classroom, morning light.",
        "negative_prompt": "identifiable faces, brand logos, text overlays",
        "spec": {"aspect_ratio": "4:3", "text_in_image": False},
        "alt_text": "A Bible lying open on a desk beside three other books.",
        "source_pages": [202, 208],
    }
    entry.update(over)
    return entry


def _make(entry, kind="photo"):
    return media.from_generated(
        entry, kind=kind, grade="grade-pp1",
        subject="Christian Religious Education",
        strand="The Bible", sub_strand="A Holy Book",
    )


def test_a_planned_photo_carries_everything_needed_to_produce_it() -> None:
    item = _make(_photo())

    assert item.kind == "photo"
    assert item.status == "planned", "planning is not producing"
    assert item.storage_url == "", "nothing exists yet"
    assert item.generation_prompt.startswith("A worn Good News Bible")
    assert item.source_pages == [202, 208]


def test_a_title_with_no_prompt_is_refused() -> None:
    """Nobody can produce an asset from a title."""
    assert _make(_photo(generation_prompt="")) is None
    assert _make(_photo(title="")) is None


def test_the_id_is_stable_so_replanning_updates_rather_than_duplicates() -> None:
    first = _make(_photo())
    second = _make(_photo(generation_prompt="A different description entirely."))

    assert first.media_id == second.media_id


def test_a_different_medium_of_the_same_subject_is_a_different_asset() -> None:
    photo = _make(_photo())
    video = _make(_photo(), kind="video")

    assert photo.media_id != video.media_id


def test_a_video_keeps_its_shot_list_and_narration() -> None:
    item = _make({
        "title": "Handling the Holy Bible with care",
        "generation_prompt": "A 45-second clip showing how to carry and open a Bible.",
        "shot_list": [
            {"shot": 1, "seconds": 6, "on_screen": "Hands lifting a Bible",
             "narration": "We hold the Holy Bible with two hands."},
        ],
        "narration": "We hold the Holy Bible with two hands.",
        "spec": {"total_seconds": 45},
    }, kind="video")

    assert len(item.shot_list) == 1
    assert item.shot_list[0]["seconds"] == 6
    assert item.narration


def test_junk_page_numbers_do_not_reach_the_record() -> None:
    item = _make(_photo(source_pages=["202", None, "not a page", 208]))

    assert item.source_pages == [202, 208]


@pytest.mark.parametrize("kind,content_type,allowed", [
    ("photo", "image/jpeg", True),
    ("photo", "video/mp4", False),
    ("video", "video/mp4", True),
    ("video", "image/png", False),
    ("photo", "application/x-msdownload", False),
])
def test_only_real_media_types_are_accepted(kind, content_type, allowed) -> None:
    """The upload endpoint decides from this: a photo slot must not take an
    executable, and a video slot must not take a still."""
    assert (content_type in media.ALLOWED_CONTENT_TYPES[kind]) is allowed


def test_a_non_dict_entry_is_refused() -> None:
    assert _make("just a string") is None
