"""Boosting one of the owner's Facebook posts — only when the owner pressed
Boost in the console, with the budget they chose.

The post is found on the profile by its words (as the comment thread finds
it); its "Boost post" button opens Facebook's own form. The days and the
budget are typed in, and before anything is confirmed the form's own total
must read the amount asked for (daily × days, in shillings). If any of it
cannot be set or read back, nothing is confirmed: the form is left as it is,
with a screenshot, and the console says why. Facebook charges the payment
method the owner set up in their ads account.
"""
from __future__ import annotations

import asyncio
import re

from playwright.async_api import Locator, Page

from .base import StepFailed, check_for_human, first, shot
from .fb_comments import find_post


def _amounts(text: str) -> set[int]:
    """Every shilling amount the text shows: KSh 1,000 · KES 1,000.00 · 1 000 KSh."""
    out = set()
    for m in re.finditer(r"(?:KSh|KES|Ksh|ksh)\s*([0-9][0-9,\s]*(?:\.[0-9]{2})?)|([0-9][0-9,\s]*(?:\.[0-9]{2})?)\s*(?:KSh|KES)", text):
        raw = (m.group(1) or m.group(2) or "").replace(",", "").replace(" ", "").split(".")[0]
        if raw.isdigit():
            out.add(int(raw))
    return out


async def _fill(field: Locator, value: str) -> None:
    await field.click()
    await field.press("ControlOrMeta+A")
    await field.press("Backspace")
    await field.type(value, delay=60)
    await field.press("Tab")
    await asyncio.sleep(1.2)


async def boost(page: Page, *, find: str, also: list[str] | None, daily_ksh: int, days: int) -> dict:
    total = daily_ksh * days
    post = await find_post(page, find, "", also=also)
    button = post.get_by_role("button", name=re.compile(r"^boost( post)?$", re.I))
    if not await button.count():
        button = post.get_by_text(re.compile(r"^Boost( post)?$", re.I))
    if not await button.count():
        raise StepFailed('No "Boost post" button on this post — boosting needs professional mode or a Page.')
    await button.first.click()
    await asyncio.sleep(6)
    await check_for_human(page)
    form = page.get_by_role("dialog").last if await page.get_by_role("dialog").count() else page.locator("body")

    # Duration, in days.
    dur = await first(page, [form.get_by_label(re.compile(r"^(duration|days)$", re.I)),
                             form.locator('input[aria-label*="Duration" i], input[aria-label*="days" i]')],
                      timeout=30, what="the duration")
    await _fill(dur, str(days))
    # The budget: a daily one if the form has it, else the total.
    daily = form.get_by_label(re.compile(r"daily budget", re.I))
    if await daily.count():
        await _fill(daily.first, str(daily_ksh))
    else:
        budget = await first(page, [form.get_by_label(re.compile(r"(total )?budget", re.I)),
                                    form.locator('input[aria-label*="budget" i]')], timeout=20, what="the budget")
        await _fill(budget, str(total))
    await asyncio.sleep(2)
    shown = _amounts(await form.inner_text(timeout=10_000))
    if total not in shown:
        name = await shot(page, "facebook-boost-check")
        raise StepFailed(f"Facebook's form does not show KSh {total:,} (it shows {sorted(shown)[:6] or 'no amount'}) "
                         f"— not boosted. See {name}.")
    go = await first(page, [form.get_by_role("button", name=re.compile(r"^(boost post now|boost now|boost post|boost)$", re.I))],
                     timeout=20, what='"Boost post now"')
    await go.click()
    await asyncio.sleep(8)
    await check_for_human(page)
    text = (await page.locator("body").inner_text(timeout=10_000)).lower()
    if not re.search(r"in review|being reviewed|boosted|your ad|is now active|submitted", text):
        # It may have gone through: never treated as a failure that invites a second press.
        return {"unsure": True, "total_ksh": total, "shot": await shot(page, "facebook-boost-unsure")}
    return {"total_ksh": total, "shot": await shot(page, "facebook-boost-done")}
