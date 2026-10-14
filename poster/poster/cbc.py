"""The CBC API, from the poster's side: what to post, and how it went."""
from __future__ import annotations

import os
from typing import Any

import httpx

from . import config


def _headers() -> dict[str, str]:
    return {"X-API-Key": config.CBC_API_KEY}


async def next_post(*, platform: str = "", post_id: str = "", dry: bool = False, share: str = "",
                    groups: list[str] | None = None) -> dict[str, Any]:
    params: dict[str, Any] = {"platform": platform, "post_id": post_id, "dry": str(dry).lower()}
    if share:                       # a post-now button: the feed only, or the feed and groups
        params.update(share=share, groups=list(groups or []))
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(f"{config.CBC_API_URL}/api/v1/play/poster/next", params=params, headers=_headers())
        r.raise_for_status()
        return r.json()


async def report(post_id: str, *, ok: bool, url: str = "", error: str = "", dry_run: bool = False,
                 scheduled: bool = False, groups: list[str] | None = None,
                 destinations: list[str] | None = None) -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{config.CBC_API_URL}/api/v1/play/poster/result", headers=_headers(),
                              json={"post_id": post_id, "ok": ok, "url": url, "error": error[:900], "dry_run": dry_run,
                                    "scheduled": scheduled, "groups": groups or [],
                                    "destinations": destinations or []})
        r.raise_for_status()


async def groups_found(platform: str, names: list[str]) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{config.CBC_API_URL}/api/v1/play/poster/groups/found", headers=_headers(),
                              json={"platform": platform, "names": names})
        r.raise_for_status()
        return r.json().get("groups", [])


async def login_state(platform: str, logged_in: bool, note: str = "") -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        await client.post(f"{config.CBC_API_URL}/api/v1/play/poster/state", headers=_headers(),
                          json={"platform": platform, "logged_in": logged_in, "note": note[:300]})


async def heartbeat(status: dict[str, Any]) -> None:
    async with httpx.AsyncClient(timeout=20) as client:
        await client.post(f"{config.CBC_API_URL}/api/v1/play/poster/heartbeat", headers=_headers(),
                          json={"poster_id": config.POSTER_ID, "status": status})


async def take_command() -> dict[str, Any] | None:
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(f"{config.CBC_API_URL}/api/v1/play/poster/commands/next", headers=_headers())
        r.raise_for_status()
        return r.json().get("command")


async def command_done(command_id: int, result: dict[str, Any]) -> None:
    async with httpx.AsyncClient(timeout=20) as client:
        await client.post(f"{config.CBC_API_URL}/api/v1/play/poster/commands/{command_id}/done",
                          headers=_headers(), json={"result": result})


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
    async with httpx.AsyncClient(timeout=300, follow_redirects=True) as client:
        async with client.stream("GET", internal(url), headers=_headers()) as r:
            r.raise_for_status()
            with open(path, "wb") as fh:
                async for chunk in r.aiter_bytes(1 << 16):
                    fh.write(chunk)
    return path
