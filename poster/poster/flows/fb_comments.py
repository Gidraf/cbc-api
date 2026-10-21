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

from .base import NotLoggedIn, StepFailed, check_for_human, shot, yield_point

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


def post_page(url: str) -> str:
    """The page to open a post on: a reel as a video page — the reel's own
    player does not open its comments (or its numbers) for the poster; the
    video page has them beside it, with the comment box."""
    m = re.search(r"facebook\.com/(?:[^/?#]+/)?reel/(\d+)", url)
    return f"https://www.facebook.com/watch/?v={m.group(1)}" if m else url


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
        await page.goto(post_page(url), wait_until="domcontentloaded", timeout=60_000)
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
        yield_point()                                  # a command from the console comes first
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


_LINK_DOM = r"""() => ({
  url: location.href,
  dialogs: document.querySelectorAll('[role=dialog]').length,
  buttons: [...document.querySelectorAll('[role=button][aria-label], button[aria-label]')].map(b => b.getAttribute('aria-label')).filter(Boolean).slice(0, 80),
  boxes: [...document.querySelectorAll('[contenteditable="true"]')].map(b => [b.getAttribute('role'), b.getAttribute('aria-label'), b.getAttribute('aria-placeholder'), b.offsetParent !== null]),
  texts: [...document.querySelectorAll('span, div')].map(e => (e.childElementCount === 0 ? (e.innerText || '').trim() : '')).filter(t => /comment/i.test(t)).slice(0, 30),
})"""


async def open_post(page: Page, find: str, url: str = "", *, also: list[str] | None = None,
                    need_box: bool = True) -> tuple[Locator, Locator | None]:
    """The post, and (when needed) its comment box: by its link first — any
    post, however old — else, or if its page will not give a comment box, by
    its words on the profile."""
    if url:
        try:
            post = await find_post(page, find, url)
            if re.search(r"/login|checkpoint", page.url):
                raise NotLoggedIn("Facebook is logged out.")
            return post, (await comment_box(page, post) if need_box else None)
        except NotLoggedIn:
            raise
        except Exception as exc:  # noqa: BLE001
            import json
            import logging
            import os

            from .. import config

            try:                      # what the post's page showed: for fixing the steps
                info = await page.evaluate(_LINK_DOM)
                name = await shot(page, "facebook-link-nobox")
                with open(os.path.join(config.SHOTS_DIR, name.replace(".png", ".json")), "w") as fh:
                    json.dump(info, fh, indent=1)
            except Exception:  # noqa: BLE001
                pass
            logging.getLogger("poster").info("Its link gave no comment box (%s); looking on the profile.", exc)
    return await find_post(page, find, "", also=also), None


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


_PREVIEW = 'img[src^="blob:"], [aria-label*="Remove" i][role="button"]'


async def _attach(page: Page, box: Locator, image: str) -> bool:
    """The answer card on the comment. The composer's photo input is a few
    levels up from the box — or, where Facebook hides it, behind its "Attach
    a photo or video" button. True once the photo's preview shows."""
    before = await page.locator(_PREVIEW).count()

    async def previewed(wait: int = 20) -> bool:
        for _ in range(wait):
            if await page.locator(_PREVIEW).count() > before:
                await asyncio.sleep(1.5)
                return True
            await asyncio.sleep(1)
        return False

    for up in range(1, 16):                       # the nearest input wins: never another comment's
        files = box.locator(f"xpath=ancestor::*[{up}]").locator('input[type="file"]')
        if await files.count():
            try:
                await files.first.set_input_files(image)
                if await previewed():
                    return True
            except Exception:  # noqa: BLE001
                pass
            break
    for up in range(1, 16):
        button = box.locator(f"xpath=ancestor::*[{up}]").locator(
            '[aria-label*="photo" i][role="button"], [aria-label*="Attach" i][role="button"]')
        if await button.count():
            try:
                async with page.expect_file_chooser(timeout=8_000) as chooser:
                    await button.first.click()
                await (await chooser.value).set_files(image)
                return await previewed()
            except Exception:  # noqa: BLE001
                return False
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


def number(text: str) -> int:
    """'1.2K' → 1200, '3,456' → 3456, '2M' → 2000000."""
    m = re.match(r"\s*([\d.,]+)\s*([KkMm]?)", text or "")
    if not m:
        return 0
    raw = m.group(1).replace(",", "")
    try:
        val = float(raw)
    except ValueError:
        return 0
    return int(val * {"k": 1_000, "m": 1_000_000}.get(m.group(2).lower(), 1))


_LABELS = {"views": r"^(views|plays|video views|reel plays)$", "viewers": r"^(viewers|reach|accounts reached)$",
           "reactions": r"^(reactions|likes|post reactions)$", "comments": r"^comments$", "shares": r"^shares$",
           "saves": r"^saves$"}


