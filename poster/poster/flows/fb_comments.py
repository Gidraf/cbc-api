"""Comments under a Facebook post: the choices, "can you solve it?", then the
answer and its working (with the answer card).

The post is found again on the profile by the question's opening words — a
reel scheduled weeks ago has no link the poster kept — scrolling the feed a
little at a time. Its comment box is the post's own, or the one in the post's
window if pressing "Comment" opens it there. Each comment is typed with its
line breaks (Shift+Enter) and sent with Enter, then looked for under the post
before the next one goes.

`check` does all of it except sending: it finds the post and its comment box,
and leaves a screenshot.
"""
from __future__ import annotations

import asyncio
import re
import unicodedata

from playwright.async_api import Locator, Page

from .base import NotLoggedIn, StepFailed, check_for_human, shot

PROFILE = "https://www.facebook.com/me"


def _norm(text: str) -> str:
    """Letters and digits only, lower case: a caption as Facebook shows it
    (emoji, "See more", line breaks) still matches the words we sent."""
    text = unicodedata.normalize("NFKD", text or "").lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


# Each article: is it a post (not a comment inside one), and its text.
_ALL_ARTICLES = """els => els.map(a => [!a.parentElement.closest('[role=article]'), (a.innerText || '').slice(0, 1500)])"""


# Mark the post holding any of the words: the nearest block around them that
# has its own comment button (Facebook does not always call posts "articles").
_MARK = r"""needles => {
  const norm = s => (s || '').normalize('NFKD').toLowerCase().replace(/[^a-z0-9]+/g, ' ').replace(/\s+/g, ' ').trim();
  document.querySelectorAll('[data-cbc-post]').forEach(e => e.removeAttribute('data-cbc-post'));
  const ACTION = '[aria-label="Leave a comment"], [aria-label="Comment"], [aria-label^="Comment as"], [contenteditable="true"][role="textbox"]';
  for (const a of document.querySelectorAll(ACTION)) {
    let el = a.parentElement;
    for (let depth = 0; el && depth < 30; depth++, el = el.parentElement) {
      if (!needles.some(n => n && norm(el.innerText).includes(n))) continue;
      const actions = el.querySelectorAll('[aria-label="Leave a comment"], [aria-label="Comment"]').length;
      if (actions <= 2) { el.setAttribute('data-cbc-post', '1'); return true; }
      break;                                   // reached a block holding several posts: not this one
    }
  }
  return false;
}"""

# Open the captions Facebook folds behind "See more" / "…more".
_EXPAND = r"""() => {
  let n = 0;
  for (const b of document.querySelectorAll('[role=button], span, div')) {
    const t = (b.innerText || '').trim();
    if ((t === 'See more' || t === 'more' || t === '… more' || t === '...more') && b.offsetParent && n < 25) {
      try { b.click(); n++; } catch (e) {}
    }
  }
  return n;
}"""

_DOM = r"""() => ({
  url: location.href,
  articles: document.querySelectorAll('[role=article]').length,
  posinset: document.querySelectorAll('[aria-posinset]').length,
  comment_buttons: document.querySelectorAll('[aria-label="Leave a comment"], [aria-label="Comment"]').length,
  boxes: [...document.querySelectorAll('[contenteditable="true"][role="textbox"]')].map(b => b.getAttribute('aria-label')).slice(0, 5),
  samples: [...document.querySelectorAll('[role=article], [aria-posinset]')].slice(0, 6).map(a => (a.innerText || '').slice(0, 240)),
})"""


def needles(find: str, also: list[str] | None = None) -> list[str]:
    """What to look for: the question's opening words (and the context's), long enough to be its own."""
    out = []
    for text in [find, *(also or [])]:
        n = _norm(text)
        if len(n) >= 14:
            out.append(n[:40])
    return list(dict.fromkeys(out))


async def find_post(page: Page, find: str, url: str = "", scrolls: int = 40, also: list[str] | None = None) -> Locator:
    """The post (on the profile, or the post page), by its words."""
    if url:
        await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        await asyncio.sleep(5)
        dialog = page.get_by_role("dialog")
        if await dialog.count():
            return dialog.last
        return page.locator("[role=main]").first
    await page.goto(PROFILE, wait_until="domcontentloaded", timeout=60_000)
    await asyncio.sleep(6)
    if re.search(r"/login|checkpoint", page.url) or await page.locator('input[name="pass"]').count():
        raise NotLoggedIn("Facebook is logged out.")
    await check_for_human(page)
    want = needles(find, also)
    if not want:
        raise StepFailed("The question is too short to find its post by.")
    for _ in range(scrolls):
        await page.evaluate(_EXPAND)
        await asyncio.sleep(0.8)
        if await page.evaluate(_MARK, want):
            post = page.locator('[data-cbc-post="1"]').first
            await post.scroll_into_view_if_needed()
            return post
        await page.mouse.wheel(0, 1600)
        await asyncio.sleep(2.5)
    await _dump(page, want)
    raise StepFailed("Could not find the post on the profile — it may not be out yet.")


