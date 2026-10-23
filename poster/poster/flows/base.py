"""What every platform's posting steps share.

Sites change their buttons. Each step looks for its control by role and
visible name, with a few fallbacks, and every run can be a dry run: all the
steps except the final "Post", with a screenshot of what would go out.

A login check, a puzzle or an "is this you?" page is never answered here:
the run stops, the screen is left on it, and the owner finishes it by hand.
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from typing import Iterable

from playwright.async_api import Locator, Page

from .. import config

_HUMAN = re.compile(
    r"captcha|i'?m not a robot|verify (?:it'?s |that it'?s )?(?:you|your identity)|security check|"
    r"unusual (?:activity|traffic)|suspicious|confirm (?:it'?s|your) (?:you|identity)|enter (?:the|your) "
    r"(?:security |verification )?code|two-factor|2-step verification|drag the (?:slider|puzzle)|select all (?:images|squares)",
    re.I)


class NeedsHuman(Exception):
    """The site wants a person: a check, a puzzle, a code."""


class NotLoggedIn(Exception):
    """The saved session no longer works on this platform."""


# Commands from the console (Post now, Log in, Check…) come first: while one is
# waiting, background work (comments, likes) stops at its next safe point.
URGENT = {"n": 0}


class Yielded(Exception):
    """A background step stepped aside for a command; it runs again later, not counted as a failure."""


def yield_point() -> None:
    # "shield": the finishing touch of a post in hand (its animated comment) is not background work.
    if URGENT["n"] > 0 and not URGENT.get("shield"):
        raise Yielded("A command from the console came first.")


class StepFailed(Exception):
    """A control the steps expect was not found — the site has changed."""


async def check_for_human(page: Page) -> None:
    try:
        text = (await page.inner_text("body", timeout=5_000))[:30_000]
    except Exception:  # noqa: BLE001
        text = ""
    frames = " ".join((f.url or "") for f in page.frames)
    if _HUMAN.search(text) or re.search(r"recaptcha|hcaptcha|arkoselabs|funcaptcha|captcha", frames, re.I):
        raise NeedsHuman("The site is asking for a check by a person — finish it on the screen.")


async def shot(page: Page, name: str) -> str:
    os.makedirs(config.SHOTS_DIR, exist_ok=True)
    file = f"{name}-{int(time.time())}.png"
    try:
        await page.screenshot(path=os.path.join(config.SHOTS_DIR, file), full_page=False)
    except Exception:  # noqa: BLE001
        return ""
    return file


async def first(page: Page, candidates: Iterable[Locator], timeout: float = 20.0, what: str = "") -> Locator:
    """The first of several ways to find a control that becomes visible."""
    candidates = list(candidates)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for c in candidates:
            try:
                if await c.count() and await c.first.is_visible():
                    return c.first
            except Exception:  # noqa: BLE001
                pass
        await asyncio.sleep(0.5)
    raise StepFailed(f"Could not find {what or 'the next control'} — the page may have changed.")


def button(page: Page, *names: str) -> list[Locator]:
    out: list[Locator] = []
    for n in names:
        pattern = re.compile(rf"^\s*{n}\s*$", re.I)
        out += [page.get_by_role("button", name=pattern), page.get_by_role("link", name=pattern)]
    return out


async def click(page: Page, *names: str, timeout: float = 20.0) -> None:
    target = await first(page, button(page, *names), timeout=timeout, what=" or ".join(f'"{n}"' for n in names))
    await target.click()
    await asyncio.sleep(1.0)


async def enabled(locator: Locator, timeout: float = 600.0) -> None:
    """Wait until a control can be pressed — an upload finishing."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if await locator.is_enabled() and (await locator.get_attribute("aria-disabled")) not in ("true",):
                return
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(2.0)
    raise StepFailed("The upload did not finish in time.")


async def write(page: Page, box: Locator, text: str) -> None:
    """Replace whatever is in a caption box with `text`."""
    await box.click()
    await page.keyboard.press("ControlOrMeta+A")   # Cmd on a Mac
    await page.keyboard.press("Delete")
    await page.keyboard.insert_text(text)
    await asyncio.sleep(0.5)
    await page.keyboard.press("Escape")   # close hashtag or mention suggestions


async def wait_text(page: Page, pattern: str, timeout: float = 180.0) -> bool:
    deadline = time.monotonic() + timeout
    rx = re.compile(pattern, re.I)
    while time.monotonic() < deadline:
        try:
            if rx.search(await page.inner_text("body", timeout=5_000)):
                return True
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(2.0)
    return False


class Flow:
    platform = ""
    login_url = ""
    caption_limit = 2200
    can_schedule = False      # fills in the platform's own Schedule (post(schedule_at=...))
    can_share_groups = False  # ticks groups in the composer (post(groups=...))
    shared_groups: list[str] = []
    destinations: list[str] = []   # where the last post went on the platform (reel, feed, story)

    async def logged_in(self, page: Page) -> bool:  # pragma: no cover - site specific
        raise NotImplementedError

    async def post(self, page: Page, *, video: str, caption: str, title: str, dry_run: bool) -> str:  # pragma: no cover
        raise NotImplementedError

    def fit(self, caption: str) -> str:
        """The caption within the platform's limit, cut at a line, never mid-word."""
        if len(caption) <= self.caption_limit:
            return caption
        cut = caption[: self.caption_limit - 1]
        return cut[: cut.rfind("\n")] if "\n" in cut else cut[: cut.rfind(" ")]
