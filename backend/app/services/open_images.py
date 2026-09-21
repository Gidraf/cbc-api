"""A photograph where a drawing would be worse.

A number line, a bar chart, a thermometer: drawn, exactly. A maize plant, a
Maasai shuka, a matatu, the Nairobi skyline: no line drawing a model
produces looks like one, and a Grade 4 paper that says "look at the picture
below" wants a picture. Wikimedia Commons holds millions under licences that
allow reuse with attribution, reachable without a key.

Fetched once, filed in the diagram registry as an SVG that embeds the image
and prints its attribution beneath, so every paper afterwards reuses the
file and nothing calls Commons twice for the same thing.
"""
from __future__ import annotations

import base64
import json
import logging
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger("cbc-open-images")

API = "https://commons.wikimedia.org/w/api.php"
UA = "CBC-Factory/1.0 (Kenyan curriculum assessment platform; educational use)"
WIDTH = 720
MAX_BYTES = 400_000
# Licences a printed paper may carry with a credit line.
ALLOWED = ("cc0", "public domain", "cc by", "cc-by", "cc by-sa", "cc-by-sa", "pd")


def search(query: str, *, limit: int = 6) -> list[dict[str, Any]]:
    """Candidate photographs for a query, most relevant first, with their
    licence and author — only bitmaps, only reusable licences."""
    params = {
        "action": "query", "format": "json", "generator": "search", "gsrnamespace": "6",
        "gsrsearch": f"{query} filetype:bitmap", "gsrlimit": str(limit * 2),
        "prop": "imageinfo", "iiprop": "url|extmetadata|mime|size", "iiurlwidth": str(WIDTH),
    }
    req = urllib.request.Request(API + "?" + urllib.parse.urlencode(params), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    out: list[dict[str, Any]] = []
    for page in (data.get("query") or {}).get("pages", {}).values():
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        licence = str((meta.get("LicenseShortName") or {}).get("value") or "").strip()
        if not info.get("thumburl") or not str(info.get("mime") or "").startswith("image/"):
            continue
        if not any(tag in licence.lower() for tag in ALLOWED):
            continue
        author = _plain(str((meta.get("Artist") or {}).get("value") or ""))
        out.append({
            "title": str(page.get("title") or "").replace("File:", ""),
            "thumb": info["thumburl"], "page": info.get("descriptionurl") or "",
            "licence": licence, "author": author[:80], "mime": info.get("mime"),
            "width": info.get("thumbwidth"), "height": info.get("thumbheight"),
        })
        if len(out) >= limit:
            break
    return out


def _plain(html: str) -> str:
    import re

    return re.sub(r"<[^>]+>", "", html).strip()


def fetch(query: str) -> dict[str, Any] | None:
    """The best photograph for the query as an SVG that embeds it with its
    credit line, or None when Commons has nothing usable."""
    try:
        candidates = search(query)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Commons search for %r failed: %s", query, exc)
        return None
    for cand in candidates:
        try:
            req = urllib.request.Request(cand["thumb"], headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as resp:
                body = resp.read(MAX_BYTES + 1)
                mime = resp.headers.get("Content-Type", cand.get("mime") or "image/jpeg").split(";")[0]
        except Exception as exc:  # noqa: BLE001
            logger.info("Could not fetch %s: %s", cand["thumb"], exc)
            continue
        if len(body) > MAX_BYTES:
            continue
        w = int(cand.get("width") or WIDTH)
        h = int(cand.get("height") or int(WIDTH * 0.66))
        credit = f"{cand['title']} — {cand['author'] or 'Wikimedia Commons'} · {cand['licence']}"
        data = base64.b64encode(body).decode("ascii")
        svg = (f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {w} {h + 22}' role='img' "
               f"aria-label='{_esc(query)}'>"
               f"<image href='data:{mime};base64,{data}' x='0' y='0' width='{w}' height='{h}' "
               f"preserveAspectRatio='xMidYMid meet'/>"
               f"<text x='4' y='{h + 15}' font-size='11' fill='#444' font-family='Helvetica, Arial, sans-serif'>"
               f"{_esc(credit[:140])}</text></svg>")
        return {"svg": svg, "title": query, "alt_text": f"Photograph: {cand['title']}", "kind": "image",
                "credit": credit, "source": cand.get("page") or cand["thumb"], "licence": cand["licence"],
                "scene": {"title": query, "parts": [{"label": credit, "role": "credit", "assessable": False,
                                                     "occludable": False, "function": "", "alt_text": credit}]}}
    return None


def _esc(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace("'", "&#39;").replace('"', "&quot;"))
