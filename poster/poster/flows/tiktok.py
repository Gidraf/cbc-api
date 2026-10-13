"""TikTok: TikTok Studio's upload page."""
from __future__ import annotations

import asyncio

from playwright.async_api import Page

from .base import Flow, NotLoggedIn, check_for_human, click, enabled, first, write, wait_text

UPLOAD = "https://www.tiktok.com/tiktokstudio/upload?from=webapp"


class TikTok(Flow):
    platform = "tiktok"
    login_url = "https://www.tiktok.com/login"
    caption_limit = 4000

    async def logged_in(self, page: Page) -> bool:
        await page.goto(UPLOAD, wait_until="domcontentloaded", timeout=60_000)
        await asyncio.sleep(3)
        if "/login" in page.url:
            return False
        try:
            await first(page, [page.locator('input[type="file"]')], timeout=20, what="the upload box")
            return True
        except Exception:  # noqa: BLE001
            return False

    async def post(self, page: Page, *, video: str, caption: str, title: str, dry_run: bool) -> str:
        if not await self.logged_in(page):
            raise NotLoggedIn("TikTok is logged out.")
        await check_for_human(page)
        await page.locator('input[type="file"]').first.set_input_files(video)
        box = await first(page, [page.locator('[contenteditable="true"]')], timeout=120, what="the caption box")
        post = await first(page, [page.locator('[data-e2e="post_video_button"]'), *[
            page.get_by_role("button", name=n) for n in ("Post",)]], timeout=60, what='the "Post" button')
        await enabled(post, timeout=900)          # the upload has finished
        await write(page, box, self.fit(caption))
        await check_for_human(page)
        if dry_run:
            return ""
        await post.click()
        # TikTok sometimes asks to confirm, e.g. "Continue to post?".
        for name in ("Post now", "Continue", "Post anyway"):
            try:
                await click(page, name, timeout=4)
            except Exception:  # noqa: BLE001
                pass
        ok = await wait_text(page, r"uploaded|published|manage (?:your )?posts|your video (?:is|has been)", timeout=240)
        await check_for_human(page)
        if not ok:
            raise RuntimeError("TikTok did not confirm the post.")
        return ""
