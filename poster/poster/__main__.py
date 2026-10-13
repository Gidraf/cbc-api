"""The poster: a control service for the console, and the posting loop.

Every minute it asks the CBC API for the next post it may publish — the API
applies the day's cap, the per-platform cap, the gap and the hours — and
publishes it in the logged-in browser. A dry run does every step but the
last and keeps a screenshot. A login wall or a check by a person stops that
platform until the owner deals with it on the shared screen.

Two ways to run it:
  server  inside the stack; the API commands it over the control service
          and the owner sees its screen through noVNC.
  local   on the owner's own Mac, in their own Chrome; the server cannot
          reach it, so it checks in and asks for its commands instead.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any

import uvicorn
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse

try:
    # On a Mac behind a company proxy the system keychain knows certificates
    # Python's own bundle does not; use the system's when it is there.
    import truststore

    truststore.inject_into_ssl()
except ImportError:
    pass

from . import cbc, config
from .browser import browser
from .flows import FLOWS, NeedsHuman, NotLoggedIn, StepFailed
from .flows.base import shot

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("poster")
logging.getLogger("httpx").setLevel(logging.WARNING)   # one line per poll is noise

STATE_FILE = os.path.join(os.path.dirname(config.PROFILE_DIR.rstrip("/")) or "/data", "poster-state.json")
state: dict[str, Any] = {"paused": False, "busy": "", "last": None, "logins": {}, "started": time.time(), "note": ""}


def _why(exc: BaseException) -> str:
    """A timeout has no message of its own; say what kind of failure it was."""
    return (f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__)[:200]


def _load() -> None:
    try:
        with open(STATE_FILE) as fh:
            state["paused"] = bool(json.load(fh).get("paused", False))
    except Exception:  # noqa: BLE001
        pass


def _save() -> None:
    try:
        with open(STATE_FILE, "w") as fh:
            json.dump({"paused": state["paused"]}, fh)
    except Exception:  # noqa: BLE001
        pass


async def _set_login(platform: str, ok: bool, note: str = "") -> None:
    state["logins"][platform] = {"logged_in": ok, "note": note, "at": time.time()}
    try:
        await cbc.login_state(platform, ok, note)
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not report %s login state: %s", platform, exc)


async def publish(post: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
    """One post on one platform, in the browser."""
    flow = FLOWS.get(post["platform"])
    if flow is None:
        return {"ok": False, "error": f"No steps for {post['platform']}."}
    async with browser.lock:
        state["busy"] = f"{'Dry run' if dry_run else 'Posting'} on {post['platform']}"
        page = None
        result: dict[str, Any] = {"post_id": post["post_id"], "platform": post["platform"], "dry_run": dry_run}
        try:
            video = await cbc.download(post["video_url"], f"{post['post_id']}.mp4")
            page = await browser.page()
            url = await flow.post(page, video=video, caption=post["caption"], title=post.get("title", ""), dry_run=dry_run)
            result.update(ok=True, url=url, shot=await shot(page, f"{post['platform']}-{'dry' if dry_run else 'done'}"))
            await _set_login(post["platform"], True)
            await cbc.report(post["post_id"], ok=True, url=url, dry_run=dry_run)
        except NotLoggedIn as exc:
            result.update(ok=False, error=str(exc), needs="login")
            await _set_login(post["platform"], False, "Log in on the screen.")
        except NeedsHuman as exc:
            result.update(ok=False, error=str(exc), needs="human", shot=await shot(page, f"{post['platform']}-check") if page else "")
            await _set_login(post["platform"], False, str(exc))
            # The page is left open on the screen for the owner to finish.
            page = None
        except (StepFailed, Exception) as exc:  # noqa: BLE001
            result.update(ok=False, error=str(exc)[:400], shot=await shot(page, f"{post['platform']}-failed") if page else "")
            try:
                await cbc.report(post["post_id"], ok=False, error=str(exc)[:400], dry_run=dry_run)
            except Exception:  # noqa: BLE001
                pass
        finally:
            state["busy"] = ""
            state["last"] = {**result, "at": time.time()}
            if page is not None and not dry_run:
                try:
                    await page.close()
                except Exception:  # noqa: BLE001
                    pass
            try:
                os.remove(os.path.join(config.TMP_DIR, f"{post['post_id']}.mp4"))
            except OSError:
                pass
        if config.POSTER_MODE == "local" and result.get("shot"):
            try:
                await cbc.upload_shot(result["shot"])
            except Exception as exc:  # noqa: BLE001
                log.warning("Could not upload %s: %s", result["shot"], exc)
        log.info("%s", {k: v for k, v in result.items() if k != "caption"})
        return result


async def tick() -> dict[str, Any]:
    if state["paused"]:
        return {"skipped": "paused"}
    try:
        nxt = await cbc.next_post()
    except Exception as exc:  # noqa: BLE001
        state["note"] = f"Cannot reach the CBC API: {exc}"
        return {"skipped": state["note"]}
    state["note"] = nxt.get("reason") or ""
    if not nxt.get("post"):
        return {"skipped": state["note"]}
    return await publish(nxt["post"], dry_run=False)


async def loop() -> None:
    while True:
        try:
            await tick()
        except Exception as exc:  # noqa: BLE001
            log.warning("Tick failed: %s", exc)
        await asyncio.sleep(config.POLL_SECONDS)


# ── what the owner can ask for, from the console ─────────────────────────────

def status_now() -> dict[str, Any]:
    return {"online": True, "mode": config.POSTER_MODE, "paused": state["paused"], "busy": state["busy"],
            "note": state["note"], "browser": browser.channel or "not started", "logins": state["logins"],
            "last": state["last"], "platforms": list(FLOWS)}


async def do_login(platform: str) -> dict[str, Any]:
    """Open the platform's login page in the browser for the owner."""
    flow = FLOWS.get(platform)
    if flow is None:
        return {"ok": False, "error": "Unknown platform."}
    await browser.page(flow.login_url)
    where = "in Chrome on your Mac" if config.POSTER_MODE == "local" else "on the screen"
    return {"ok": True, "message": f"{flow.platform} login is open {where} — log in there, then press Check."}


