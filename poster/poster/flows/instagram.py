"""Instagram: Create → Post on the web, which shares a video as a reel."""
from __future__ import annotations

import asyncio

from playwright.async_api import Page

from .base import Flow, NotLoggedIn, check_for_human, click, first, write, wait_text

HOME = "https://www.instagram.com/"


class Instagram(Flow):
    platform = "instagram"
    login_url = "https://www.instagram.com/accounts/login/"
    caption_limit = 2200

    def _create(self, page: Page):
        return [page.locator('svg[aria-label="New post"]'), page.locator('svg[aria-label="Create"]'),
                page.get_by_role("link", name="Create"), page.get_by_role("link", name="New post")]

    async def logged_in(self, page: Page) -> bool:
        await page.goto(HOME, wait_until="domcontentloaded", timeout=60_000)
        await asyncio.sleep(3)
        if "accounts/login" in page.url:
            return False
        try:
            await first(page, self._create(page), timeout=20, what='"Create"')
            return True
        except Exception:  # noqa: BLE001
            return False

    async def post(self, page: Page, *, video: str, caption: str, title: str, dry_run: bool) -> str:
        if not await self.logged_in(page):
            raise NotLoggedIn("Instagram is logged out.")
        await check_for_human(page)
        await (await first(page, self._create(page), what='"Create"')).click()
        await asyncio.sleep(1.5)
        try:   # newer menus ask Post / Live / Ad
            await click(page, "Post", timeout=4)
        except Exception:  # noqa: BLE001
            pass
        await page.locator('input[type="file"]').first.set_input_files(video)
        try:   # "Video posts are now shared as reels"
            await click(page, "OK", timeout=8)
        except Exception:  # noqa: BLE001
            pass
        await click(page, "Next", timeout=120)   # crop
        await click(page, "Next", timeout=60)    # edit
        box = await first(page, [page.locator('div[aria-label="Write a caption..."]'),
                                 page.locator('textarea[aria-label^="Write a caption"]'),
                                 page.locator('[contenteditable="true"][role="textbox"]')], timeout=60, what="the caption box")
        await write(page, box, self.fit(caption))
        await check_for_human(page)
        if dry_run:
            return ""
        await click(page, "Share", timeout=30)
        ok = await wait_text(page, r"(?:reel|post) (?:has been )?shared|your (?:reel|post) has been shared", timeout=600)
        await check_for_human(page)
        if not ok:
            raise RuntimeError("Instagram did not confirm the post.")
        return ""
