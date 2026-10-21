"""Facebook: a reel on your own profile (the default) or on a Page.

Profile: facebook.com/reels/create — the video and the description, then
Post. Post lights up before the upload is done, so it waits for the
preview's "Uploading N%" to go first. Facebook now splits the composer into
steps ("Edit › Settings") with a Next between them; Next is pressed until
the step with Post (and Schedule, groups, story) shows. The old one-screen
composer has no Next, and is posted as before.

Ahead of time: with `schedule_at`, the composer's Schedule button opens
"Scheduling options"; the date ("Nov 7, 2026") and time ("8:47 AM", the
browser's Nairobi time) are typed into its two boxes and read back before
"Schedule for later". Facebook takes dates up to 29 days ahead.

Groups: "Share to groups" lists every group with a checkbox (9 at most per
post); the named ones are ticked, then Done.

Photos (a question's teaser, question and answer cards): the home page's
"What's on your mind" box — the photo, the caption, Post.

Page (FACEBOOK_TARGET=page): Meta Business Suite's reel composer —
Create → Edit → Share. The video goes in through "Add Video"; the step
tabs at the top are buttons too, so the final Share is the footer's.
"""
from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime

from playwright.async_api import Page

from .. import config
from .base import Flow, NotLoggedIn, StepFailed, check_for_human, enabled, first, wait_text, write

PROFILE_COMPOSER = "https://www.facebook.com/reels/create/"
HOME = "https://www.facebook.com/"
PAGE_COMPOSER = "https://business.facebook.com/latest/reels_composer"


def _logged_out(url: str) -> bool:
    return bool(re.search(r"/login|checkpoint|recover", url))


async def _uploaded(page: Page, timeout: float = 900.0) -> None:
    """Until the preview stops saying "Uploading" / "Processing"."""
    busy = page.get_by_text(re.compile(r"^\s*(Uploading|Processing)\b", re.I))
    deadline = time.monotonic() + timeout
    await asyncio.sleep(2)
    while time.monotonic() < deadline:
        try:
            if not await busy.count() or not await busy.first.is_visible():
                return
        except Exception:  # noqa: BLE001
            return
        await asyncio.sleep(2)
    raise StepFailed("The video did not finish uploading in time.")


async def _to_last_step(page: Page, steps: int = 4) -> None:
    """Press Next until the composer's last step (the one with Post) shows.

    Facebook's reel composer is "Edit › Settings": the description is on
    Edit, and Post, Schedule, groups and the story switch are on Settings.
    """
    post = page.get_by_role("button", name=re.compile(r"^(Post|Schedule|Share)$"))
    nxt = page.get_by_role("button", name="Next", exact=True)
    for _ in range(steps):
        try:
            if await post.count() and await post.last.is_visible():
                return
            if not (await nxt.count() and await nxt.last.is_visible()):
                return                              # the one-screen composer: nothing to step through
        except Exception:  # noqa: BLE001
            return
        await enabled(nxt.last, timeout=300)
        await nxt.last.click()
        await asyncio.sleep(3)
    raise StepFailed("Pressed Next but never reached the step with Post — the composer may have changed.")


async def _settled(page: Page, pattern: str, seconds: float) -> None:
    """Give a passing notice a little time to go; never fail on it."""
    note = page.get_by_text(re.compile(pattern, re.I))
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if not await note.count() or not await note.first.is_visible():
                return
        except Exception:  # noqa: BLE001
            return
        await asyncio.sleep(3)


