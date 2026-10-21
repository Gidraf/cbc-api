"""One real browser, kept open, with the profile the owner logged into.

A persistent profile keeps each platform's session between runs and
restarts. The browser is shown on the shared screen (not headless) so the
owner can log in, answer a "is this you?" check, and watch a post go out.
Nothing here disguises the browser.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from playwright.async_api import BrowserContext, Page, async_playwright

from . import config

log = logging.getLogger("poster.browser")


class ProfileBusy(RuntimeError):
    """The profile is in use by another Chrome the owner may still be using."""


LEFT_OPEN = 10 * 60           # seconds: a Chrome on the profile this long is a login window left open


async def free_profile(profile: str) -> bool:
    """Free the profile for the poster: a lock left by a Chrome that is gone is
    cleared; a Chrome on it for more than LEFT_OPEN is asked to quit (as Cmd+Q
    does: it saves its cookies, so a login done there is kept). False while a
    Chrome opened on it only lately is still there — the owner may be logging in."""
    import os
    import signal
    import time

    lock = os.path.join(profile, "SingletonLock")
    try:
        target = os.readlink(lock)                      # "<host>-<pid>"
    except OSError:
        return True
    try:
        pid = int(target.rsplit("-", 1)[1])
        os.kill(pid, 0)
        alive = True
    except (ValueError, IndexError, ProcessLookupError, PermissionError):
        alive = False
    if not alive:
        for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
            try:
                os.unlink(os.path.join(profile, name))
            except OSError:
                pass
        log.info("Cleared the lock a closed Chrome left on the profile.")
        return True
    if time.time() - os.lstat(lock).st_mtime < LEFT_OPEN:
        return False
    log.info("A Chrome has had the profile open for over %d minutes (a Log in window left open): asking it to quit.",
             LEFT_OPEN // 60)
    os.kill(pid, signal.SIGTERM)
    for _ in range(30):
        await asyncio.sleep(1)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
    return False


class Browser:
    def __init__(self) -> None:
        self._pw: Any = None
        self._ctx: BrowserContext | None = None
        self.channel = ""
        self.lock = asyncio.Lock()   # one action in the browser at a time

    async def context(self) -> BrowserContext:
        if self._ctx is not None:
            return self._ctx
        if self._pw is None:
            self._pw = await async_playwright().start()
        options = dict(user_data_dir=config.PROFILE_DIR, headless=False, viewport=None, locale="en-US",
                       timezone_id="Africa/Nairobi", args=["--start-maximized", "--no-first-run",
                                                           "--no-default-browser-check", "--disable-dev-shm-usage"])
        # Real Chrome keeps its cookies encrypted with the Mac's Keychain. Playwright
        # swaps in a fake keychain by default, which makes a login done in plain
        # Chrome (mac/login.sh) unreadable here, and this one unreadable there.
        # Keep the real one so a single login works in both, every start.
        chrome_options = dict(options, ignore_default_args=["--use-mock-keychain", "--password-store=basic"])
        try:
            self._ctx = await self._pw.chromium.launch_persistent_context(channel=config.BROWSER_CHANNEL,
                                                                          **chrome_options)
            self.channel = config.BROWSER_CHANNEL
        except Exception as exc:  # noqa: BLE001
            if "ProcessSingleton" in str(exc) or "profile directory" in str(exc):
                # The profile is open in another Chrome — the window "Log in"
                # opens, left open — not a missing Chrome: Chromium would not
                # have the logins either. Free it, or wait for the owner.
                if not await free_profile(config.PROFILE_DIR):
                    raise ProfileBusy("The poster's Chrome profile is open in another Chrome window (Log in?). "
                                      "Finish logging in there, then quit that Chrome with Cmd+Q.") from None
                self._ctx = await self._pw.chromium.launch_persistent_context(channel=config.BROWSER_CHANNEL,
                                                                              **chrome_options)
                self.channel = config.BROWSER_CHANNEL
            else:
                log.info("No %s here (%s); using Chromium.", config.BROWSER_CHANNEL, str(exc).splitlines()[0][:120])
                self._ctx = await self._pw.chromium.launch_persistent_context(**options)
                self.channel = "chromium"
        # Closing the window (on a Mac) ends the browser; the next action opens it again.
        self._ctx.on("close", lambda *_: setattr(self, "_ctx", None))
        return self._ctx

    async def close(self) -> None:
        """Close the poster's Chrome, so the profile can be opened in ordinary Chrome."""
        ctx, self._ctx = self._ctx, None
        if ctx is not None:
            try:
                await ctx.close()
            except Exception:  # noqa: BLE001
                pass

    async def page(self, url: str | None = None) -> Page:
        ctx = await self.context()
        page = await ctx.new_page()
        if url:
            await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        await page.bring_to_front()
        return page


browser = Browser()
