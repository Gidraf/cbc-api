"""Facebook Page: Meta Business Suite's reel composer."""
from __future__ import annotations

import asyncio

from playwright.async_api import Page

from .base import Flow, NotLoggedIn, check_for_human, click, first, write, wait_text

COMPOSER = "https://business.facebook.com/latest/reels_composer"


class Facebook(Flow):
    platform = "facebook"
    login_url = "https://www.facebook.com/login"
    caption_limit = 2200

    async def logged_in(self, page: Page) -> bool:
        await page.goto(COMPOSER, wait_until="domcontentloaded", timeout=60_000)
        await asyncio.sleep(4)
        if "login" in page.url:
            return False
        try:
            await first(page, [page.locator('input[type="file"]'), page.get_by_text("Add video")], timeout=25,
                        what="the reel composer")
            return True
        except Exception:  # noqa: BLE001
            return False

    async def post(self, page: Page, *, video: str, caption: str, title: str, dry_run: bool) -> str:
        if not await self.logged_in(page):
            raise NotLoggedIn("Facebook is logged out.")
        await check_for_human(page)
        await page.locator('input[type="file"]').first.set_input_files(video)
        box = await first(page, [page.locator('[contenteditable="true"][role="textbox"]'),
                                 page.locator('div[aria-label*="escri" i][contenteditable="true"]'),
                                 page.locator("textarea")], timeout=180, what="the description box")
        await write(page, box, self.fit(caption))
        for _ in range(3):   # Next until Share/Publish is on screen
            try:
                await first(page, [page.get_by_role("button", name=n) for n in ("Share", "Publish")], timeout=3)
                break
            except Exception:  # noqa: BLE001
                try:
                    await click(page, "Next", timeout=30)
                except Exception:  # noqa: BLE001
                    break
        await check_for_human(page)
        if dry_run:
            return ""
        await click(page, "Share", "Publish", timeout=300)
        ok = await wait_text(page, r"reel (?:is )?(?:being )?(?:published|shared)|published|your reel", timeout=600)
        await check_for_human(page)
        if not ok:
            raise RuntimeError("Facebook did not confirm the reel.")
        return ""
