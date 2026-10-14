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


PENDING_FILE = os.path.join(os.path.dirname(STATE_FILE), "unreported.json")


def _pending() -> list[dict[str, Any]]:
    try:
        with open(PENDING_FILE) as fh:
            return list(json.load(fh))
    except Exception:  # noqa: BLE001
        return []


def _keep_pending(items: list[dict[str, Any]]) -> None:
    try:
        with open(PENDING_FILE, "w") as fh:
            json.dump(items, fh)
    except Exception as exc:  # noqa: BLE001
        log.error("Could not keep the unreported posts: %s", exc)


async def _report_or_keep(outcome: dict[str, Any]) -> None:
    """Tell the server a post is out; if it cannot be told, keep the news on
    disk and tell it before doing anything else."""
    for attempt in range(3):
        try:
            await cbc.report(outcome["post_id"], ok=True, url=outcome.get("url", ""), dry_run=outcome.get("dry_run", False),
                             scheduled=outcome.get("scheduled", False), groups=outcome.get("groups") or [],
                             destinations=outcome.get("destinations") or [])
            return
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not report %s (try %s): %s", outcome["post_id"], attempt + 1, _why(exc))
            await asyncio.sleep(5 * (attempt + 1))
    if not outcome.get("dry_run"):
        _keep_pending([*_pending(), outcome])


async def flush_reports() -> bool:
    """Send any posts the server has not heard about. True when none are left."""
    left = []
    for outcome in _pending():
        try:
            await cbc.report(outcome["post_id"], ok=True, url=outcome.get("url", ""), scheduled=outcome.get("scheduled", False),
                             groups=outcome.get("groups") or [], destinations=outcome.get("destinations") or [])
        except Exception:  # noqa: BLE001
            left.append(outcome)
    if left or os.path.exists(PENDING_FILE):
        _keep_pending(left)
    return not left


async def publish(post: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
    """One post on one platform, in the browser."""
    flow = FLOWS.get(post["platform"])
    if flow is None:
        return {"ok": False, "error": f"No steps for {post['platform']}."}
    async with browser.lock:
        state["busy"] = (f"{'Dry run' if dry_run else 'Scheduling' if post.get('schedule_at') else 'Posting'} "
                         f"on {post['platform']}")
        page = None
        result: dict[str, Any] = {"post_id": post["post_id"], "platform": post["platform"], "dry_run": dry_run}
        try:
            schedule_at, groups = post.get("schedule_at") or "", post.get("groups") or []
            if schedule_at and not flow.can_schedule:
                raise StepFailed(f"The poster cannot use {post['platform']}'s scheduler; this post must go out live.")
            extra: dict[str, Any] = {}
            if flow.can_schedule:
                extra["schedule_at"] = schedule_at
            if flow.can_share_groups:
                extra["groups"] = groups
            video = await cbc.download(post["video_url"], f"{post['post_id']}.mp4")
            page = await browser.page()
            url = await flow.post(page, video=video, caption=post["caption"], title=post.get("title", ""),
                                  dry_run=dry_run, **extra)
            shared = list(getattr(flow, "shared_groups", []) or [])
            places = list(getattr(flow, "destinations", []) or [])
            result.update(ok=True, url=url, scheduled=bool(schedule_at), schedule_at=schedule_at, groups=shared,
                          destinations=places,
                          shot=await shot(page, f"{post['platform']}-{'dry' if dry_run else 'scheduled' if schedule_at else 'done'}"))
            # From here it is out (or scheduled): whatever happens next, it is
            # never reported as failed — that would post it a second time.
            outcome = {"post_id": post["post_id"], "ok": True, "url": url, "dry_run": dry_run,
                       "scheduled": bool(schedule_at), "groups": shared, "destinations": places}
            await _set_login(post["platform"], True)
            await _report_or_keep(outcome)
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
    if not await flush_reports():
        state["note"] = "Waiting to tell the server about a post that went out."
        return {"skipped": state["note"]}
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


async def post_now(platform: str = "") -> dict[str, Any]:
    """"Post next now": the next queued post goes out live at once — not at
    its booked time, and without waiting out the gap. A post already due
    goes first; otherwise the next booked one on a platform logged in."""
    if state["paused"]:
        return {"ok": False, "error": "The poster is paused — resume it first."}
    done = await tick()
    if done.get("post_id"):
        return done
    why = done.get("skipped") or ""
    for p in [platform] if platform else list(FLOWS):
        if not platform and state["logins"].get(p, {}).get("logged_in") is False:
            continue
        nxt = await cbc.next_post(platform=p, dry=True)
        if nxt.get("post"):
            # Out now, live — never handed to the platform's scheduler for later.
            return await publish({**nxt["post"], "schedule_at": ""}, dry_run=False)
        why = nxt.get("reason") or why
    return {"ok": False, "error": why or "Nothing queued to post."}


async def do_groups(platform: str = "facebook") -> dict[str, Any]:
    """Read the owner's groups from the platform's share picker and send the
    list to the console, where the owner ticks the ones to share to."""
    flow = FLOWS.get(platform or "facebook")
    if flow is None or not flow.can_share_groups:
        return {"ok": False, "error": f"No group sharing on {platform or 'facebook'}."}
    async with browser.lock:
        state["busy"] = f"Reading your {flow.platform} groups"
        page = await browser.page()
        try:
            names = await flow.groups(page)
        except NotLoggedIn as exc:
            await _set_login(flow.platform, False, "Log in on the screen.")
            return {"ok": False, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"Could not read the groups: {_why(exc)}"}
        finally:
            state["busy"] = ""
            try:
                await page.close()
            except Exception:  # noqa: BLE001
                pass
    await cbc.groups_found(flow.platform, names)
    return {"ok": True, "message": f"Found {len(names)} groups — tick the ones that welcome teaching posts.",
            "count": len(names)}


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
        return await post_now(platform)
    if action in ("pause", "resume"):
        return set_paused(action == "pause")
    if action == "groups":
        return await do_groups(platform or "facebook")
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
    if action not in ("login", "check", "dry_run", "run_now", "pause", "resume", "groups"):
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
