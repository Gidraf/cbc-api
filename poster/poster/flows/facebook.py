"""Facebook: a reel on your own profile (the default) or on a Page.

Profile: facebook.com/reels/create — one screen: description, the video,
then Post. Post lights up before the upload is done, so it waits for the
preview's "Uploading N%" to go first.

Page (FACEBOOK_TARGET=page): Meta Business Suite's reel composer —
Create → Edit → Share. The video goes in through "Add Video"; the step
tabs at the top are buttons too, so the final Share is the footer's.
"""
from __future__ import annotations

import asyncio
import re
import time

from playwright.async_api import Page

from .. import config
from .base import Flow, NotLoggedIn, StepFailed, check_for_human, enabled, first, wait_text, write

PROFILE_COMPOSER = "https://www.facebook.com/reels/create/"
PAGE_COMPOSER = "https://business.facebook.com/latest/reels_composer"


def _logged_out(url: str) -> bool:
    return bool(re.search(r"/login|checkpoint|recover", url))


async def _uploaded(page: Page, timeout: float = 900.0) -> None:
    """Until the preview stops saying "Uploading" / "Processing"."""
    busy = page.get_by_text(re.compile(r"^\s*(Uploading|Processing)\b", re.I))
    deadline = time.monotonic() + timeout
    await asyncio.sleep(2)
    while time.monotonic() < deadline:
        try:
            if not await busy.count() or not await busy.first.is_visible():
                return
        except Exception:  # noqa: BLE001
            return
        await asyncio.sleep(2)
    raise StepFailed("The video did not finish uploading in time.")


async def _settled(page: Page, pattern: str, seconds: float) -> None:
    """Give a passing notice a little time to go; never fail on it."""
    note = page.get_by_text(re.compile(pattern, re.I))
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if not await note.count() or not await note.first.is_visible():
                return
        except Exception:  # noqa: BLE001
            return
        await asyncio.sleep(3)


class Facebook(Flow):
    platform = "facebook"
    caption_limit = 2200

    @property
    def page_mode(self) -> bool:
        return config.FACEBOOK_TARGET == "page"

    @property
    def login_url(self) -> str:  # type: ignore[override]
        # The composer itself: it asks for a login only when one is needed,
        # instead of facebook.com/login bouncing a logged-in owner to the feed.
        return PAGE_COMPOSER if self.page_mode else PROFILE_COMPOSER

    async def logged_in(self, page: Page) -> bool:
        await page.goto(self.login_url, wait_until="domcontentloaded", timeout=60_000)
        await asyncio.sleep(4)
        if _logged_out(page.url):
            return False
        try:
            if self.page_mode:
                await first(page, [page.get_by_role("button", name="Add Video")], timeout=25, what="the reel composer")
            else:
                await page.locator('input[type="file"][accept*="video"]').first.wait_for(state="attached", timeout=25_000)
            return True
        except Exception:  # noqa: BLE001
            return False

    async def post(self, page: Page, *, video: str, caption: str, title: str, dry_run: bool) -> str:
        if not await self.logged_in(page):
            raise NotLoggedIn("Facebook is logged out.")
        await check_for_human(page)
        if self.page_mode:
            return await self._page_reel(page, video=video, caption=caption, dry_run=dry_run)
        return await self._profile_reel(page, video=video, caption=caption, dry_run=dry_run)

    async def _profile_reel(self, page: Page, *, video: str, caption: str, dry_run: bool) -> str:
        await page.locator('input[type="file"][accept*="video"]').first.set_input_files(video)
        box = await first(page, [page.locator('[contenteditable="true"][role="textbox"]')], timeout=60,
                          what="the description box")
        await write(page, box, self.fit(caption))
        await _uploaded(page)
        await _settled(page, r"Checking for copyrighted", 120)   # posting can go ahead without it, but give it a moment
        post = page.get_by_role("button", name="Post", exact=True).last
        await enabled(post, timeout=300)
        await check_for_human(page)
        if dry_run:
            return ""
        await post.click()
        ok = await _left_composer_or_said(page, "/reels/create")
        await check_for_human(page)
        if not ok:
            raise RuntimeError("Facebook did not confirm the reel.")
        return ""

    async def _page_reel(self, page: Page, *, video: str, caption: str, dry_run: bool) -> str:
        add = await first(page, [page.get_by_role("button", name="Add Video")], timeout=30, what='"Add Video"')
        async with page.expect_file_chooser(timeout=20_000) as chooser:
            await add.click()
        await (await chooser.value).set_files(video)
        box = await first(page, [page.locator('[contenteditable="true"][role="textbox"]')], timeout=60,
                          what="the description box")
        await write(page, box, self.fit(caption))
        share_now = page.get_by_text("Share now", exact=True)
        for _ in range(4):       # Create → Edit → Share
            if await share_now.count() and await share_now.first.is_visible():
                break
            nxt = page.get_by_role("button", name="Next", exact=True).last
            await enabled(nxt, timeout=600)
            await nxt.click()
            await asyncio.sleep(3)
        else:
            raise StepFailed("Never reached the Share step.")
        await share_now.first.click()
        share = page.get_by_role("button", name="Share", exact=True).last   # the footer's, not the step tab
        await enabled(share, timeout=600)
        await check_for_human(page)
        if dry_run:
            return ""
        await share.click()
        ok = await _left_composer_or_said(page, "reels_composer")
        await check_for_human(page)
        if not ok:
            raise RuntimeError("Facebook did not confirm the reel.")
        return ""


async def _left_composer_or_said(page: Page, composer: str, timeout: float = 600.0) -> bool:
    """Done when the composer closes, or the page says the reel is out."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if composer not in page.url:
            return True
        if await wait_text(page, r"reel (?:is |has been )?(?:being )?(?:published|shared|posted)|your reel is", timeout=4):
            return True
    return False
