"""Groups on Facebook: finding them by a keyword, and joining one.

`search` opens Facebook's group search for a keyword, scrolls a few screens
and reads each result: its name, its link, its members ("12K members"), public
or private, and whether the owner is in it already. `join` opens a group and
presses "Join group": joined at once (a public group), "requested" (an admin
approves), or — when Facebook asks membership questions — the questions are
closed unanswered and the group is left for the owner: answers are never made
up on the owner's behalf.
"""
from __future__ import annotations

import asyncio
import random
import re
from urllib.parse import quote

from playwright.async_api import Page

from .base import NotLoggedIn, check_for_human, shot, yield_point

_RESULTS = r"""() => {
  const out = [], seen = new Set();
  for (const a of document.querySelectorAll('a[href*="/groups/"]')) {
    const m = a.href.match(/https:\/\/[^/]*facebook\.com\/groups\/([^/?#]+)/);
    if (!m || ['feed', 'discover', 'joins', 'create', 'search'].includes(m[1])) continue;
    const url = `https://www.facebook.com/groups/${m[1]}/`;
    if (seen.has(url)) continue;
    // The result's card: the nearest block with its name and its "members" line.
    let el = a, card = null;
    for (let d = 0; el && d < 12; d++, el = el.parentElement) {
      if (/members?/i.test(el.innerText || '') && (el.innerText || '').length < 600) card = el;
      else if (card) break;
    }
    if (!card) continue;
    const name = (a.innerText || '').trim().split('\n')[0];
    if (!name || name.length < 3) continue;
    seen.add(url);
    const text = card.innerText || '';
    const members = (text.match(/([\d.,]+\s*[KkMm]?)\s+members?/) || [])[1] || '0';
    const privacy = /private/i.test(text) ? 'private' : (/public/i.test(text) ? 'public' : '');
    const joined = [...card.querySelectorAll('[role=button], a')].some(b => /^(visit|joined|view group)$/i.test((b.innerText || '').trim()));
    out.push({ name: name.slice(0, 200), url, members, privacy, joined });
  }
  return out;
}"""


def members(text: str) -> int:
    """'12K' → 12000, '1.2M' → 1200000, '3,456' → 3456."""
    m = re.match(r"\s*([\d.,]+)\s*([KkMm]?)", text or "")
    if not m:
        return 0
    n = float(m.group(1).replace(",", "")) if m.group(2) else float(m.group(1).replace(",", "").replace(".", "") or 0)
    return int(n * {"k": 1_000, "m": 1_000_000}.get(m.group(2).lower(), 1))


async def search(page: Page, *, keyword: str, limit: int = 30) -> dict:
    await page.goto(f"https://www.facebook.com/search/groups/?q={quote(keyword)}", wait_until="domcontentloaded", timeout=60_000)
    await asyncio.sleep(6)
    if re.search(r"/login|checkpoint", page.url) or await page.locator('input[name="pass"]').count():
        raise NotLoggedIn("Facebook is logged out.")
    await check_for_human(page)
    found: dict[str, dict] = {}
    for _ in range(6):
        yield_point()
        for g in await page.evaluate(_RESULTS):
            found.setdefault(g["url"], {**g, "members": members(g["members"])})
        if len(found) >= limit:
            break
        await page.mouse.wheel(0, 1600)
        await asyncio.sleep(random.uniform(2.5, 4.0))
    return {"groups": list(found.values())[:limit], "shot": await shot(page, "facebook-groups-search")}


async def join(page: Page, *, url: str) -> dict:
    await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    await asyncio.sleep(6)
    if re.search(r"/login|checkpoint", page.url) or await page.locator('input[name="pass"]').count():
        raise NotLoggedIn("Facebook is logged out.")
    await check_for_human(page)
    main = page.locator("[role=main]").first
    if await main.get_by_role("button", name=re.compile(r"^(Joined|Invite)$", re.I)).count():
        return {"result": "member", "shot": await shot(page, "facebook-group-joined")}
    button = main.get_by_role("button", name=re.compile(r"^Join (group|Group)$", re.I))
    if not await button.count():
        button = main.get_by_role("button", name=re.compile(r"^Join$", re.I))
    if not await button.count():
        if await main.get_by_role("button", name=re.compile(r"cancel request", re.I)).count():
            return {"result": "requested", "shot": await shot(page, "facebook-group-requested")}
        raise RuntimeError('No "Join group" button on the group.')
    await button.first.click()
    await asyncio.sleep(4)
    dialog = page.get_by_role("dialog")
    if await dialog.count() and await dialog.last.get_by_text(
            re.compile(r"answer|question|rules|agree", re.I)).count():
        # Membership questions or rules to accept: for the owner, never answered here.
        name = await shot(page, "facebook-group-questions")
        await page.keyboard.press("Escape")
        await asyncio.sleep(1)
        return {"result": "needs_answers", "shot": name}
    if await main.get_by_role("button", name=re.compile(r"cancel request|pending", re.I)).count():
        return {"result": "requested", "shot": await shot(page, "facebook-group-requested")}
    return {"result": "member", "shot": await shot(page, "facebook-group-joined")}
