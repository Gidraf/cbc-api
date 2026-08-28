"""Check media briefs for the two things that make them worthless.

An image model produces what it is told and invents the rest. A one-line prompt
buys a generic picture that teaches nothing, and the invented parts are where
the anachronisms and the wrong faces come from — so a brief that is too short is
not a stylistic choice, it is a defect with a predictable failure.

And a depiction the faith scope forbids reaching a Kenyan IRE classroom is not a
quality problem at all. The prompt states the rule; this checks it, because a
prompt instruction is a request and this is a check.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("cbc-media-validators")

# Roughly four characters per token, matching the chunker's own estimate.
CHARS_PER_TOKEN = 4

# What the design asked for: 1,000 tokens of image brief, 5,000 for a video.
MIN_PHOTO_TOKENS = 1_000
MIN_VIDEO_TOKENS = 5_000

# A shot with no description of its own is a caption, not a shot.
MIN_SHOT_CHARS = 120


def tokens_in(text: str) -> int:
    return len(text or "") // CHARS_PER_TOKEN


@dataclass(slots=True)
class MediaFinding:
    severity: str
    asset: str
    check: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {"severity": self.severity, "asset": self.asset,
                "check": self.check, "message": self.message}


@dataclass(slots=True)
class MediaReport:
    photos: int = 0
    videos: int = 0
    findings: list[MediaFinding] = field(default_factory=list)
    photo_tokens: list[int] = field(default_factory=list)
    video_tokens: list[int] = field(default_factory=list)

    @property
    def errors(self) -> list[MediaFinding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def sound(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "sound": self.sound,
            "photos": self.photos,
            "videos": self.videos,
            "photo_tokens": self.photo_tokens,
            "video_tokens": self.video_tokens,
            "errors": [f.to_dict() for f in self.errors],
            "warnings": [f.to_dict() for f in self.findings if f.severity == "warning"],
        }


def _video_tokens(video: dict[str, Any]) -> int:
    """A video brief is its premise plus every shot plus the narration."""
    parts = [str(video.get("generation_prompt") or ""),
             str(video.get("narration_script") or "")]
    for shot in video.get("shot_list") or []:
        if isinstance(shot, dict):
            parts += [str(shot.get(k) or "")
                      for k in ("on_screen", "camera", "audio", "narration")]
    return tokens_in("\n".join(parts))


def check(media: dict[str, Any], subject: str = "") -> MediaReport:
    """Measure a media plan against depth, coverage and the faith's own rules."""
    from .faith_scope import forbidden_depictions

    report = MediaReport()
    if not isinstance(media, dict):
        return report

    photos = [p for p in (media.get("photos") or []) if isinstance(p, dict)]
    videos = [v for v in (media.get("videos") or []) if isinstance(v, dict)]
    report.photos, report.videos = len(photos), len(videos)

    def fail(asset: str, check_name: str, message: str) -> None:
        report.findings.append(MediaFinding("error", asset, check_name, message))

    def warn(asset: str, check_name: str, message: str) -> None:
        report.findings.append(MediaFinding("warning", asset, check_name, message))

    # Learning areas with no diagram to draw are exactly the ones that live on
    # pictures. Returning none is almost never the right answer.
    if not photos:
        fail("(plan)", "no_images",
             "No image brief at all. A learner who cannot yet read learns almost "
             "entirely from the picture, and every learning area needs at least one.")
    if not videos:
        warn("(plan)", "no_video",
             "No video brief. Acceptable only where the sub-strand genuinely "
             "cannot be filmed.")

    for photo in photos:
        title = str(photo.get("title") or "untitled")
        brief = str(photo.get("generation_prompt") or "")
        count = tokens_in(brief)
        report.photo_tokens.append(count)

        if count < MIN_PHOTO_TOKENS:
            fail(title, "too_short",
                 f"{count} tokens; at least {MIN_PHOTO_TOKENS} are needed. An image "
                 "model invents everything the brief does not specify, and the "
                 "invented parts are where the anachronisms come from.")
        if not str(photo.get("alt_text") or "").strip():
            fail(title, "no_alt_text",
                 "No alt text, so a learner who cannot see it cannot meet the outcome.")
        if not str(photo.get("purpose") or "").strip():
            warn(title, "no_purpose",
                 "No learning outcome quoted, so it may be decoration.")
        if not str(photo.get("negative_prompt") or "").strip():
            warn(title, "no_negative_prompt",
                 "Nothing is excluded, so the model may add faces, logos or text.")

    for video in videos:
        title = str(video.get("title") or "untitled")
        count = _video_tokens(video)
        report.video_tokens.append(count)

        if count < MIN_VIDEO_TOKENS:
            fail(title, "too_short",
                 f"{count} tokens across brief, shots and narration; at least "
                 f"{MIN_VIDEO_TOKENS} are needed.")

        shots = [s for s in (video.get("shot_list") or []) if isinstance(s, dict)]
        if not shots:
            fail(title, "no_shot_list", "No shot list, so nobody can film it.")
        for index, shot in enumerate(shots, start=1):
            if len(str(shot.get("on_screen") or "")) < MIN_SHOT_CHARS:
                warn(title, "thin_shot",
                     f"Shot {index} has no description of its own — that is a "
                     "caption, not a shot.")
        if not str(video.get("narration_script") or "").strip():
            warn(title, "no_narration",
                 "No narration script, so the audio is left to whoever produces it.")

    # The faith rules last, over everything, because a workaround is still a
    # depiction and it can appear in any field.
    whole = json.dumps(media, default=str)
    for found in forbidden_depictions(whole, subject):
        fail("(plan)", "forbidden_depiction",
             f"'{found}' appears. {subject} forbids this depiction absolutely; "
             "picture the setting, the objects or the lesson instead.")

    if report.errors:
        logger.warning(
            "Media plan for %s has %d blocking issue(s): %s", subject or "?",
            len(report.errors),
            "; ".join(f"{f.asset}: {f.check}" for f in report.errors[:4]),
        )
    return report
