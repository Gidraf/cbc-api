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
import sys
import json
import logging
import os
import random
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
from .flows.base import URGENT, Yielded
from .flows.base import shot

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("poster")
logging.getLogger("httpx").setLevel(logging.WARNING)   # one line per poll is noise

STATE_FILE = os.path.join(os.path.dirname(config.PROFILE_DIR.rstrip("/")) or "/data", "poster-state.json")
state: dict[str, Any] = {"paused": False, "busy": "", "last": None, "logins": {}, "started": time.time(), "note": "",
                         "today": {}}


def count(kind: str, n: int = 1) -> None:
    """Today's activity on this Mac (posts, comments, shares, likes, boosts, failures), shown in the console."""
    day = time.strftime("%Y-%m-%d")
    today = state["today"]
    if today.get("day") != day:
        today.clear()
        today["day"] = day
    today[kind] = int(today.get(kind) or 0) + max(0, int(n))


def _machine() -> dict[str, Any]:
    import platform
    import socket

    here = os.path.dirname(os.path.abspath(__file__))
    return {"host": socket.gethostname().split(".")[0], "os": (f"macOS {platform.mac_ver()[0]}" if sys.platform == "darwin"
                                                               else platform.platform(terse=True)),
            "code": time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(os.path.join(here, "__main__.py")))),
            "hash": code_hash(here)}


def code_hash(folder: str) -> str:
    """A fingerprint of the poster's code (every .py file, by its path in the
    package) — the server works out the same for the code it serves, and the
    Devices page says when a Mac is behind."""
    import hashlib

    h = hashlib.sha256()
    root = os.path.abspath(folder)
    files = []
    for d, dirs, names in os.walk(root):
        dirs[:] = sorted(x for x in dirs if x != "__pycache__")
        files += [os.path.join(d, n) for n in names if n.endswith(".py")]
    for f in sorted(files, key=lambda x: os.path.relpath(x, root).replace(os.sep, "/")):
        h.update(os.path.relpath(f, root).replace(os.sep, "/").encode() + b"\n")
        with open(f, "rb") as fh:
            h.update(fh.read())
    return h.hexdigest()[:16]


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
    account = (state["logins"].get(platform) or {}).get("account", "")    # whose account: kept from the last check
    state["logins"][platform] = {"logged_in": ok, "note": note, "at": time.time(), **({"account": account} if account else {})}
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


async def _share_photo(page: Any, post: dict[str, Any], groups: list[str]) -> list[str]:
    """A photo post just out, shared to its groups. Never fails the post (it is out):
    the groups it reached, or none."""
    from .flows import fb_share

    words = " ".join(str(post.get("caption") or "").split())
    try:
        await asyncio.sleep(20)                       # a moment for the post to show on the profile
        out = await fb_share.share_post(page, find=words[:60], also=[words[60:120]] if len(words) > 80 else [],
                                        groups=groups)
        return list(out.get("groups") or [])
    except Exception as exc:  # noqa: BLE001
        log.info("The photo %s is out; sharing it to its groups failed: %s", post.get("post_id"), _why(exc))
        return []


