"""HTML to PDF, through the browser that is already in the stack.

A teacher's guide that only exists on a screen is not much use to a teacher
whose classroom has no screen in it. The console's Print button hands that job
to whatever browser the operator happens to have; a downloaded file is the same
document every time, and can be sent to somebody who is not sitting at the
console.

Chromium is already here — `browserless/chrome`, connected over CDP, used for
page inspection. Rendering to PDF is one more call to it rather than a new
dependency and a second HTML engine that disagrees with the first about page
breaks.
"""
from __future__ import annotations

import asyncio
import logging

from ..settings import settings

logger = logging.getLogger("cbc-pdf")

# A guide is tens of pages at most. Long enough for a slow render, short enough
# that a wedged browser does not hold a worker.
TIMEOUT_MS = 60_000


class PdfUnavailable(RuntimeError):
    """The browser service could not produce a PDF, and said why."""


async def _render(html: str) -> bytes:
    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(
            settings.playwright_cdp_url, timeout=TIMEOUT_MS
        )
        try:
            context = await browser.new_context()
            page = await context.new_page()
            # set_content rather than a URL: the document never leaves this
            # process, so there is nothing to serve and nothing to clean up.
            await page.set_content(html, wait_until="load")
            pdf = await page.pdf(
                format="A4",
                print_background=True,
                # The @page rule in the document owns the margins; overriding
                # them here would fight it.
                prefer_css_page_size=True,
            )
            await context.close()
            return pdf
        finally:
            await browser.close()


def from_html(html: str) -> bytes:
    """Render a complete HTML document to PDF bytes."""
    try:
        return asyncio.run(_render(html))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not render a PDF: %s", exc)
        raise PdfUnavailable(
            f"The browser service could not render this to PDF ({exc}). "
            f"Check that the `playwright` container is running and reachable "
            f"at {settings.playwright_cdp_url}. In the meantime the guide can "
            f"be printed from the reader, and saved as PDF from the print "
            f"dialog."
        ) from exc
