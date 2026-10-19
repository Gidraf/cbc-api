"""Reading the profile once, deep: every post on it with its link and its words.

Posts the server has no link for — reels handed to Facebook's scheduler, posts
whose first comment never found them — are matched by their words on the
server (the question's opening, middle or end). Here the profile is scrolled
a screen at a time; each post's text is read with its captions unfolded, and
its link is the one under its time stamp (a /reel/, /videos/ or /posts/
address). It stops when the profile ends or nothing new shows for a while.
"""
from __future__ import annotations

import asyncio
import re

from playwright.async_api import Page

from .base import NotLoggedIn, check_for_human, shot, yield_point
from .fb_comments import _EXPAND, PROFILE

# Every post in view: the block around each comment button that holds only
# that post, its words, and its own link.
_HARVEST = r"""() => {
  const ACTION = '[aria-label="Leave a comment"], [aria-label="Comment"]';
  const LINK = /facebook\.com\/(?:[^/?#]+\/)?(?:reel|videos|posts|permalink\.php|story\.php|watch)/;
  const out = [];
  for (const a of document.querySelectorAll(ACTION)) {
    let el = a.parentElement, post = null;
    for (let depth = 0; el && depth < 30; depth++, el = el.parentElement) {
      const n = el.querySelectorAll(ACTION).length;
      if (n > 2) break;
      if ((el.innerText || '').length > 60) post = el;
    }
    if (!post) continue;
    const links = [...post.querySelectorAll('a[href]')].map(x => x.href).filter(h => LINK.test(h));
    if (!links.length) continue;
    out.push({ url: links[0], text: (post.innerText || '').slice(0, 2500) });
  }
  return out;
}"""


def clean(url: str) -> str:
    """A post's address without the tracking: /reel/123, /videos/123, /posts/pfbid…, or a permalink's ids."""
    m = re.search(r"(https://(?:www|m|web)\.facebook\.com/(?:[^/?#]+/)?(?:reel|videos|posts)/[^/?#]+)", url)
    if m:
        return m.group(1).replace("://m.", "://www.").replace("://web.", "://www.") + "/"
    m = re.search(r"(https://[^/]*facebook\.com/(?:permalink|story)\.php)\?(.*)", url)
    if m:
        keep = "&".join(p for p in m.group(2).split("&") if p.split("=")[0] in ("story_fbid", "id"))
        return f"{m.group(1)}?{keep}"
    return url.split("?")[0]


async def harvest(page: Page, *, scrolls: int = 160) -> dict:
    await page.goto(PROFILE, wait_until="domcontentloaded", timeout=60_000)
    await asyncio.sleep(6)
    if re.search(r"/login|checkpoint", page.url) or await page.locator('input[name="pass"]').count():
        raise NotLoggedIn("Facebook is logged out.")
    await check_for_human(page)
    found: dict[str, str] = {}
    quiet = 0
    for _ in range(scrolls):
        yield_point()                                  # a command from the console comes first
        await page.evaluate(_EXPAND)
        await asyncio.sleep(0.8)
        before = len(found)
        for item in await page.evaluate(_HARVEST):
            url = clean(str(item.get("url") or ""))
            if url and len(item.get("text") or "") > len(found.get(url, "")):
                found[url] = item["text"]
        quiet = quiet + 1 if len(found) == before else 0
        if quiet >= 10:                                # the end of the profile, or nothing new for a while
            break
        await page.mouse.wheel(0, 1600)
        await asyncio.sleep(2.2)
    return {"items": [{"url": u, "text": t} for u, t in found.items()], "shot": await shot(page, "facebook-reconcile")}
