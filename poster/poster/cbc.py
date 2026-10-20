"""The CBC API, from the poster's side: what to post, and how it went."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

import httpx

from . import config

log = logging.getLogger("poster")

# The server can be slow to answer while it renders: a timeout or a dropped
# connection is tried again, with growing waits, before it counts as failed.
WAITS = (2, 5, 10, 20)
TRANSIENT = (httpx.ConnectTimeout, httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout,
             httpx.PoolTimeout, httpx.RemoteProtocolError)


def _headers() -> dict[str, str]:
    return {"X-API-Key": config.CBC_API_KEY}


async def _call(method: str, path: str, *, timeout: float = 30, waits: tuple[int, ...] | None = None,
                **kw: Any) -> httpx.Response:
    """One request to the API, tried again on a timeout, a lost connection or
    a 502/503/504 (the proxy saying the API is busy)."""
    waits = WAITS if waits is None else waits
    for attempt in range(len(waits) + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.request(method, f"{config.CBC_API_URL}{path}", headers=_headers(), **kw)
            if r.status_code in (502, 503, 504) and attempt < len(waits):
                raise httpx.RemoteProtocolError(f"the API answered {r.status_code}")
            r.raise_for_status()
            return r
        except TRANSIENT as exc:
            if attempt >= len(waits):
                raise
            log.info("API %s %s: %s — trying again in %ss", method, path, type(exc).__name__, waits[attempt])
            await asyncio.sleep(waits[attempt])
    raise RuntimeError("unreachable")


async def next_post(*, platform: str = "", post_id: str = "", dry: bool = False, share: str = "",
                    groups: list[str] | None = None, schedule: bool = False) -> dict[str, Any]:
    params: dict[str, Any] = {"platform": platform, "post_id": post_id, "dry": str(dry).lower(),
                              "poster_id": config.POSTER_ID}
    if schedule:                    # "Schedule now": the next booking for Facebook's scheduler
        params["schedule"] = "true"
    if share:                       # a post-now button: the feed only, or the feed and groups
        params.update(share=share, groups=list(groups or []))
    return (await _call("GET", "/api/v1/play/poster/next", timeout=60, params=params)).json()


def _unsent_path() -> str:
    return os.path.join(os.path.dirname(config.SHOTS_DIR.rstrip("/")) or ".", "unsent_results.json")


def _unsent() -> list[dict[str, Any]]:
    try:
        with open(_unsent_path()) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return []


def _save_unsent(items: list[dict[str, Any]]) -> None:
    try:
        with open(_unsent_path(), "w") as fh:
            json.dump(items[-200:], fh)
    except OSError as exc:
        log.warning("Could not keep the unsent results: %s", exc)


async def report(post_id: str, *, ok: bool, url: str = "", error: str = "", dry_run: bool = False,
                 scheduled: bool = False, groups: list[str] | None = None,
                 destinations: list[str] | None = None) -> None:
    """How a post went. It MUST reach the server — a post it never hears of
    would be posted again — so one that cannot be sent is kept on disk and
    sent later (send_unsent)."""
    body = {"post_id": post_id, "ok": ok, "url": url, "error": error[:900], "dry_run": dry_run,
            "scheduled": scheduled, "groups": groups or [], "destinations": destinations or []}
    try:
        await _call("POST", "/api/v1/play/poster/result", json=body)
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not report %s now (%s): kept, to send when the server answers.", post_id, type(exc).__name__)
        _save_unsent(_unsent() + [body])


async def send_unsent() -> int:
    """Results kept while the server was not answering, sent now."""
    items = _unsent()
    if not items:
        return 0
    left = []
    for body in items:
        try:
            await _call("POST", "/api/v1/play/poster/result", json=body, waits=WAITS[:1])
        except Exception:  # noqa: BLE001
            left.append(body)
    _save_unsent(left)
    sent = len(items) - len(left)
    if sent:
        log.info("Sent %d result(s) kept while the server was not answering.", sent)
    return sent


async def comments_next(*, check: bool = False) -> dict[str, Any] | None:
    """The next comment step under a post that is out (or, `check`, the newest post)."""
    r = await _call("GET", "/api/v1/play/poster/comments/next", timeout=60,
                    params={"poster_id": config.POSTER_ID, "check": str(check).lower()})
    return r.json().get("job")


async def comments_done(post_id: str, stage: str, *, ok: bool, error: str = "", url: str = "",
                        metrics: dict[str, int] | None = None, groups: list[str] | None = None) -> None:
    await _call("POST", "/api/v1/play/poster/comments/result",
                json={"post_id": post_id, "stage": stage, "ok": ok, "error": error[:900], "url": url,
                      **({"metrics": metrics} if metrics else {}), **({"groups": groups} if groups else {})})


async def reconcile_done(items: list[dict[str, str]]) -> dict[str, Any]:
    """Every post seen on the profile, for the server to match to the posts it has no link for."""
    r = await _call("POST", "/api/v1/play/poster/reconcile", json={"items": items[:2000]}, timeout=120)
    return r.json()


async def card(question_id: str, step: str) -> dict[str, Any]:
    """A card: its picture's link if made, else its page (HTML) to photograph here."""
    r = await _call("GET", "/api/v1/play/poster/card", timeout=60, params={"question_id": question_id, "step": step})
    return r.json()