class Facebook(Flow):
    platform = "facebook"
    caption_limit = 2200
    can_schedule = True
    can_share_groups = True

    @property
    def page_mode(self) -> bool:
        return config.FACEBOOK_TARGET == "page"

    @property
    def login_url(self) -> str:  # type: ignore[override]
        # The composer itself: it asks for a login only when one is needed,
        # instead of facebook.com/login bouncing a logged-in owner to the feed.
        return PAGE_COMPOSER if self.page_mode else PROFILE_COMPOSER

    async def logged_in(self, page: Page) -> bool:
        await page.goto(self.login_url, wait_until="domcontentloaded", timeout=60_000)
        await asyncio.sleep(4)
        if _logged_out(page.url):
            return False
        try:
            if self.page_mode:
                await first(page, [page.get_by_role("button", name="Add Video")], timeout=25, what="the reel composer")
            else:
                await page.locator('input[type="file"][accept*="video"]').first.wait_for(state="attached", timeout=25_000)
            return True
        except Exception:  # noqa: BLE001
            return False

    async def post(self, page: Page, *, video: str, caption: str, title: str, dry_run: bool,
                   schedule_at: str = "", groups: list[str] | None = None) -> str:
        self.shared_groups, self.destinations = [], []
        if not await self.logged_in(page):
            raise NotLoggedIn("Facebook is logged out.")
        await check_for_human(page)
        if self.page_mode:
            if schedule_at or groups:
                raise StepFailed("Scheduling ahead and group shares are set up for the profile composer only.")
            return await self._page_reel(page, video=video, caption=caption, dry_run=dry_run)
        return await self._profile_reel(page, video=video, caption=caption, dry_run=dry_run,
                                        schedule_at=schedule_at, groups=groups or [])

    can_post_photos = True

    async def post_photo(self, page: Page, *, image: str, caption: str, dry_run: bool) -> str:
        """A photo post on the profile's feed: the home page's "What's on
        your mind" composer, the photo, the caption, then Post."""
        if self.page_mode:
            raise StepFailed("Photo posts are set up for the profile only.")
        await page.goto(HOME, wait_until="domcontentloaded", timeout=60_000)
        await asyncio.sleep(4)
        if _logged_out(page.url):
            raise NotLoggedIn("Facebook is logged out.")
        await check_for_human(page)
        opener = await first(page, [page.get_by_role("button", name=re.compile(r"What.s on your mind", re.I)),
                                    page.get_by_text(re.compile(r"^What.s on your mind", re.I))],
                             timeout=30, what='"What\'s on your mind"')
        await opener.click()
        # The composer: the dialog with the post's text box (its title has
        # changed before — "Create post", "Create a post" — so not by its title).
        dialog = page.get_by_role("dialog").filter(has=page.locator('[contenteditable="true"][role="textbox"]')).last
        await first(page, [dialog], timeout=30, what='the "Create post" box')
        box = await first(page, [dialog.locator('[contenteditable="true"][role="textbox"]')], timeout=30,
                          what="the post's text box")
        await write(page, box, self.fit(caption))
        # The photo: the box's own file input if it has one; else "Photo/video",
        # then its input or its file chooser.
        files = dialog.locator('input[type="file"][accept*="image"]')
        if not await files.count():
            pv = await first(page, [dialog.get_by_role("button", name=re.compile(r"Photo/video", re.I)),
                                    dialog.get_by_label(re.compile(r"Photo/video", re.I))], timeout=20,
                             what='"Photo/video"')
            await pv.click()
            await asyncio.sleep(1.5)
        if await files.count():
            await files.first.set_input_files(image)
        else:
            add = await first(page, [dialog.get_by_text(re.compile(r"Add photos/videos", re.I))], timeout=20,
                              what='"Add photos/videos"')
            async with page.expect_file_chooser(timeout=20_000) as chooser:
                await add.click()
            await (await chooser.value).set_files(image)
        await first(page, [dialog.locator("img[src^='blob:'], img[src*='scontent']")], timeout=90,
                    what="the photo's preview")
        await asyncio.sleep(1.5)
        post = dialog.get_by_role("button", name="Post", exact=True).last
        await enabled(post, timeout=120)
        await check_for_human(page)
        self.destinations = ["feed"]
        if dry_run:
            return ""
        await post.click()
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:          # done when the box closes
            try:
                if not await dialog.count() or not await dialog.is_visible():
                    return ""
            except Exception:  # noqa: BLE001
                return ""
            await asyncio.sleep(2)
        raise RuntimeError("Facebook did not confirm the photo post.")

    async def groups(self, page: Page) -> list[str]:
        """Every group in the composer's "Share to groups" list."""
        await page.goto(PROFILE_COMPOSER, wait_until="domcontentloaded", timeout=60_000)
        await asyncio.sleep(4)
        if _logged_out(page.url):
            raise NotLoggedIn("Facebook is logged out.")
        dialog = await _open_groups(page)
        names: list[str] = []
        for _ in range(12):                       # the list may load more as it scrolls
            found = await dialog.evaluate(_GROUP_NAMES)
            new = [n for n in found if n not in names]
            names += new
            if not new:
                break
            await dialog.evaluate("d => { const s = [...d.querySelectorAll('*')].find(e => e.scrollHeight > e.clientHeight + 20); if (s) s.scrollTop = s.scrollHeight; }")
            await asyncio.sleep(1.5)
        await page.keyboard.press("Escape")
        return names

    async def _profile_reel(self, page: Page, *, video: str, caption: str, dry_run: bool,
                            schedule_at: str = "", groups: list[str] | None = None) -> str:
        await page.locator('input[type="file"][accept*="video"]').first.set_input_files(video)
        box = await first(page, [page.locator('[contenteditable="true"][role="textbox"]')], timeout=60,
                          what="the description box")
        await write(page, box, self.fit(caption))
        await _uploaded(page)
        await _settled(page, r"Checking for copyrighted", 120)   # posting can go ahead without it, but give it a moment
        await _to_last_step(page)                                  # Edit › Settings: Next, to where Post is
        if groups and schedule_at:
            raise StepFailed("Facebook cannot schedule a reel that is shared to a group — one or the other.")
        # A profile reel shows on the profile and in friends' and followers'
        # feeds; it goes to the story too when the composer's "Share to story"
        # is on (the owner's own setting — read, never changed here).
        self.destinations = ["reel", "feed"] + (["story"] if await _story_on(page) else [])
        if groups:
            self.shared_groups = await _tick_groups(page, groups)
        if schedule_at:
            return await self._schedule(page, datetime.fromisoformat(schedule_at), dry_run=dry_run)
        post = page.get_by_role("button", name="Post", exact=True).last
        await enabled(post, timeout=300)
        await check_for_human(page)
        if dry_run:
            return ""
        await post.click()
        ok = await _left_composer_or_said(page, "/reels/create")
        await check_for_human(page)
        if not ok:
            raise RuntimeError("Facebook did not confirm the reel.")
        return ""

    async def _schedule(self, page: Page, at: datetime, *, dry_run: bool) -> str:
        """Facebook's own Schedule: it publishes at `at` (Nairobi time, as the
        browser is). The boxes are read back — a date Facebook will not take
        is refused rather than quietly scheduled on another day."""
        button = page.get_by_role("button", name="Schedule", exact=True).last
        await enabled(button, timeout=300)
        await button.click()
        await first(page, [page.get_by_text("Scheduling options")], timeout=20, what="the scheduling options")
        boxes = page.locator('input[type="text"][role="combobox"]')
        day = f"{at:%b} {at.day}, {at.year}"
        clock = f"{(at.hour % 12) or 12}:{at.minute:02d} {'AM' if at.hour < 12 else 'PM'}"
        for box, text in ((boxes.nth(0), day), (boxes.nth(1), clock)):
            await box.click()
            await asyncio.sleep(0.6)
            await page.keyboard.press("ControlOrMeta+A")
            await page.keyboard.type(text, delay=30)
            await page.keyboard.press("Enter")
            await asyncio.sleep(1.0)
        got = (await boxes.nth(0).input_value(), await boxes.nth(1).input_value())
        if got != (day, clock):
            raise StepFailed(f"Facebook would not take {day} {clock} (it shows {got[0]} {got[1]}) — "
                             "it schedules up to 29 days ahead.")
        await check_for_human(page)
        if dry_run:
            return ""
        await page.get_by_role("button", name="Schedule for later").last.click()
        ok = await _left_composer_or_said(page, "/reels/create")
        await check_for_human(page)
        if not ok:
            raise RuntimeError("Facebook did not confirm the scheduled reel.")
        return ""

    async def _page_reel(self, page: Page, *, video: str, caption: str, dry_run: bool) -> str:
        add = await first(page, [page.get_by_role("button", name="Add Video")], timeout=30, what='"Add Video"')
        async with page.expect_file_chooser(timeout=20_000) as chooser:
            await add.click()
        await (await chooser.value).set_files(video)
        box = await first(page, [page.locator('[contenteditable="true"][role="textbox"]')], timeout=60,
                          what="the description box")
        await write(page, box, self.fit(caption))
        share_now = page.get_by_text("Share now", exact=True)
        for _ in range(4):       # Create → Edit → Share
            if await share_now.count() and await share_now.first.is_visible():
                break
            nxt = page.get_by_role("button", name="Next", exact=True).last
            await enabled(nxt, timeout=600)
            await nxt.click()
            await asyncio.sleep(3)
        else:
            raise StepFailed("Never reached the Share step.")
        await share_now.first.click()
        share = page.get_by_role("button", name="Share", exact=True).last   # the footer's, not the step tab
        await enabled(share, timeout=600)
        await check_for_human(page)
        if dry_run:
            return ""
        await share.click()
        ok = await _left_composer_or_said(page, "reels_composer")
        await check_for_human(page)
        if not ok:
            raise RuntimeError("Facebook did not confirm the reel.")
        return ""


