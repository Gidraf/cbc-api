"""Liking back on Facebook: the comments under the owner's posts, then a few
of each commenter's own recent posts. Likes only — it never comments on
anyone else's post.

`scan` opens one of the owner's posts (found by its words, as the comment
thread finds it), opens more of its comments, likes each one not yet liked
and returns who wrote them. `like_person` opens a person's profile and likes
their newest posts. Every like waits a few seconds, like a person reading.
"""
from __future__ import annotations

import asyncio
import random
import re

from playwright.async_api import Locator, Page

from .base import NotLoggedIn, check_for_human, shot, yield_point
from .fb_comments import find_post

LIKE = re.compile(r"^Like$", re.I)


async def _pause(lo: float = 4.0, hi: float = 9.0) -> None:
    await asyncio.sleep(random.uniform(lo, hi))


async def _more_comments(page: Page, post: Locator, rounds: int = 4) -> None:
    for _ in range(rounds):
        more = post.get_by_role("button", name=re.compile(r"(view|see) (more|previous|all) comments|more replies", re.I))
        if not await more.count():
            more = post.get_by_text(re.compile(r"^(View|See) (more|previous|all) comments", re.I))
        if not await more.count():
            return
        try:
            await more.first.click()
        except Exception:  # noqa: BLE001
            return
        await asyncio.sleep(2.5)


_COMMENTS = """post => {
  const own = (post.querySelector('h2 a, h3 a, strong a') || {}).href || '';
  const out = [];
  post.querySelectorAll('[role=article]').forEach((c, k) => {
    const link = [...c.querySelectorAll('a[href]')].find(a => a.innerText.trim() && /facebook\\.com\\//.test(a.href));
    if (!link) return;
    out.push({ k, name: link.innerText.trim().slice(0, 120), url: link.href, own: !!own && link.href.split('?')[0] === own.split('?')[0] });
  });
  return out;
}"""


async def scan(page: Page, *, find: str, url: str, count: int, also: list[str] | None = None) -> dict:
    """Like the comments under one of the owner's posts; return who wrote them."""
    post = await find_post(page, find, url, also=also)
    await _more_comments(page, post)
    comments = await post.evaluate(_COMMENTS)
    people, liked = [], 0
    articles = post.locator("[role=article]")
    for c in comments:
        if c["own"]:
            continue                                   # the owner's own comments (the thread)
        people.append({"name": c["name"], "url": c["url"]})
        if liked >= count:
            continue
        like = articles.nth(c["k"]).get_by_role("button", name=LIKE)
        try:
            if await like.count() and await like.first.is_visible():
                await like.first.click()
                liked += 1
                await _pause(3, 7)
        except Exception:  # noqa: BLE001
            continue
    seen = {}
    for p in people:                                    # one entry per person
        seen.setdefault(p["url"].split("&")[0], p)
    return {"likes": liked, "people": list(seen.values()), "shot": await shot(page, "facebook-engage-scan")}


async def like_person(page: Page, *, url: str, count: int) -> dict:
    """Like a person's newest posts on their profile."""
    await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    await asyncio.sleep(6)
    if re.search(r"/login|checkpoint", page.url) or await page.locator('input[name="pass"]').count():
        raise NotLoggedIn("Facebook is logged out.")
    await check_for_human(page)
    liked, scrolls = 0, 0
    while liked < count and scrolls < 6:
        yield_point()
        posts = page.locator("[role=article]")
        for n in range(await posts.count()):
            if liked >= count:
                break
            post = posts.nth(n)
            try:
                if not await post.evaluate("a => !a.parentElement.closest('[role=article]')"):
                    continue                            # a comment, not a post
                like = post.get_by_role("button", name=LIKE)
                if await like.count() and await like.first.is_visible() and (await like.first.get_attribute("aria-pressed")) != "true":
                    await like.first.click()
                    liked += 1
                    await _pause()
            except Exception:  # noqa: BLE001
                continue
        await page.mouse.wheel(0, 1400)
        await asyncio.sleep(2.5)
        scrolls += 1
    return {"likes": liked, "shot": await shot(page, "facebook-engage-like")}
