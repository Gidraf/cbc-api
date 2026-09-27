"""The Chromium every PDF and page inspection runs in.

The stack's `playwright` service (browserless, over CDP) is used when it is
configured and answers. When it is not — the container never started because
its port was taken, or PLAYWRIGHT_CDP_URL is blank — a Chromium bundled in
this image is launched instead, the way CVPAP renders its cards. A guide that
could not be downloaded because a sidecar was down is a guide nobody printed.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from ..settings import settings

logger = logging.getLogger("cbc-browser")

# Chromium in a container runs without its sandbox (there is no user namespace
# to put it in) and with /tmp instead of a 64 MB /dev/shm.
LAUNCH_ARGS = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
CONNECT_TIMEOUT_MS = 10_000


@asynccontextmanager
async def open_browser() -> AsyncIterator[Any]:
    """A connected or launched browser, closed on the way out."""
    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        browser = None
        url = (settings.playwright_cdp_url or "").strip()
        if url:
            try:
                browser = await playwright.chromium.connect_over_cdp(url, timeout=CONNECT_TIMEOUT_MS)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Browser service at %s unreachable (%s); launching the local Chromium.",
                               url, str(exc).splitlines()[0][:160])
        if browser is None:
            browser = await playwright.chromium.launch(headless=True, args=LAUNCH_ARGS)
        try:
            yield browser
        finally:
            await browser.close()