_GROUP_NAMES = """d => {
  const out = [];
  for (const box of d.querySelectorAll('[role=checkbox], input[type=checkbox]')) {
    let row = box;
    for (let i = 0; i < 8 && row; i++) {
      row = row.parentElement;
      const lines = (row?.innerText || '').split('\\n').map(s => s.trim()).filter(Boolean);
      if (lines.length >= 1 && lines.length <= 4 && lines[0].length < 120) { out.push(lines[0]); break; }
    }
  }
  return [...new Set(out)].filter(n => !/^(select groups|post in up to)/i.test(n));
}"""


async def _story_on(page: Page) -> bool:
    try:
        text = await page.evaluate("""() => {
          const label = [...document.querySelectorAll('span')].find(e => e.innerText.trim() === 'Share to story');
          let row = label;
          for (let i = 0; i < 5 && row; i++) { row = row.parentElement; if ((row.innerText || '').split('\\n').length > 1) break; }
          return row ? row.innerText : '';
        }""")
    except Exception:  # noqa: BLE001
        return False
    return bool(re.search(r"\bsharing\b", text, re.I)) and not re.search(r"not sharing|\boff\b", text, re.I)


async def _open_groups(page: Page):
    row = page.locator("span").filter(has_text=re.compile(r"^Share to groups$")).first
    await row.scroll_into_view_if_needed()
    await row.click()
    await first(page, [page.get_by_text("Select groups")], timeout=20, what="the group list")
    # Not a role=dialog: the box that holds the "Select groups" heading and the checkboxes.
    dialog = page.locator("div").filter(has=page.get_by_text("Select groups")).filter(
        has=page.locator('[role=checkbox], input[type=checkbox]')).last
    await asyncio.sleep(1.5)
    return dialog


