"""One real browser, kept open, with the profile the owner logged into.

A persistent profile keeps each platform's session between runs and
restarts. The browser is shown on the shared screen (not headless) so the
owner can log in, answer a "is this you?" check, and watch a post go out.
Nothing here disguises the browser.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from playwright.async_api import BrowserContext, Page, async_playwright

from . import config

log = logging.getLogger("poster.browser")


class Browser:
    def __init__(self) -> None:
        self._pw: Any = None
        self._ctx: BrowserContext | None = None
        self.channel = ""
        self.lock = asyncio.Lock()   # one action in the browser at a time

    async def context(self) -> BrowserContext:
        if self._ctx is not None:
            return self._ctx
        self._pw = await async_playwright().start()
        options = dict(user_data_dir=config.PROFILE_DIR, headless=False, viewport=None, locale="en-US",
                       timezone_id="Africa/Nairobi", args=["--start-maximized", "--no-first-run",
                                                           "--no-default-browser-check", "--disable-dev-shm-usage"])
        try:
            self._ctx = await self._pw.chromium.launch_persistent_context(channel=config.BROWSER_CHANNEL, **options)
            self.channel = config.BROWSER_CHANNEL
        except Exception as exc:  # noqa: BLE001
            log.info("No %s here (%s); using Chromium.", config.BROWSER_CHANNEL, str(exc).splitlines()[0][:120])
            self._ctx = await self._pw.chromium.launch_persistent_context(**options)
            self.channel = "chromium"
        self._ctx.on("close", lambda *_: setattr(self, "_ctx", None))
        return self._ctx

    async def page(self, url: str | None = None) -> Page:
        ctx = await self.context()
        page = await ctx.new_page()
        if url:
            await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        await page.bring_to_front()
        return page


browser = Browser()
