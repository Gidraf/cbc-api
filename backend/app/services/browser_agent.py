from __future__ import annotations

from playwright.async_api import async_playwright

from ..settings import settings


async def browse_page(url: str) -> dict:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(settings.playwright_cdp_url)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(url, wait_until="domcontentloaded")
        title = await page.title()
        h1 = await page.locator("h1").first.text_content()
        screenshot = await page.screenshot(type="png")
        await context.close()
        await browser.close()

    return {
        "url": url,
        "title": title,
        "first_h1": h1,
        "screenshot_bytes": len(screenshot),
    }