async def _tick_groups(page: Page, names: list[str]) -> list[str]:
    """Tick the named groups (Facebook allows 9 a post), then Done. A group
    that is not in the list is skipped, never guessed at."""
    dialog = await _open_groups(page)
    ticked: list[str] = []
    for name in names[:9]:
        if not await dialog.get_by_text(name, exact=True).count():
            continue
        row = dialog.locator("div").filter(has=page.get_by_text(name, exact=True)).filter(
            has=page.locator('[role=checkbox], input[type=checkbox]')).last
        box = row.locator('[role=checkbox], input[type=checkbox]').first
        if (await box.get_attribute("aria-checked")) != "true" and not await box.is_checked():
            await box.click()
            await asyncio.sleep(0.6)
        if (await box.get_attribute("aria-checked")) == "true" or await box.is_checked():
            ticked.append(name)
    await page.get_by_role("button", name="Done", exact=True).last.click()   # in the footer, outside the list
    await asyncio.sleep(1.0)
    return ticked


async def _left_composer_or_said(page: Page, composer: str, timeout: float = 600.0) -> bool:
    """Done when the composer closes, or the page says the reel is out."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if composer not in page.url:
            return True
        if await wait_text(page, r"reel (?:is |has been )?(?:being )?(?:published|shared|posted|scheduled)|your reel is|scheduled for", timeout=4):
            return True
    return False