async def do_check(platform: str = "") -> dict[str, Any]:
    platforms = [platform] if platform else list(FLOWS)
    out = {}
    async with browser.lock:
        for p in platforms:
            if p not in FLOWS:
                continue
            page = await browser.page()
            try:
                ok = await FLOWS[p].logged_in(page)
            except Exception as exc:  # noqa: BLE001
                ok = False
                log.info("Check %s: %s", p, exc)
            finally:
                await page.close()
            await _set_login(p, ok, "" if ok else "Log in on the screen.")
            out[p] = ok
    return {"ok": True, "logins": out}


async def do_dry_run(platform: str = "", post_id: str = "") -> dict[str, Any]:
    """Every step but the last, on the next queued post for a platform."""
    nxt = await cbc.next_post(platform=platform, post_id=post_id, dry=True)
    if not nxt.get("post"):
        return {"ok": False, "error": nxt.get("reason") or "Nothing queued for that platform."}
    return await publish(nxt["post"], dry_run=True)


def set_paused(paused: bool) -> dict[str, Any]:
    state["paused"] = paused
    _save()
    return {"ok": True, "paused": paused}


async def run(action: str, platform: str = "", post_id: str = "") -> dict[str, Any]:
    if action == "login":
        return await do_login(platform)
    if action == "check":
        return await do_check(platform)
    if action == "dry_run":
        return await do_dry_run(platform, post_id)
    if action == "run_now":
        return await tick()
    if action in ("pause", "resume"):
        return set_paused(action == "pause")
    return {"ok": False, "error": f"Unknown action {action!r}."}


# ── server mode: the control service the API talks to (never public) ────────

app = FastAPI(title="CBC browser poster")


def _guard(token: str | None) -> None:
    if not config.POSTER_TOKEN or token != config.POSTER_TOKEN:
        raise HTTPException(status_code=401, detail="Bad poster token.")


@app.get("/status")
async def status(x_poster_token: str | None = Header(default=None)) -> dict[str, Any]:
    _guard(x_poster_token)
    return status_now()


@app.post("/{action}")
async def command(action: str, body: dict[str, Any] | None = None,
                  x_poster_token: str | None = Header(default=None)) -> dict[str, Any]:
    _guard(x_poster_token)
    body = body or {}
    if action not in ("login", "check", "dry_run", "run_now", "pause", "resume"):
        raise HTTPException(404, "No such action.")
    if action == "login" and str(body.get("platform") or "") not in FLOWS:
        raise HTTPException(400, "Unknown platform.")
    return await run(action, str(body.get("platform") or ""), str(body.get("post_id") or ""))


@app.get("/shots/{name}")
async def shots(name: str, x_poster_token: str | None = Header(default=None)):
    _guard(x_poster_token)
    path = os.path.join(config.SHOTS_DIR, os.path.basename(name))
    if not os.path.exists(path):
        raise HTTPException(404, "No such screenshot.")
    return FileResponse(path, media_type="image/png")


# ── local mode: check in, ask for commands, never listen ─────────────────────

async def checkin_loop() -> None:
    while True:
        try:
            await cbc.heartbeat(status_now())
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not check in with %s: %s", config.CBC_API_URL, _why(exc))
        await asyncio.sleep(15)


async def command_loop() -> None:
    while True:
        try:
            cmd = await cbc.take_command()
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not ask for commands: %s", _why(exc))
            cmd = None
        if cmd:
            log.info("Command %s: %s %s", cmd["command_id"], cmd["action"], cmd.get("platform") or "")
            try:
                result = await run(cmd["action"], cmd.get("platform") or "", cmd.get("post_id") or "")
            except Exception as exc:  # noqa: BLE001
                result = {"ok": False, "error": str(exc)[:400]}
            try:
                await cbc.command_done(int(cmd["command_id"]), result)
                await cbc.heartbeat(status_now())     # the console sees the change at once
            except Exception as exc:  # noqa: BLE001
                log.warning("Could not report command %s: %s", cmd["command_id"], _why(exc))
            continue
        await asyncio.sleep(4)


async def main() -> None:
    _load()
    if config.POSTER_MODE == "local":
        if not config.CBC_API_KEY:
            raise SystemExit("CBC_API_KEY is not set — run the installer again, or add it to ~/.cbc/poster/.env.")
        for d in (config.PROFILE_DIR, config.SHOTS_DIR, config.TMP_DIR):
            os.makedirs(d, exist_ok=True)
        log.info("Local poster %s → %s", config.POSTER_ID, config.CBC_API_URL)
        await browser.context()
        await asyncio.gather(checkin_loop(), command_loop(), loop())
        return
    await browser.context()          # the browser is on the screen from the start
    server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=config.CONTROL_PORT, log_level="warning"))
    await asyncio.gather(server.serve(), loop())


if __name__ == "__main__":
    asyncio.run(main())
