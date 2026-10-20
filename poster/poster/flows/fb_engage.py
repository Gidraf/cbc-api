"""Liking back on Facebook: the comments under the owner's posts, then a few
of each commenter's own recent posts — and, under the owner's own posts, a
reply to the people who commented (correct, close, or thanks for joining in).
It never comments on anyone else's post.

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
    out.push({ k, name: link.innerText.trim().slice(0, 120), url: link.href, own: !!own && link.href.split('?')[0] === own.split('?')[0],
               text: (c.innerText || '').slice(0, 400), reply: !!c.parentElement.closest('[role=article]') });
  });
  return out;
}"""


def _said(text: str, name: str) -> str:
    """A comment's own words: its writer's name and Facebook's "Like · Reply · 2h" taken off."""
    t = (text or "").replace(name, "", 1)
    t = re.sub(r"\b(Like|Reply|Share|Edited|Author|Top fan|See translation)\b|\b\d+\s*[smhdwy]\b", " ", t)
    return " ".join(t.split())


def kind_of(words: str, letter: str, answer: str) -> str:
    """correct · close · other: a reply that fits what they wrote."""
    low = words.lower()
    norm = lambda x: " ".join(re.sub(r"[^a-z0-9.]+", " ", x.lower()).split())  # noqa: E731
    picked = re.search(r"(?:^|answer\s*(?:is)?\s*[:\-]?\s*|\()\s*([a-d])\s*(?:\)|\.|$|\s)", low)
    if letter and picked and picked.group(1).upper() == letter.upper():
        return "correct"
    if answer and len(norm(answer)) >= 1 and re.search(rf"(?<![0-9a-z]){re.escape(norm(answer))}(?![0-9a-z])", norm(words)):
        return "correct"
    if picked or re.search(r"\d", low):
        return "close"
    return "other"


async def _reply(page: Page, article: Locator, text: str) -> bool:
    button = article.get_by_role("button", name=re.compile(r"^Reply$", re.I))
    if not await button.count():
        button = article.get_by_text(re.compile(r"^Reply$", re.I))
    if not await button.count():
        return False
    await button.first.click()
    await asyncio.sleep(2)
    box = page.locator('[contenteditable="true"][role="textbox"]:focus')
    if not await box.count():
        return False
    await page.keyboard.insert_text(text)
    await asyncio.sleep(0.8)
    await page.keyboard.press("Enter")
    await asyncio.sleep(3)
    return True


async def scan(page: Page, *, find: str, url: str, count: int, also: list[str] | None = None,
               reply: dict | None = None) -> dict:
    """Like the comments under one of the owner's posts (and reply to a few);
    return who wrote them and which comments were replied to."""
    import hashlib

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
    replied: list[str] = []
    if reply and int(reply.get("max") or 0) > 0:
        skip = set(reply.get("skip") or [])
        say = reply.get("say") or {}
        for c in comments:
            if len(replied) >= int(reply["max"]):
                break
            if c["own"] or c.get("reply"):
                continue                               # the owner's comments, and replies inside a thread
            words = _said(c.get("text") or "", c["name"])
            key = hashlib.sha1(f"{c['name']}|{words[:80]}".encode()).hexdigest()[:16]
            if key in skip or not words:
                continue
            first = (c["name"].split() or ["there"])[0]
            text = str(say.get(kind_of(words, str(reply.get("letter") or ""), str(reply.get("answer") or ""))) or "")
            if not text:
                continue
            try:
                if await _reply(page, articles.nth(c["k"]), text.replace("{name}", first)):
                    replied.append(key)
                    skip.add(key)
                    await _pause(6, 14)
            except Exception:  # noqa: BLE001
                continue
    seen = {}
    for p in people:                                    # one entry per person
        seen.setdefault(p["url"].split("&")[0], p)
    return {"likes": liked, "people": list(seen.values()), "replied": replied, "shot": await shot(page, "facebook-engage-scan")}


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
