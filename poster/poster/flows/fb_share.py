"""Sharing one of the owner's posts that is out to their groups — the comment
campaign's daily share for a post that is doing well.

The post is found on the profile by its words (as the comment thread finds
it); its Share button opens Facebook's share sheet; "Share to a group" (or
"Group") opens the group picker, where each ticked group is found by its name
and the share is posted. A group not in the picker is skipped, never guessed
at. At most three groups a share, a pause between each, like a person.
"""
from __future__ import annotations

import asyncio
import random
import re

from playwright.async_api import Page

from .base import StepFailed, check_for_human, first, shot
from .fb_comments import find_post


async def share_post(page: Page, *, find: str, also: list[str] | None, groups: list[str], url: str = "") -> dict:
    shared: list[str] = []
    for name in groups[:3]:
        post = None
        if url:                   # its own page first: an older post is far down the profile
            try:
                post = await find_post(page, find, url)
                if not await post.locator('[aria-label*="Share" i][role="button"], [aria-label*="Send this" i]').count():
                    post = None
            except Exception:  # noqa: BLE001
                post = None
        post = post or await find_post(page, find, "", also=also)
        button = post.get_by_role("button", name=re.compile(r"^(Send this to friends or post it on your profile\.|Share)$", re.I))
        if not await button.count():
            button = post.locator('[aria-label*="Share" i][role="button"]')
        if not await button.count():
            raise StepFailed('No "Share" button on the post.')
        await button.first.click()
        await asyncio.sleep(2.5)
        await check_for_human(page)
        try:
            target = await first(page, [page.get_by_role("button", name=re.compile(r"share to a group", re.I)),
                                        page.get_by_text(re.compile(r"^share to a group$", re.I)),
                                        page.get_by_role("button", name=re.compile(r"^group$", re.I)),
                                        page.get_by_text(re.compile(r"^group$", re.I))], timeout=15, what='"Share to a group"')
            await target.click()
            await asyncio.sleep(2)
            search = page.locator('input[placeholder*="Search" i], input[aria-label*="Search" i]').last
            if await search.count():
                await search.fill(name)
                await asyncio.sleep(2)
            option = page.get_by_text(name, exact=True).last
            if not await option.count():
                await page.keyboard.press("Escape")
                continue                                   # not in the picker: skipped, never guessed
            await option.click()
            await asyncio.sleep(2)
            post_btn = await first(page, [page.get_by_role("button", name=re.compile(r"^post$", re.I)),
                                          page.get_by_role("button", name=re.compile(r"^share$", re.I))],
                                   timeout=20, what='"Post"')
            await post_btn.click()
            await asyncio.sleep(4)
            shared.append(name)
        except StepFailed:
            await page.keyboard.press("Escape")
            raise
        await asyncio.sleep(random.uniform(20, 45))
    if not shared:
        raise StepFailed("None of the ticked groups were in the share picker.")
    return {"groups": shared, "shot": await shot(page, "facebook-share")}