async def _dump(page: Page, want: list[str]) -> None:
    """What the page looked like when the post was not found — for fixing the steps."""
    import json
    import os
    import time

    from .. import config

    try:
        info = await page.evaluate(_DOM)
        info["looked_for"] = want
        os.makedirs(config.SHOTS_DIR, exist_ok=True)
        with open(os.path.join(config.SHOTS_DIR, f"facebook-comments-dom-{int(time.time())}.json"), "w") as fh:
            json.dump(info, fh, indent=1)
    except Exception:  # noqa: BLE001
        pass


async def comment_box(page: Page, post: Locator) -> Locator:
    """The post's comment box: in the post, or in the window "Comment" opens."""
    box_sel = '[contenteditable="true"][role="textbox"]'
    box = post.locator(box_sel)
    if await box.count() and await box.last.is_visible():
        return box.last
    button = post.get_by_role("button", name=re.compile(r"^(Comment|Leave a comment|Write a comment)", re.I))
    if not await button.count():
        button = post.locator('[aria-label*="omment" i][role="button"]')
    if not await button.count():
        raise StepFailed('No "Comment" button on the post.')
    await button.first.click()
    await asyncio.sleep(3)
    for scope in (post, page.get_by_role("dialog").last, page):
        found = scope.locator(box_sel)
        if await found.count():
            for n in range(await found.count() - 1, -1, -1):
                el = found.nth(n)
                label = (await el.get_attribute("aria-label") or "") + (await el.get_attribute("aria-placeholder") or "")
                if await el.is_visible() and (not label or re.search(r"comment|answer", label, re.I)):
                    return el
    raise StepFailed("The comment box did not open.")


async def _type(page: Page, box: Locator, text: str) -> None:
    await box.click()
    lines = text.split("\n")
    for k, line in enumerate(lines):
        if line:
            await page.keyboard.insert_text(line)
        if k < len(lines) - 1:
            await page.keyboard.press("Shift+Enter")
    await asyncio.sleep(0.6)


async def _attach(box: Locator, image: str) -> bool:
    """The answer card on the comment: the composer's own photo input."""
    for up in range(1, 8):
        holder = box.locator(f"xpath=ancestor::*[{up}]")
        files = holder.locator('input[type="file"]')
        if await files.count():
            await files.first.set_input_files(image)
            await asyncio.sleep(4)
            return True
    return False


async def _landed(page: Page, post: Locator, text: str, timeout: float = 20.0) -> bool:
    """The comment shows under the post (Facebook cleared the box and drew it)."""
    want = _norm(text.split("\n")[0])[:40]
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        try:
            scope = post if await post.count() else page.locator("body")
            if want and want in _norm(await scope.inner_text(timeout=5_000)):
                return True
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(1.5)
    return False


async def comment(page: Page, *, find: str, url: str, comments: list[str], image: str = "",
                  check: bool = False, also: list[str] | None = None) -> dict:
    """Find the post and comment under it, one comment after the other."""
    post = await find_post(page, find, url, also=also)
    box = await comment_box(page, post)
    if check:
        await box.click()
        return {"found": True, "shot": await shot(page, "facebook-comments-check")}
    for k, text in enumerate(comments):
        box = await comment_box(page, post)
        await _type(page, box, text)
        if image and k == len(comments) - 1:
            if not await _attach(box, image):
                pass        # no photo input: the text still goes
        await page.keyboard.press("Enter")
        if not await _landed(page, post, text):
            raise StepFailed(f"Comment {k + 1} did not show under the post.")
        await asyncio.sleep(4)
    permalink = ""
    try:
        link = post.locator('a[href*="/posts/"], a[href*="/reel/"], a[href*="/videos/"]').first
        if await link.count():
            permalink = (await link.get_attribute("href") or "").split("?")[0]
    except Exception:  # noqa: BLE001
        pass
    return {"found": True, "url": permalink, "shot": await shot(page, "facebook-comments")}