async def publish(post: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
    """One post on one platform, in the browser."""
    flow = FLOWS.get(post["platform"])
    if flow is None:
        return {"ok": False, "error": f"No steps for {post['platform']}."}
    async with browser.lock:
        state["busy"] = (f"{'Dry run' if dry_run else 'Scheduling' if post.get('schedule_at') else 'Posting'} "
                         f"{'a ' + str(post.get('step') or 'photo') + ' card' if post.get('format') == 'photo' else ''} "
                         f"on {post['platform']}").replace("  ", " ")
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
            if post.get("format") == "photo":
                # A card of a question's series: the teaser, the question, or its answer.
                if not getattr(flow, "can_post_photos", False):
                    raise StepFailed(f"The poster cannot post photos on {post['platform']} yet.")
                image = await cbc.download(post["image_url"], _pic_name(post["post_id"], post["image_url"]))
                page = await browser.page()
                url = await flow.post_photo(page, image=image, caption=post["caption"], dry_run=dry_run)
                if groups and not dry_run and post["platform"] == "facebook":
                    # Out on the feed: then shared to its groups, as a reel is —
                    # found on the profile by its words and shared from there.
                    flow.shared_groups = await _share_photo(page, post, groups)
            else:
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
            if not dry_run:
                count("posts")
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
            for ext in ("mp4", "jpg"):
                try:
                    os.remove(os.path.join(config.TMP_DIR, f"{post['post_id']}.{ext}"))
                except OSError:
                    pass
        if config.POSTER_MODE == "local" and result.get("shot"):
            try:
                await cbc.upload_shot(result["shot"])
            except Exception as exc:  # noqa: BLE001
                log.warning("Could not upload %s: %s", result["shot"], exc)
        log.info("%s", {k: v for k, v in result.items() if k != "caption"})
        return result


ENGAGE_EVERY = 20 * 60          # seconds: the longest the like-back, replies and groups wait for a turn
RECHECK_EVERY = 10 * 60         # seconds: a platform marked logged out is checked again this often


async def _recheck_logins() -> None:
    """A platform marked logged out is checked again every few minutes: a
    page that did not load, or a moment's checkpoint, should not stop the
    posting until someone presses Check — a real logout stays marked."""
    now = time.time()
    for platform, login in list((state.get("logins") or {}).items()):
        if login.get("logged_in") is not False or platform not in FLOWS:
            continue
        if now - float(login.get("at") or 0) < RECHECK_EVERY or now - state.get(f"recheck_{platform}", 0) < RECHECK_EVERY:
            continue
        state[f"recheck_{platform}"] = now
        try:
            got = await do_check(platform)
            if (got.get("logins") or {}).get(platform):
                log.info("%s is logged in after all — posting carries on.", platform)
        except Exception as exc:  # noqa: BLE001
            log.info("Re-check of %s failed: %s", platform, _why(exc))


async def tick() -> dict[str, Any]:
    if state["paused"]:
        return {"skipped": "paused"}
    if not await flush_reports():
        state["note"] = "Waiting to tell the server about a post that went out."
        return {"skipped": state["note"]}
    await _recheck_logins()
    try:
        nxt = await cbc.next_post()
    except Exception as exc:  # noqa: BLE001
        state["note"] = f"Cannot reach the CBC API: {exc}"
        return {"skipped": state["note"]}
    state["note"] = nxt.get("reason") or ""
    if not nxt.get("post"):
        # Nothing to post: the comments due under posts that are out — or,
        # with none due, the next like-back step.
        try:
            if await linkedin_step():
                return {"skipped": state["note"]}
            # Liking back, replies and groups get a turn every 20 minutes or so
            # even while the comments are busy — a profile active all day.
            if time.time() - state.get("engage_at", 0) > ENGAGE_EVERY:
                state["engage_at"] = time.time()
                await engage_step()
                return {"skipped": state["note"]}
            done = await comment_step()
            if not done.get("ok") and done.get("error") == "No post to comment on.":
                state["engage_at"] = time.time()
                await engage_step()
        except Exception as exc:  # noqa: BLE001
            log.warning("Comment or like-back step failed: %s", _why(exc))
        return {"skipped": state["note"]}
    return await publish(nxt["post"], dry_run=False)


async def boost_step(post_id: str, options: dict[str, Any]) -> dict[str, Any]:
    """Boost one post — pressed in the console, with its budget."""
    from .flows import fb_boost

    async with browser.lock:
        state["busy"] = f"Boosting a post (KSh {options.get('daily_ksh')} a day, {options.get('days')} days)"
        page = await browser.page()
        try:
            out = await fb_boost.boost(page, find=str(options.get("find") or ""), also=options.get("find_also") or [],
                                       daily_ksh=int(options.get("daily_ksh") or 0), days=int(options.get("days") or 0))
            if out.get("unsure"):
                return {"ok": False, "unsure": True, "error": "Pressed Boost, but Facebook did not confirm — check Ads Manager.",
                        "shot": out.get("shot")}
            count("boosts")
            return {"ok": True, "message": f"Boosted: KSh {out['total_ksh']:,} in all.", "shot": out.get("shot")}
        except NotLoggedIn as exc:
            await _set_login("facebook", False, "Log in on the screen.")
            return {"ok": False, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": _why(exc), "shot": await shot(page, "facebook-boost-failed")}
        finally:
            state["busy"] = ""
            try:
                await page.close()
            except Exception:  # noqa: BLE001
                pass


async def linkedin_step() -> bool:
    """A developer-studio post on LinkedIn, if one is queued: True when one was tried."""
    if URGENT["n"]:
        return False
    try:
        post = await cbc.linkedin_next()
    except Exception:  # noqa: BLE001
        return False                      # an older server: no LinkedIn queue
    if not post:
        return False
    flow = FLOWS.get("linkedin")
    kind = "pdf" if post["kind"] == "document" else "mp4"
    path = ""
    async with browser.lock:
        state["busy"] = f"Posting a {post['kind']} on LinkedIn"
        page = None
        try:
            path = await cbc.download(post["media_url"], f"li-{post['post_id']}.{kind}")
            page = await browser.page()
            if post["kind"] == "document":
                url = await flow.post_document(page, pdf=path, caption=post["body"], title=post["title"], dry_run=False)
            else:
                url = await flow.post(page, video=path, caption=post["body"], title=post["title"], dry_run=False)
            await cbc.linkedin_done(post["post_id"], ok=True, url=url or "")
            await _set_login("linkedin", True)
            log.info("LinkedIn %s posted: %s", post["kind"], post["post_id"])
            count("linkedin")
        except NotLoggedIn as exc:
            await _set_login("linkedin", False, "Log in on the screen.")
            await cbc.linkedin_done(post["post_id"], ok=False, error=str(exc))
        except Exception as exc:  # noqa: BLE001
            log.info("LinkedIn %s failed: %s", post["post_id"], _why(exc))
            await cbc.linkedin_done(post["post_id"], ok=False, error=_why(exc))
        finally:
            state["busy"] = ""
            if page is not None:
                try:
                    await page.close()
                except Exception:  # noqa: BLE001
                    pass
            if path:
                try:
                    os.remove(path)
                except OSError:
                    pass
    return True


async def group_step(act: dict[str, Any]) -> dict[str, Any]:
    """Find groups for a keyword, or join one group."""
    from .flows import fb_groups

    async with browser.lock:
        state["busy"] = (f"Looking for groups: {act.get('keyword')}" if act["kind"] == "find_groups"
                         else f"Joining the group {act.get('name') or ''}")
        page = await browser.page()
        try:
            if act["kind"] == "find_groups":
                out = await fb_groups.search(page, keyword=str(act.get("keyword") or ""), limit=int(act.get("limit") or 30))
                await cbc.engage_done("find_groups", str(act.get("keyword") or ""), groups=out["groups"])
                log.info("Groups for %r: %d found.", act.get("keyword"), len(out["groups"]))
                return {"ok": True, "message": f"{len(out['groups'])} group(s) found.", "shot": out.get("shot")}
            out = await fb_groups.join(page, url=str(act["url"]))
            await cbc.engage_done("join_group", str(act["url"]), result=out["result"])
            count("groups_joined" if out["result"] == "member" else "group_requests")
            log.info("Group %s: %s", act.get("name"), out["result"])
            return {"ok": True, "message": f"{act.get('name')}: {out['result']}", "shot": out.get("shot")}
        except Yielded:
            return {"ok": False, "error": "A command from the console came first."}
        except NotLoggedIn as exc:
            await _set_login("facebook", False, "Log in on the screen.")
            return {"ok": False, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            why = _why(exc)
            try:
                await cbc.engage_done(act["kind"], str(act.get("keyword") or act.get("url") or ""), error=why)
            except Exception:  # noqa: BLE001
                pass
            return {"ok": False, "error": why, "shot": await shot(page, "facebook-groups-failed")}
        finally:
            state["busy"] = ""
            try:
                await page.close()
            except Exception:  # noqa: BLE001
                pass


async def engage_step(*, check: bool = False) -> dict[str, Any]:
    """One like-back step: like the comments under one of your posts and note
    who wrote them, or like a few posts of one person who commented.
    `check`: read the newest post's commenters, liking nothing."""
    from .flows import fb_engage

    if URGENT["n"] and not check:
        return {"ok": False, "error": "A command from the console comes first."}
    if check:
        job = await cbc.comments_next(check=True)
        if not job:
            return {"ok": False, "error": "No post is out yet to check against."}
        act = {"kind": "scan", "post_id": job["post_id"], "find": job.get("find") or "", "url": job.get("url") or "", "count": 0}
    else:
        nxt = await cbc.engage_next()
        act = nxt.get("action")
        if not act:
            return {"ok": False, "error": nxt.get("reason") or "Nothing to like now."}
    target = act.get("post_id") if act["kind"] == "scan" else act.get("keyword") if act["kind"] == "find_groups" else act.get("url")
    if act["kind"] in ("find_groups", "join_group"):
        return await group_step(act)
    async with browser.lock:
        state["busy"] = "Reading the comments" if act["kind"] == "scan" else f"Liking {act.get('name') or 'a commenter'}'s posts"
        page = await browser.page()
        try:
            if act["kind"] == "scan":
                out = await fb_engage.scan(page, find=act.get("find") or "", url=act.get("url") or "", count=int(act.get("count") or 0),
                                           reply=None if check else act.get("reply"))
                if out.get("replied"):
                    count("replies", len(out["replied"]))
            else:
                out = await fb_engage.like_person(page, url=act["url"], count=int(act.get("count") or 1))
            if not check:
                await cbc.engage_done(act["kind"], str(target), likes=out.get("likes", 0), people=out.get("people"),
                                      replied=out.get("replied") or [])
                count("likes", out.get("likes", 0))
            log.info("Like-back %s %s: %s likes, %s people", act["kind"], "(check)" if check else "", out.get("likes", 0),
                     len(out.get("people") or []))
            return {"ok": True, "message": (f"Found {len(out.get('people') or [])} commenters under your newest post (nothing liked)."
                                            if check else f"{out.get('likes', 0)} like(s)."), "shot": out.get("shot"),
                    "people": [p.get("name") for p in (out.get("people") or [])][:20]}
        except Yielded:
            log.info("Like-back stepped aside for a command; it runs again later.")
            return {"ok": False, "error": "A command from the console came first."}
        except NotLoggedIn as exc:
            await _set_login("facebook", False, "Log in on the screen.")
            return {"ok": False, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            why = _why(exc)
            if not check:
                await cbc.engage_done(act["kind"], str(target), error=why)
            return {"ok": False, "error": why, "shot": await shot(page, "facebook-engage-failed")}
        finally:
            state["busy"] = ""
            try:
                await page.close()
            except Exception:  # noqa: BLE001
                pass


async def comment_step(*, check: bool = False) -> dict[str, Any]:
    """One step of a post's comment thread: the choices and "can you solve
    it?", or — a minute later — the answer and its working with the card."""
    from .flows import fb_comments

    if URGENT["n"] and not check:
        return {"ok": False, "error": "A command from the console comes first."}
    job = await cbc.comments_next(check=check)
    if not job:
        return {"ok": False, "error": "No post to comment on."}
    if job.get("platform") != "facebook":
        await cbc.comments_done(job["post_id"], job["stage"], ok=False, error="Comments are set up for Facebook only.")
        return {"ok": False, "error": "Comments are set up for Facebook only."}
    image = ""
    images: list[str] = []
    if job.get("images") and not check:
        for k, link in enumerate(job["images"]):           # one picture per comment ("" for none)
            path = ""
            if link:
                try:
                    path = await cbc.download(link, _pic_name(f"card-{job['post_id']}-{k}", link))
                except Exception as exc:  # noqa: BLE001
                    log.info("No card %d for %s: %s", k, job["post_id"], _why(exc))
            images.append(path)
    elif job.get("image_url") and not check:
        try:
            image = await cbc.download(job["image_url"], _pic_name(f"answer-{job['post_id']}", job["image_url"]))
        except Exception as exc:  # noqa: BLE001
            log.info("No answer card for %s: %s", job["post_id"], _why(exc))
    async with browser.lock:
        state["busy"] = "Checking the comment box" if check else f"Commenting ({job['stage']}) on facebook"
        page = await browser.page()
        try:
            if job.get("stage") == "reconcile":
                # Every post on the profile, with its link: the server matches them
                # to the posts it has no link for, and their comments start.
                from .flows import fb_reconcile

                state["busy"] = "Reading the profile (matching posts to their links)"
                out = await fb_reconcile.harvest(page, scrolls=int(job.get("scrolls") or 160))
                got = await cbc.reconcile_done(out["items"])
                log.info("Reconciled: %s of %s post(s) seen matched; %s still without a link.",
                         got.get("matched"), got.get("seen"), got.get("left"))
                return {"ok": True, "message": f"Matched {got.get('matched')} post(s) to their links.", "shot": out.get("shot")}
            if job.get("stage") == "share":
                # The campaign's daily share of a post doing well, to the ticked groups.
                from .flows import fb_share

                out = await fb_share.share_post(page, find=job.get("find") or "", also=job.get("find_also") or [],
                                                groups=job.get("groups") or [], url=job.get("url") or "")
                await cbc.comments_done(job["post_id"], "share", ok=True, groups=out.get("groups") or [])
                log.info("Shared %s to %s", job["post_id"], out.get("groups"))
                count("shares")
                return {"ok": True, "message": f"Shared to {', '.join(out.get('groups') or [])}.", "shot": out.get("shot")}
            out = await fb_comments.comment(page, find=job.get("find") or "", url=job.get("url") or "",
                                            comments=job.get("comments") or [], image=image, check=check,
                                            also=job.get("find_also") or [], measure=bool(job.get("measure")),
                                            images=images or None)
            if not check:
                await cbc.comments_done(job["post_id"], job["stage"], ok=True, url=out.get("url") or "",
                                        metrics=out.get("metrics") or None)
            log.info("Comments %s on %s: %s", "checked" if check else job["stage"], job["post_id"], out)
            if not check:
                count("comments", len(job.get("comments") or []))
                if job.get("stage") == "measure":
                    count("readings")
            return {"ok": True, "message": ("Found the newest post and its comment box — see the screenshot."
                                            if check else f"Commented ({job['stage']})."), "shot": out.get("shot")}
        except Yielded:
            # Not reported: the post keeps its turn and is tried again shortly.
            log.info("Comments on %s stepped aside for a command; tried again shortly.", job["post_id"])
            return {"ok": False, "error": "A command from the console came first."}
        except NotLoggedIn as exc:
            await _set_login("facebook", False, "Log in on the screen.")
            return {"ok": False, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            why = _why(exc)
            if not check and job.get("stage") != "reconcile":      # a deep scroll that failed is tried again later
                await cbc.comments_done(job["post_id"], job["stage"], ok=False, error=why)
            log.info("Comments %s on %s failed: %s", job["stage"], job["post_id"], why)
            count("failures")
            return {"ok": False, "error": why, "shot": await shot(page, "facebook-comments-failed")}
        finally:
            state["busy"] = ""
            try:
                await page.close()
            except Exception:  # noqa: BLE001
                pass


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
            "last": state["last"], "platforms": list(FLOWS),
            "started": state["started"], "today": dict(state["today"]), "machine": _machine()}   # the newest poster is the active one (two Macs never both post)


async def do_login(platform: str) -> dict[str, Any]:
    """Open the platform's login page in the browser for the owner."""
    flow = FLOWS.get(platform)
    if flow is None:
        return {"ok": False, "error": "Unknown platform."}
    if config.POSTER_MODE == "local" and sys.platform == "darwin" and browser.channel != "chromium":
        # On a Mac, the login is done in ordinary Chrome, the way mac/login.sh
        # does it: the poster's own window says "controlled by automated test
        # software", and Facebook asks for more checks there or refuses. The
        # poster's Chrome closes, the same profile opens in plain Chrome, and
        # the poster carries on when that Chrome is quit (Cmd+Q).
        asyncio.create_task(_plain_chrome_login(flow.login_url, flow.platform))
        return {"ok": True, "message": (f"Chrome is open on the Mac at the {flow.platform} login. Log in there (answer any "
                                        "code or check), then quit Chrome with Cmd+Q — the poster carries on by itself.")}
    await browser.page(flow.login_url)
    where = "in Chrome on your Mac" if config.POSTER_MODE == "local" else "on the screen"
    return {"ok": True, "message": f"{flow.platform} login is open {where} — log in there, then press Check."}


async def _plain_chrome_login(url: str, platform: str) -> None:
    """Hold the poster while the owner logs in in ordinary Chrome; then check the login."""
    async with browser.lock:
        state["busy"] = f"Waiting for you to log in to {platform} — quit that Chrome (Cmd+Q) when done"
        await browser.close()
        await asyncio.sleep(2)                       # let Chrome release the profile
        try:
            proc = await asyncio.create_subprocess_exec(
                "open", "-n", "-W", "-a", "Google Chrome", "--args", f"--user-data-dir={config.PROFILE_DIR}",
                "--no-first-run", "--no-default-browser-check", url)
            await proc.wait()                        # back when that Chrome is quit
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not open Chrome for the login: %s", _why(exc))
        finally:
            state["busy"] = ""
    try:
        out = await do_check(platform)
        log.info("Login check for %s after the plain-Chrome login: %s", platform, out.get("message") or out.get("error"))
    except Exception as exc:  # noqa: BLE001
        log.info("Login check failed: %s", _why(exc))


# The cookies that keep each platform logged in, by the domains they belong to.
_DOMAINS = {"facebook": r"(^|\.)facebook\.com$", "instagram": r"(^|\.)instagram\.com$",
            "linkedin": r"(^|\.)linkedin\.com$", "tiktok": r"(^|\.)tiktok\.com$",
            "youtube": r"(^|\.)(youtube\.com|google\.com|accounts\.google\.com)$"}


async def do_logout(platform: str) -> dict[str, Any]:
    """Log this Mac out of one platform: its cookies cleared from the poster's profile."""
    import re

    if platform not in _DOMAINS:
        return {"ok": False, "error": "Unknown platform."}
    async with browser.lock:
        ctx = await browser.context()
        await ctx.clear_cookies(domain=re.compile(_DOMAINS[platform]))
    await _set_login(platform, False, "Logged out from the console.")
    state["logins"].get(platform, {}).pop("account", None)
    return {"ok": True, "message": f"This Mac is logged out of {platform}."}


def do_uninstall() -> dict[str, Any]:
    """Remove the poster from this Mac (its logins are kept) — asked for from the devices page."""
    import subprocess

    script = os.path.expanduser("~/.cbc/poster/uninstall.sh")
    if config.POSTER_MODE != "local" or not os.path.exists(script):
        return {"ok": False, "error": "Only a poster installed on a Mac can uninstall itself."}

    async def later() -> None:
        await asyncio.sleep(3)                          # the answer reaches the console first
        subprocess.Popen(["bash", script], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    asyncio.get_event_loop().create_task(later())
    return {"ok": True, "message": "The poster is removing itself from this Mac (its logins are kept). "
                                   "Install it again with the one-line command."}


async def do_check(platform: str = "") -> dict[str, Any]:
    platforms = [platform] if platform else list(FLOWS)
    out = {}
    async with browser.lock:
        for p in platforms:
            if p not in FLOWS:
                continue
            page = await browser.page()
            account = ""
            try:
                ok = await FLOWS[p].logged_in(page)
                if ok:
                    account = await _account_name(page, p)
            except Exception as exc:  # noqa: BLE001
                ok = False
                log.info("Check %s: %s", p, exc)
            finally:
                await page.close()
            await _set_login(p, ok, "" if ok else "Log in on the screen.")
            if account:
                state["logins"][p]["account"] = account
            out[p] = ok
    return {"ok": True, "logins": out}


async def _account_name(page: Any, platform: str) -> str:
    """Whose account this Mac is logged into: the name on its own profile page."""
    import re

    own = {"facebook": "https://www.facebook.com/me", "linkedin": "https://www.linkedin.com/in/me/",
           "instagram": "https://www.instagram.com/accounts/edit/", "youtube": "https://studio.youtube.com/",
           "tiktok": "https://www.tiktok.com/profile"}.get(platform)
    if not own:
        return ""
    try:
        await page.goto(own, wait_until="domcontentloaded", timeout=45_000)
        await asyncio.sleep(3)
        title = (await page.title()) or ""
        name = re.sub(r"\s*[|–-]\s*(Facebook|LinkedIn|Instagram|YouTube Studio|YouTube|TikTok).*$", "", title).strip()
        name = re.sub(r"^\(\d+\)\s*", "", name)                  # "(3) Jane Doe" — unread notifications
        return "" if name.lower() in ("", "facebook", "linkedin", "log in", "channel content") else name[:80]
    except Exception:  # noqa: BLE001
        return ""


async def do_dry_run(platform: str = "", post_id: str = "") -> dict[str, Any]:
    """Every step but the last, on the next queued post for a platform."""
    nxt = await cbc.next_post(platform=platform, post_id=post_id, dry=True)
    if not nxt.get("post"):
        return {"ok": False, "error": nxt.get("reason") or "Nothing queued for that platform."}
    return await publish(nxt["post"], dry_run=True)


def _pic_name(stem: str, url: str) -> str:
    """A picture's file name with its own kind — a GIF stays a .gif, so Facebook plays it."""
    return stem + (".gif" if url.lower().split("?")[0].endswith(".gif") else ".jpg")


async def make_card(question_id: str, step: str) -> None:
    """A card not made yet: this Mac's browser draws it from the server's page
    and sends it back — the server's queue is not waited on."""
    got = await cbc.card(question_id, step)
    if got.get("status") == "ready" or not got.get("html"):
        return
    async with browser.lock:
        page = await browser.page()
        try:
            await page.set_viewport_size({"width": int(got.get("width") or 1080), "height": int(got.get("height") or 1350)})
            await page.set_content(got["html"], wait_until="networkidle", timeout=45_000)
            try:
                await page.wait_for_function("window.__ready === true", timeout=8_000)
            except Exception:  # noqa: BLE001
                pass
            jpeg = await page.screenshot(type="jpeg", quality=90, full_page=False)
        finally:
            try:
                await page.close()
            except Exception:  # noqa: BLE001
                pass
    await cbc.card_upload(question_id, step, jpeg)
    log.info("Made the %s card of %s here and sent it to the server.", step, question_id)


async def series_now(options: dict[str, Any]) -> dict[str, Any]:
    """A question's whole series, now, one after the other: each card (made
    here if the server has not made it), then its walkthrough — a short pause
    between, like a person posting a thread of pictures."""
    if state["paused"]:
        return {"ok": False, "error": "The poster is paused — resume it first."}
    qid = str(options.get("question_id") or "")
    share = str(options.get("share") or "feed")
    picked = [str(g) for g in (options.get("groups") or [])][:9]
    said, posted = [], 0
    for k, (pid, step) in enumerate(zip(options.get("post_ids") or [], options.get("steps") or [])):
        if k:
            await asyncio.sleep(random.uniform(25, 50))
        try:
            if step != "walkthrough":
                await make_card(qid, step)
            nxt = await cbc.next_post(platform="facebook", post_id=pid, dry=True, share=share, groups=picked)
        except Exception as exc:  # noqa: BLE001
            said.append(f"{step}: {_why(exc)}")
            continue
        if not nxt.get("post"):
            said.append(f"{step}: {nxt.get('reason') or 'not ready'}")
            continue
        one = {**nxt["post"], "schedule_at": ""}
        if share == "feed":
            one["groups"] = []
        out = await publish(one, dry_run=False)
        posted += bool(out.get("ok"))
        said.append(f"{step}: {'posted' if out.get('ok') else out.get('error')}")
    return {"ok": posted > 0, "message": f"Series of {qid}: " + "; ".join(said),
            **({} if posted else {"error": "Nothing of the series went out — " + "; ".join(said)})}


async def post_now(platform: str = "", options: dict[str, Any] | None = None) -> dict[str, Any]:
    """The post-now buttons: the next queued post goes out live at once —
    not at its booked time, and without waiting out the gap.

    No `share` ("Post next now"): a post already due goes first, with any
    group share it carries; otherwise the next booked one on a platform
    logged in. `share` "feed": the feed only. `share` "groups": Facebook's
    feed and the next groups in turn, or the `groups` picked (5 at most)."""
    options = options or {}
    share = str(options.get("share") or "")
    wanted = str(options.get("post_id") or "")
    if wanted:
        # One booked post, now — a photo card or a video picked in the console.
        if state["paused"]:
            return {"ok": False, "error": "The poster is paused — resume it first."}
        nxt = await cbc.next_post(platform=platform, post_id=wanted, dry=True, share=share,
                                  groups=[str(g) for g in (options.get("groups") or [])][:9])
        if not nxt.get("post"):
            return {"ok": False, "error": nxt.get("reason") or "That post is not ready (its card or video is still being made)."}
        one = {**nxt["post"], "schedule_at": ""}
        if share == "feed":
            one["groups"] = []
        return await publish(one, dry_run=False)
    picked = [str(g) for g in (options.get("groups") or [])][:9]
    if state["paused"]:
        return {"ok": False, "error": "The poster is paused — resume it first."}
    why = ""
    if not share:
        done = await tick()
        if done.get("post_id"):
            return done
        why = done.get("skipped") or ""
    reasons: dict[str, str] = {}
    if share == "groups":
        platforms = ["facebook"]        # the only platform with groups
    else:
        platforms = [platform] if platform else sorted(FLOWS, key=lambda x: x != "facebook")   # Facebook first
    for p in platforms:
        if not platform and share != "groups" and state["logins"].get(p, {}).get("logged_in") is False:
            continue
        nxt = await cbc.next_post(platform=p, dry=True, share=share, groups=picked)
        if nxt.get("post"):
            post = {**nxt["post"], "schedule_at": ""}   # out now, live — never handed to a scheduler
            if share == "feed":
                post["groups"] = []
            return await publish(post, dry_run=False)
        if nxt.get("reason"):
            reasons[p] = nxt["reason"]
    # Facebook's reason first: it is where the videos go; another platform's
    # "nothing booked" said last used to hide it.
    why = reasons.get("facebook") or next(iter(reasons.values()), "") or why
    return {"ok": False, "error": why or "Nothing queued to post."}


async def schedule_now(count: int = 5) -> dict[str, Any]:
    """"Schedule now": hand the next `count` booked videos to Facebook's own
    scheduler, one after another, while today's limit has room."""
    if state["paused"]:
        return {"ok": False, "error": "The poster is paused — resume it first."}
    done, why = [], ""
    for _ in range(max(1, min(count, 30))):
        nxt = await cbc.next_post(platform="facebook", schedule=True)
        post = nxt.get("post")
        if not post:
            why = nxt.get("reason") or ""
            break
        out = await publish(post, dry_run=False)
        if not out.get("ok"):
            why = out.get("error") or "Facebook did not take it."
            break
        done.append(post.get("schedule_at") or "")
    if done:
        return {"ok": True, "message": f"Scheduled {len(done)} on Facebook" + (f" — {why}" if why else "."), "scheduled": len(done)}
    return {"ok": False, "error": why or "Nothing to schedule."}


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


async def run(action: str, platform: str = "", post_id: str = "",
              options: dict[str, Any] | None = None) -> dict[str, Any]:
    if action == "login":
        return await do_login(platform)
    if action == "check":
        return await do_check(platform)
    if action == "logout":
        return await do_logout(platform)
    if action == "uninstall":
        return do_uninstall()
    if action == "dry_run":
        return await do_dry_run(platform, post_id)
    if action == "comments_check":
        return await comment_step(check=True)
    if action == "engage_check":
        return await engage_step(check=True)
    if action == "schedule_now":
        return await schedule_now(int((options or {}).get("count") or 5))
    if action == "series_now":
        return await series_now(options or {})
    if action == "run_now":
        opts = dict(options or {})
        if post_id:
            opts.setdefault("post_id", post_id)      # one booked post, picked in the console
        return await post_now(platform, opts)
    if action in ("pause", "resume"):
        return set_paused(action == "pause")
    if action == "groups":
        return await do_groups(platform or "facebook")
    if action == "boost":
        return await boost_step(post_id, options or {})
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
    if action not in ("login", "check", "dry_run", "run_now", "schedule_now", "comments_check", "engage_check", "pause", "resume", "groups"):
        raise HTTPException(404, "No such action.")
    if action == "login" and str(body.get("platform") or "") not in FLOWS:
        raise HTTPException(400, "Unknown platform.")
    return await run(action, str(body.get("platform") or ""), str(body.get("post_id") or ""),
                     body.get("options") if isinstance(body.get("options"), dict) else None)


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
            await cbc.send_unsent()            # results kept while the server was not answering
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
            log.info("Command %s: %s %s %s", cmd["command_id"], cmd["action"], cmd.get("platform") or "",
                     cmd.get("options") or "")
            URGENT["n"] += 1                 # background work steps aside at its next safe point
            try:
                opts = cmd.get("options")
                result = await run(cmd["action"], cmd.get("platform") or "", cmd.get("post_id") or "",
                                   opts if isinstance(opts, dict) else None)
            except Exception as exc:  # noqa: BLE001
                result = {"ok": False, "error": _why(exc)[:400]}
            finally:
                URGENT["n"] = max(0, URGENT["n"] - 1)
            # Every command's outcome in the log — not only the ones that posted.
            log.info("Command %s done: %s", cmd["command_id"],
                     "ok" + (f" — {result.get('message')}" if result.get("message") else "") if result.get("ok")
                     else f"not done — {result.get('error') or result.get('skipped') or 'no reason given'}")
            try:
                await cbc.command_done(int(cmd["command_id"]), result)
                await cbc.heartbeat(status_now())     # the console sees the change at once
            except Exception as exc:  # noqa: BLE001
                log.warning("Could not report command %s: %s", cmd["command_id"], _why(exc))
            continue
        await asyncio.sleep(4)


async def _open_browser() -> None:
    """The poster's Chrome — waiting, not crashing, while the profile is open
    in another Chrome the owner is still using (a Log in window)."""
    from .browser import ProfileBusy

    while True:
        try:
            await browser.context()
            return
        except ProfileBusy as exc:
            state["note"] = str(exc)
            log.info("%s Trying again in 30 s.", exc)
            await asyncio.sleep(30)


async def main() -> None:
    _load()
    if config.POSTER_MODE == "local":
        if not config.CBC_API_KEY:
            raise SystemExit("CBC_API_KEY is not set — run the installer again, or add it to ~/.cbc/poster/.env.")
        for d in (config.PROFILE_DIR, config.SHOTS_DIR, config.TMP_DIR):
            os.makedirs(d, exist_ok=True)
        log.info("Local poster %s → %s", config.POSTER_ID, config.CBC_API_URL)
        await _open_browser()
        await asyncio.gather(checkin_loop(), command_loop(), loop())
        return
    await browser.context()          # the browser is on the screen from the start
    server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=config.CONTROL_PORT, log_level="warning"))
    await asyncio.gather(server.serve(), loop())


if __name__ == "__main__":
    asyncio.run(main())
