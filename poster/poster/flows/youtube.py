"""YouTube Shorts: the YouTube Studio upload dialog."""
from __future__ import annotations

import asyncio

from playwright.async_api import Page

from .. import config
from .base import Flow, NotLoggedIn, StepFailed, check_for_human, enabled, first, write

STUDIO = "https://studio.youtube.com/"
UPLOAD = "https://www.youtube.com/upload"


class YouTube(Flow):
    platform = "youtube"
    login_url = "https://accounts.google.com/ServiceLogin?service=youtube&continue=https%3A%2F%2Fstudio.youtube.com%2F"
    caption_limit = 4900

    async def logged_in(self, page: Page) -> bool:
        await page.goto(STUDIO, wait_until="domcontentloaded", timeout=60_000)
        await asyncio.sleep(4)
        if "accounts.google.com" in page.url:
            return False
        try:
            await first(page, [page.locator("#create-icon"), page.get_by_role("button", name="Create")], timeout=25,
                        what='"Create"')
            return True
        except Exception:  # noqa: BLE001
            return False

    async def post(self, page: Page, *, video: str, caption: str, title: str, dry_run: bool) -> str:
        if not await self.logged_in(page):
            raise NotLoggedIn("YouTube is logged out.")
        await page.goto(UPLOAD, wait_until="domcontentloaded", timeout=60_000)
        await check_for_human(page)
        await page.locator('input[type="file"]').first.set_input_files(video)
        title_box = await first(page, [page.locator("#title-textarea #textbox")], timeout=180, what="the title box")
        await write(page, title_box, title[:100])
        description = await first(page, [page.locator("#description-textarea #textbox")], timeout=30,
                                  what="the description box")
        await write(page, description, self.fit(caption))
        kids = "VIDEO_MADE_FOR_KIDS_MFK" if config.YOUTUBE_MADE_FOR_KIDS else "VIDEO_MADE_FOR_KIDS_NOT_MFK"
        await (await first(page, [page.locator(f'tp-yt-paper-radio-button[name="{kids}"]')], timeout=30,
                           what="the made-for-kids choice")).click()
        for _ in range(3):   # Details → Video elements → Checks → Visibility
            nxt = await first(page, [page.locator("#next-button")], timeout=30, what='"Next"')
            await enabled(nxt, timeout=120)
            await nxt.click()
            await asyncio.sleep(1.5)
        await (await first(page, [page.locator('tp-yt-paper-radio-button[name="PUBLIC"]')], timeout=30,
                           what='"Public"')).click()
        link = ""
        try:
            anchor = await first(page, [page.locator("a.style-scope.ytcp-video-info"), page.locator("span.video-url-fadeable a")],
                                 timeout=20, what="the video link")
            link = await anchor.get_attribute("href") or ""
        except StepFailed:
            pass
        await check_for_human(page)
        if dry_run:
            return link
        done = await first(page, [page.locator("#done-button")], timeout=30, what='"Publish"')
        await enabled(done, timeout=900)     # processing far enough to publish
        await done.click()
        await asyncio.sleep(5)
        await check_for_human(page)
        return link