async def card_upload(question_id: str, step: str, jpeg: bytes) -> dict[str, Any]:
    """A card this Mac photographed, sent to the server to keep."""
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(f"{config.CBC_API_URL}/api/v1/play/poster/card", headers=_headers(),
                              data={"question_id": question_id, "step": step},
                              files={"file": (f"{step}.jpg", jpeg, "image/jpeg")})
        r.raise_for_status()
        return r.json()


async def linkedin_next() -> dict[str, Any] | None:
    """The next developer-studio post for LinkedIn: a document (PDF) or a video."""
    r = await _call("GET", "/api/v1/dev/linkedin/next", timeout=60, params={"poster_id": config.POSTER_ID})
    return r.json().get("post")


async def linkedin_done(post_id: str, *, ok: bool, url: str = "", error: str = "") -> None:
    await _call("POST", f"/api/v1/dev/linkedin/{post_id}/done", json={"ok": ok, "url": url, "error": error[:450]})


async def engage_next() -> dict[str, Any]:
    """The next like-back step (read a post's comments, or like a person's posts), or why none."""
    r = await _call("GET", "/api/v1/play/poster/engage/next", timeout=60, params={"poster_id": config.POSTER_ID})
    return r.json()


async def engage_done(kind: str, target: str, *, likes: int = 0, people: list[dict[str, str]] | None = None,
                      error: str = "", groups: list[dict[str, Any]] | None = None, result: str = "",
                      replied: list[str] | None = None) -> None:
    await _call("POST", "/api/v1/play/poster/engage/result",
                json={"kind": kind, "target": target, "likes": likes, "people": people or [], "error": error[:500],
                      **({"groups": groups[:100]} if groups else {}), **({"result": result} if result else {}),
                      **({"replied": replied[:20]} if replied else {})})


async def groups_found(platform: str, names: list[str]) -> list[dict[str, Any]]:
    r = await _call("POST", "/api/v1/play/poster/groups/found", json={"platform": platform, "names": names})
    return r.json().get("groups", [])


async def login_state(platform: str, logged_in: bool, note: str = "") -> None:
    await _call("POST", "/api/v1/play/poster/state", json={"platform": platform, "logged_in": logged_in, "note": note[:300]})


async def heartbeat(status: dict[str, Any]) -> None:
    async with httpx.AsyncClient(timeout=20) as client:
        await client.post(f"{config.CBC_API_URL}/api/v1/play/poster/heartbeat", headers=_headers(),
                          json={"poster_id": config.POSTER_ID, "status": status})


async def take_command() -> dict[str, Any] | None:
    r = await _call("POST", "/api/v1/play/poster/commands/next", timeout=20, waits=WAITS[:2],
                    params={"poster_id": config.POSTER_ID})
    return r.json().get("command")


async def command_done(command_id: int, result: dict[str, Any]) -> None:
    await _call("POST", f"/api/v1/play/poster/commands/{command_id}/done", timeout=20, json={"result": result})


async def upload_shot(name: str) -> None:
    path = os.path.join(config.SHOTS_DIR, name)
    if not name or not os.path.exists(path):
        return
    async with httpx.AsyncClient(timeout=60) as client:
        with open(path, "rb") as fh:
            await client.post(f"{config.CBC_API_URL}/api/v1/play/poster/shots", headers=_headers(),
                              files={"file": (name, fh, "image/png")})


def internal(url: str) -> str:
    """A stored file's link, fetched through the API the poster talks to —
    inside the stack's network on the server, over the domain on a Mac."""
    marker = "/api/v1/assets/"
    return config.CBC_API_URL + url[url.index(marker):] if marker in url else url


async def download(url: str, name: str) -> str:
    os.makedirs(config.TMP_DIR, exist_ok=True)
    path = os.path.join(config.TMP_DIR, name)
    for attempt, wait in enumerate((*WAITS, None)):
        try:
            async with httpx.AsyncClient(timeout=300, follow_redirects=True) as client:
                async with client.stream("GET", internal(url), headers=_headers()) as r:
                    r.raise_for_status()
                    with open(path, "wb") as fh:
                        async for chunk in r.aiter_bytes(1 << 16):
                            fh.write(chunk)
            break
        except TRANSIENT as exc:
            if wait is None:
                raise
            log.info("Downloading %s: %s — trying again in %ss", name, type(exc).__name__, wait)
            await asyncio.sleep(wait)
    return path
