"""One place a diagram's SVG comes from.

The markup was stored twice: `diagram_registry.svg_markup` held the text and
`storage_url` pointed at the same bytes in MinIO. Two copies with nothing
keeping them in step — edit the object and the column is stale, edit the column
and the served file is stale, and nothing anywhere says which one a reader got.

MinIO is the copy now. A diagram is a file: it is served to a browser, embedded
in a printed paper, and never queried a field at a time. What Postgres keeps is
what Postgres is for — the identity, the scene document that says which region
is which, the alt text, the reuse count, and the link.

Rows written before this still carry their markup. They are read from the column
until the sweep in data_repairs has put them in MinIO, so the change is not a
flag day: nothing has to be migrated before anything can be read.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("cbc-diagram-svg")

# Rendering an exam fetches every diagram on the paper, and a paper reuses the
# same diagram across variants. Small, because SVGs are text and a hundred of
# them is a few megabytes.
_CACHE_LIMIT = 128
_cache: dict[str, str] = {}


def svg_for(row: dict[str, Any]) -> str:
    """The markup for one diagram row, from wherever it actually is.

    Order matters: the column FIRST, because a row that still has it has not
    been swept yet and its object may not exist. Once swept the column is empty
    and this falls through to the file.
    """
    if not isinstance(row, dict):
        return ""

    stored = str(row.get("svg_markup") or "")
    if stored:
        return stored

    url = str(row.get("storage_url") or "")
    if not url:
        return ""

    if url in _cache:
        return _cache[url]

    from ..infra.storage import object_storage

    markup = object_storage.read_text(object_storage.object_name_of(url))
    if markup:
        if len(_cache) >= _CACHE_LIMIT:
            _cache.clear()
        _cache[url] = markup
    else:
        logger.warning(
            "Diagram %s has no markup in the column and none at %s.",
            row.get("diagram_id"), url,
        )
    return markup


def with_svg(row: dict[str, Any]) -> dict[str, Any]:
    """The row, with `svg_markup` filled in for a caller that expects it."""
    if not isinstance(row, dict):
        return row
    return {**row, "svg_markup": svg_for(row)}


def forget(url: str = "") -> None:
    """Drop a cached SVG, or all of them, after one is rewritten."""
    if url:
        _cache.pop(url, None)
    else:
        _cache.clear()
