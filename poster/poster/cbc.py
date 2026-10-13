"""The CBC API, from the poster's side: what to post, and how it went."""
from __future__ import annotations

import os
from typing import Any

import httpx

from . import config


def _headers() -> dict[str, str]:
    return {"X-API-Key": config.CBC_API_KEY}


async def next_post(*, platform: str = "", post_id: str = "", dry: bool = False) -> dict[str, Any]:
    params = {"platform": platform, "post_id": post_id, "dry": str(dry).lower()}
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(f"{config.CBC_API_URL}/api/v1/play/poster/next", params=params, headers=_headers())
        r.raise_for_status()
        return r.json()


async def report(post_id: str, *, ok: bool, url: str = "", error: str = "", dry_run: bool = False) -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        await client.post(f"{config.CBC_API_URL}/api/v1/play/poster/result", headers=_headers(),
                          json={"post_id": post_id, "ok": ok, "url": url, "error": error[:900], "dry_run": dry_run})


async def login_state(platform: str, logged_in: bool, note: str = "") -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        await client.post(f"{config.CBC_API_URL}/api/v1/play/poster/state", headers=_headers(),
                          json={"platform": platform, "logged_in": logged_in, "note": note[:300]})


def internal(url: str) -> str:
    """A stored file's public link, fetched inside the network instead."""
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