def parse_insights(text: str) -> dict[str, int]:
    """Numbers beside their labels, as an insights window lists them (label, then number — or number, then label)."""
    lines = [x.strip().strip("\ufeff") for x in (text or "").splitlines() if x.strip().strip("\ufeff")]
    out: dict[str, int] = {}
    # Facebook's "Post insights" page puts the number under the label up top
    # (Views / 22) but above it in the Engagement section (0 / Reactions).
    engaged = next((k for k, x in enumerate(lines) if re.match(r"^[\d.,]+[KkMm]?\s*Engagement$", x)), None)
    for k, line in enumerate(lines):
        for key, rx in _LABELS.items():
            if key in out or not re.match(rx, line, re.I):
                continue
            below, above = (lines[k + 1] if k + 1 < len(lines) else ""), (lines[k - 1] if k else "")
            order = (above, below) if engaged is not None and k > engaged else (below, above)
            for near in order:
                if re.match(r"^[\d.,]+\s*[KkMm]?$", near):
                    out[key] = number(near)
                    break
    m = re.search(r"([\d.,]+[KkMm]?)\s+Engagement", text or "")
    if m:
        out["engagement"] = number(m.group(1))
    for key, rx in (("comments", r"([\d.,]+[KkMm]?)\s+comments?"), ("shares", r"([\d.,]+[KkMm]?)\s+shares?"),
                    ("views", r"([\d.,]+[KkMm]?)\s+(?:views|plays)"), ("reactions", r"([\d.,]+[KkMm]?)\s+reactions?")):
        if key not in out:
            m = re.search(rx, text or "", re.I)
            if m:
                out[key] = number(m.group(1))
    if "reactions" not in out and "engagement" in out:      # only the total shown: the rest is reactions
        out["reactions"] = max(0, out["engagement"] - out.get("comments", 0) - out.get("shares", 0))
    return out


def _keep_text(text: str) -> None:
    """The insights page's words beside the screenshots — for reading its labels right."""
    import os
    import time

    from .. import config

    try:
        os.makedirs(config.SHOTS_DIR, exist_ok=True)
        with open(os.path.join(config.SHOTS_DIR, f"facebook-insights-{int(time.time())}.txt"), "w") as fh:
            fh.write(text[:20_000])
    except OSError:
        pass


async def read_metrics(page: Page, post: Locator) -> dict[str, int]:
    """The post's numbers. "See insights" opens a whole "Post insights" page
    on a profile (Views, Viewers, then Engagement: reactions, comments,
    shares) — or a window elsewhere; failing both, what the post shows. This
    leaves the profile, so it runs after the comments."""
    try:
        shown = parse_insights(await post.inner_text(timeout=10_000))
    except Exception:  # noqa: BLE001
        shown = {}
    try:
        link = post.get_by_text(re.compile(r"^See insights$", re.I))
        if await link.count():
            before = page.url
            await link.first.click()
            for _ in range(15):
                await asyncio.sleep(1)
                if page.url != before or await page.get_by_text(re.compile(r"^Post insights$", re.I)).count():
                    break
            await asyncio.sleep(3)                      # the numbers fill in
            dialog = page.get_by_role("dialog")
            if page.url == before and await dialog.count():
                text = await dialog.last.inner_text(timeout=10_000)
                await page.keyboard.press("Escape")
            else:
                text = await page.locator("body").inner_text(timeout=15_000)
            _keep_text(text)
            got = parse_insights(text)
            if got:
                return {**shown, **got}
    except Exception:  # noqa: BLE001
        pass
    return shown


async def comment(page: Page, *, find: str, url: str, comments: list[str], image: str = "",
                  check: bool = False, also: list[str] | None = None, measure: bool = False,
                  images: list[str] | None = None) -> dict:
    """Find the post and comment under it, one comment after the other (and
    read its numbers first, when asked). With its link, the post's own page
    (a reel's opens its comments beside it); without one — or when that page
    shows no comment box — found on the profile by its words."""
    post, box = await open_post(page, find, url, also=also, need_box=bool(comments) or check)
    if not comments and not check:
        metrics = await read_metrics(page, post) if measure else {}
        return {"found": True, "metrics": metrics, "shot": await shot(page, "facebook-insights")}
    box = box or await comment_box(page, post)
    if check:
        await box.click()
        return {"found": True, "shot": await shot(page, "facebook-comments-check")}
    attached = None
    for k, text in enumerate(comments):
        box = await comment_box(page, post)
        await _type(page, box, text)
        # Its own picture (the question card, the KICD page, the answer card),
        # or — from a server that sends one — the one picture, on the last.
        pic = (images[k] if images and k < len(images) else "") or (image if not images and k == len(comments) - 1 else "")
        if pic:
            attached = await _attach(page, box, pic)      # no photo input: the text still goes
            await box.focus()
        await page.keyboard.press("Enter")
        if not await _landed(page, post, text):
            raise StepFailed(f"Comment {k + 1} did not show under the post.")
        await asyncio.sleep(4)
    shot_name = await shot(page, "facebook-comments")
    permalink = ""
    try:
        link = post.locator('a[href*="/posts/"], a[href*="/reel/"], a[href*="/videos/"]').first
        if await link.count():
            permalink = (await link.get_attribute("href") or "").split("?")[0]
    except Exception:  # noqa: BLE001
        pass
    metrics = await read_metrics(page, post) if measure else {}    # last: it leaves the profile
    out = {"found": True, "url": permalink, "metrics": metrics, "shot": shot_name}
    if attached is not None:
        out["card"] = attached
    return out
