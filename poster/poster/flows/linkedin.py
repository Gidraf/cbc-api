"""LinkedIn: Start a post → media (a video, or a PDF as a document) → caption → Post, from the feed."""
from __future__ import annotations

import asyncio
import re

from playwright.async_api import Page

from .base import Flow, NotLoggedIn, check_for_human, click, first, write, wait_text

FEED = "https://www.linkedin.com/feed/"


class LinkedIn(Flow):
    platform = "linkedin"
    login_url = "https://www.linkedin.com/login"
    caption_limit = 2900

    async def logged_in(self, page: Page) -> bool:
        await page.goto(FEED, wait_until="domcontentloaded", timeout=60_000)
        await asyncio.sleep(3)
        if any(k in page.url for k in ("/login", "authwall", "checkpoint", "/uas/")):
            return False
        try:
            await first(page, [page.get_by_role("button", name="Start a post")], timeout=20, what='"Start a post"')
            return True
        except Exception:  # noqa: BLE001
            return False

    async def post_document(self, page: Page, *, pdf: str, caption: str, title: str, dry_run: bool) -> str:
        """A PDF as a document post — LinkedIn shows it as a swipeable carousel."""
        if not await self.logged_in(page):
            raise NotLoggedIn("LinkedIn is logged out.")
        await check_for_human(page)
        await click(page, "Start a post")
        doc = page.get_by_role("button", name=re.compile(r"add a document|document", re.I))
        if not await doc.count():
            await (await first(page, [page.get_by_role("button", name=re.compile(r"^more$", re.I)),
                                      page.locator('button[aria-label*="More" i]')], timeout=20, what='"More"')).click()
            await asyncio.sleep(1)
        await (await first(page, [page.get_by_role("button", name=re.compile(r"add a document", re.I)),
                                  page.locator('button[aria-label*="document" i]')], timeout=20, what='"Add a document"')).click()
        await asyncio.sleep(2)
        await page.locator('input[type="file"]').first.set_input_files(pdf)
        try:
            name = await first(page, [page.get_by_label(re.compile(r"document title", re.I)),
                                      page.locator('input[placeholder*="title" i]')], timeout=120, what="the document title")
            await name.fill(title[:58] or "The build, step by step")
        except Exception:  # noqa: BLE001
            pass
        await click(page, "Done", "Next", timeout=300)
        box = await first(page, [page.locator('div[role="textbox"]'), page.locator(".ql-editor")], timeout=30,
                          what="the post box")
        await write(page, box, self.fit(caption))
        await check_for_human(page)
        if dry_run:
            return ""
        await click(page, "Post", timeout=300)
        if not await wait_text(page, r"post successful|your post (?:was|has been) shared|view post", timeout=600):
            raise RuntimeError("LinkedIn did not confirm the post.")
        return ""

    async def post(self, page: Page, *, video: str, caption: str, title: str, dry_run: bool) -> str:
        if not await self.logged_in(page):
            raise NotLoggedIn("LinkedIn is logged out.")
        await check_for_human(page)
        await click(page, "Start a post")
        await (await first(page, [page.get_by_role("button", name="Add media"), page.get_by_role("button", name="Add a video"),
                                  page.locator('button[aria-label*="media" i]')], timeout=20, what='"Add media"')).click()
        await page.locator('input[type="file"]').first.set_input_files(video)
        await click(page, "Next", timeout=300)
        box = await first(page, [page.locator('div[role="textbox"]'), page.locator(".ql-editor")], timeout=30,
                          what="the post box")
        await write(page, box, self.fit(caption))
        await check_for_human(page)
        if dry_run:
            return ""
        await click(page, "Post", timeout=300)
        ok = await wait_text(page, r"post successful|your post (?:was|has been) shared|view post", timeout=600)
        await check_for_human(page)
        if not ok:
            raise RuntimeError("LinkedIn did not confirm the post.")
        link = ""
        try:
            anchor = await first(page, [page.get_by_role("link", name="View post")], timeout=5)
            link = await anchor.get_attribute("href") or ""
        except Exception:  # noqa: BLE001
            pass
        return link
