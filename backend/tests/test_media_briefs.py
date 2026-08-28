"""Image and video briefs: always present, deep enough to be worth producing,
and inside the faith's own rules about what may be pictured.

Learning areas with no diagram to draw — CRE has no schematic, Literature has no
apparatus — are exactly the ones that live on pictures. A Kenyan textbook shows
Adam and Eve and the serpent, the wise men bearing gifts, Jomo Kenyatta at
independence. The generator's escape hatch ("return an empty array for a medium
this sub-strand does not need") made those the areas most likely to get nothing.
"""
from __future__ import annotations

import pytest

from app.services.faith_scope import depiction_rules, forbidden_depictions, prompt_block
from app.services.media_validators import (
    MIN_PHOTO_TOKENS, MIN_VIDEO_TOKENS, check, tokens_in,
)


def _photo(tokens=MIN_PHOTO_TOKENS, **extra):
    return {
        "title": "Adam and Eve in the garden",
        "purpose": "name the first human beings created by God",
        "generation_prompt": "x" * (tokens * 4),
        "negative_prompt": "no identifiable faces, no text",
        "alt_text": "Two people among trees, with animals nearby.",
        **extra,
    }


def _video(tokens=MIN_VIDEO_TOKENS, shots=4):
    per_shot = (tokens * 4) // (shots + 1)
    return {
        "title": "The story of creation",
        "purpose": "tell the story of Adam and Eve",
        "generation_prompt": "y" * per_shot,
        "narration_script": "Narration.",
        "shot_list": [
            {"shot": i, "seconds": 6, "camera": "wide",
             "on_screen": "z" * per_shot, "narration": "..."}
            for i in range(1, shots + 1)
        ],
    }


# ── Always present ──────────────────────────────────────────────────────────

def test_a_plan_with_no_images_is_refused() -> None:
    """"This sub-strand does not need images" is almost never true, and it was
    an acceptable answer."""
    report = check({"photos": [], "videos": []}, "Christian Religious Education")

    assert not report.sound
    assert any(f.check == "no_images" for f in report.errors)


def test_a_missing_video_is_a_warning_not_a_block() -> None:
    """Some sub-strands genuinely cannot be filmed; none of them cannot be
    pictured."""
    report = check({"photos": [_photo()], "videos": []}, "Christian Religious Education")

    assert report.sound
    assert any(f.check == "no_video" for f in report.findings)


def test_the_prompt_closes_the_escape_hatch() -> None:
    from app.services.langfuse_seed import SEED_AGENT_PROMPTS

    prompt = SEED_AGENT_PROMPTS["media-prompt-generator"]

    assert "EVERY SUB-STRAND NEEDS IMAGES" in prompt
    assert "is not an acceptable answer" in prompt.replace("\n", " ")
    assert "Adam and Eve" in prompt and "Jomo Kenyatta" in prompt


# ── Deep enough to be worth producing ───────────────────────────────────────

def test_a_thin_image_brief_is_refused() -> None:
    """An image model produces what it is told and invents the rest, and the
    invented parts are where the anachronisms come from."""
    report = check({"photos": [_photo(tokens=120)]}, "Christian Religious Education")

    assert not report.sound
    error = next(f for f in report.errors if f.check == "too_short")
    assert str(MIN_PHOTO_TOKENS) in error.message


def test_a_thin_video_brief_is_refused() -> None:
    report = check({"photos": [_photo()], "videos": [_video(tokens=400)]},
                   "Christian Religious Education")

    assert any(f.check == "too_short" and "story of creation" in f.asset
               for f in report.errors)


def test_a_video_is_measured_across_its_whole_brief() -> None:
    """Premise, every shot and the narration together — not the premise alone."""
    report = check({"photos": [_photo()], "videos": [_video()]},
                   "Christian Religious Education")

    assert report.sound
    assert report.video_tokens[0] >= MIN_VIDEO_TOKENS


def test_a_shot_with_no_description_is_a_caption_not_a_shot() -> None:
    video = _video()
    video["shot_list"][0]["on_screen"] = "Adam and Eve."

    report = check({"photos": [_photo()], "videos": [video]},
                   "Christian Religious Education")

    assert any(f.check == "thin_shot" for f in report.findings)


def test_an_image_without_alt_text_is_refused() -> None:
    """A learner who cannot see it must still be able to meet the outcome."""
    photo = _photo()
    photo["alt_text"] = ""

    assert any(f.check == "no_alt_text" for f in check({"photos": [photo]}).errors)


@pytest.mark.parametrize("chars,expected", [(4_000, 1_000), (20_000, 5_000), (0, 0)])
def test_the_token_estimate_matches_the_chunkers(chars, expected) -> None:
    assert tokens_in("x" * chars) == expected


# ── What may be pictured ────────────────────────────────────────────────────

def test_ire_forbids_depicting_any_prophet() -> None:
    """A CRE lesson may show Adam and Eve; an IRE lesson may not. Getting this
    wrong in a Kenyan classroom is not a quality defect."""
    rules = depiction_rules("Islamic Religious Education")

    assert "Never depict Allah" in rules
    assert "Prophet Muhammad" in rules
    assert "not Adam, Ibrahim, Musa or Isa" in rules
    assert "A workaround is still a depiction" in rules


def test_cre_is_told_to_follow_the_designs_own_lead() -> None:
    """The PP1 design says "observe pictures of Adam and Eve" in its own words."""
    rules = depiction_rules("Christian Religious Education")

    assert "MAY be pictured" in rules
    assert "Adam and Eve" in rules
    assert "Do not depict God the Father as a human figure" in rules


def test_hre_carries_the_conventions_of_all_four_faiths() -> None:
    rules = depiction_rules("Hindu Religious Education")

    for tradition in ("Hindu/Sanatan", "Jain", "Sikh"):
        assert tradition in rules
    assert "Sri Guru Granth Sahib Ji" in rules


def test_a_forbidden_depiction_blocks_the_plan() -> None:
    """The prompt states the rule; this checks it, because a prompt instruction
    is a request."""
    plan = {"photos": [_photo(), {**_photo(), "title": "The Prophet teaching",
                                 "generation_prompt": "An image of the Prophet Muhammad " * 200}]}

    report = check(plan, "Islamic Religious Education")

    assert not report.sound
    assert any(f.check == "forbidden_depiction" for f in report.errors)


def test_the_same_scene_is_allowed_in_cre() -> None:
    plan = {"photos": [{**_photo(), "generation_prompt": "Adam and Eve in Eden " * 400}]}

    assert check(plan, "Christian Religious Education").sound


def test_a_non_religious_area_is_not_checked_for_depictions() -> None:
    assert forbidden_depictions("a picture of the prophet", "Mathematical Activities") == []


def test_the_depiction_rules_reach_every_prompt() -> None:
    """They are part of the faith scope, which every authoring prompt carries."""
    block = prompt_block("Islamic Religious Education")

    assert "WHAT MAY BE PICTURED" in block
    assert "Never depict Prophet Muhammad" in block
