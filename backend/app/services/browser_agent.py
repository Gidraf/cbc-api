from __future__ import annotations

from .browser import open_browser


async def browse_page(url: str) -> dict:
    async with open_browser() as browser:
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(url, wait_until="domcontentloaded")
        title = await page.title()
        h1 = await page.locator("h1").first.text_content()
        screenshot = await page.screenshot(type="png")
        await context.close()

    return {
        "url": url,
        "title": title,
        "first_h1": h1,
        "screenshot_bytes": len(screenshot),
    }
