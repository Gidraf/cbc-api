"""What each model costs, read from the provider's own pricing page.

The price table in `cost_tracker` is typed in by hand from a page someone
pasted, and the page changes more often than anyone pastes it. A run priced at
last month's rate is a run whose cost is wrong in the one number an operator
checks, and a price cut nobody noticed is money left on the table.

So the page is read, not copied. It is also not trusted blindly: a page whose
layout changed can parse into nothing, or into zeros, and a price book that
believed it would make every run look free. A read that fails its checks
changes nothing and says why; the prices in force stay in force.
"""
from __future__ import annotations

import html
import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("cbc-price-book")

OPENAI_PRICING_URL = "https://developers.openai.com/api/docs/pricing"

# A read with fewer rows than this is a page that did not render the table.
MIN_ROWS = 3
# A price that moves more than this in one read is a parse error until a
# person says otherwise: providers cut prices by halves, not by factors of ten.
MAX_JUMP = 10.0

_TTL_SECONDS = 600.0
_cache: dict[str, dict[str, float]] = {}
_cache_at = 0.0
_lock = threading.Lock()


@dataclass(frozen=True)
class Price:
    model: str
    input: float
    cached: float | None
    cache_write: float | None
    output: float

    def to_dict(self) -> dict[str, Any]:
        return {"model": self.model, "input": self.input, "cached": self.cached,
                "cache_write": self.cache_write, "output": self.output}


# ── reading the page ────────────────────────────────────────────────────────

def _devalue(node: Any) -> Any:
    """Astro's island props: every value is `[type, value]`, 0 plain, 1 array."""
    if isinstance(node, list) and len(node) == 2 and node[0] in (0, 1):
        kind, value = node
        if kind == 1 and isinstance(value, list):
            return [_devalue(v) for v in value]
        if isinstance(value, dict):
            return {k: _devalue(v) for k, v in value.items()}
        return value
    if isinstance(node, dict):
        return {k: _devalue(v) for k, v in node.items()}
    return node


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def parse_openai(page: str, tier: str = "standard") -> list[Price]:
    """The text models on the page, at one processing tier.

    The flagship tables are islands with `tier` set ("standard", "batch",
    "flex", "fast") and rows of `[model, input, cached, cache writes,
    output]`, short context. Only the tier asked for is read.
    """
    out: dict[str, Price] = {}
    for match in re.finditer(r'<astro-island[^>]*?\sprops="([^"]*)"', page):
        try:
            props = _devalue(json.loads(html.unescape(match.group(1))))
        except (ValueError, TypeError):
            continue
        if not isinstance(props, dict) or props.get("tier") != tier:
            continue
        for row in props.get("rows") or []:
            if not isinstance(row, list) or len(row) < 5 or not isinstance(row[0], str):
                continue
            # "gpt-5.4 (<272K context length)": the note is not the id.
            model = re.sub(r"\s*\(.*\)\s*$", "", row[0]).strip()
            numbers = [_number(v) for v in row[1:5]]
            if not model or numbers[0] is None or numbers[3] is None:
                continue
            out.setdefault(model, Price(model=model, input=numbers[0], cached=numbers[1],
                                        cache_write=numbers[2], output=numbers[3]))
    return list(out.values())


def check(prices: list[Price], known: dict[str, dict[str, float]]) -> list[str]:
    """Why this read must not be believed, or [] when it can be."""
    problems: list[str] = []
    if len(prices) < MIN_ROWS:
        problems.append(f"only {len(prices)} model(s) read from the page; the layout may have changed")
    for price in prices:
        if price.input < 0 or price.output <= 0:
            problems.append(f"{price.model}: a price of ${price.input} in / ${price.output} out is not a price")
            continue
        before = known.get(price.model)
        if before and before.get("output"):
            ratio = price.output / float(before["output"])
            if ratio > MAX_JUMP or ratio < 1 / MAX_JUMP:
                problems.append(f"{price.model}: output went from ${before['output']} to "
                                f"${price.output} in one read")
    return problems


def fetch_page(url: str = OPENAI_PRICING_URL, timeout: float = 30.0) -> str:
    import httpx

    response = httpx.get(url, timeout=timeout, follow_redirects=True,
                         headers={"User-Agent": "Mozilla/5.0 (cbc-price-book)"})
    response.raise_for_status()
    return response.text


# ── storing ─────────────────────────────────────────────────────────────────

def known(provider: str = "openai") -> dict[str, dict[str, float]]:
    """Every stored price for a provider, by model."""
    from ..infra.db import fetch_all

    rows = fetch_all(
        "SELECT model, input_usd, cached_usd, cache_write_usd, output_usd, first_seen, last_seen "
        "FROM model_prices WHERE provider = :provider",
        {"provider": provider}) or []
    return {str(r["model"]): {
        "input": float(r["input_usd"]),
        "cached": float(r["cached_usd"]) if r.get("cached_usd") is not None else None,
        "cache_write": float(r["cache_write_usd"]) if r.get("cache_write_usd") is not None else None,
        "output": float(r["output_usd"]),
        "first_seen": r.get("first_seen"), "last_seen": r.get("last_seen"),
    } for r in rows}


def refresh(provider: str = "openai", page: str | None = None) -> dict[str, Any]:
    """Read the page and store what changed. Never raises.

    Returns what happened: new models, changed prices, and — when the read is
    not believed — the reasons, with nothing stored.
    """
    from ..infra.db import execute

    report: dict[str, Any] = {"provider": provider, "source": OPENAI_PRICING_URL,
                              "read": 0, "new": [], "changed": [], "problems": []}
    try:
        text = page if page is not None else fetch_page()
        prices = parse_openai(text)
    except Exception as exc:  # noqa: BLE001
        report["problems"] = [f"could not read the pricing page: {exc}"]
        return report

    report["read"] = len(prices)
    try:
        before = known(provider)
    except Exception as exc:  # noqa: BLE001
        report["problems"] = [f"could not read the stored prices: {exc}"]
        return report

    problems = check(prices, before)
    if problems:
        report["problems"] = problems
        logger.warning("Pricing page read not believed: %s", "; ".join(problems))
        return report

    for price in prices:
        old = before.get(price.model)
        params = {"provider": provider, "model": price.model, "input": price.input,
                  "cached": price.cached, "write": price.cache_write, "output": price.output,
                  "source": OPENAI_PRICING_URL}
        execute(
            """
            INSERT INTO model_prices (provider, model, input_usd, cached_usd, cache_write_usd,
                                      output_usd, source)
            VALUES (:provider, :model, :input, :cached, :write, :output, :source)
            ON CONFLICT (provider, model) DO UPDATE SET
                input_usd = EXCLUDED.input_usd, cached_usd = EXCLUDED.cached_usd,
                cache_write_usd = EXCLUDED.cache_write_usd, output_usd = EXCLUDED.output_usd,
                source = EXCLUDED.source, last_seen = NOW()
            """, params)
        changed = old is None or any(
            (old.get(k) is None) != (v is None) or (v is not None and abs(float(old[k]) - v) > 1e-9)
            for k, v in (("input", price.input), ("cached", price.cached),
                         ("cache_write", price.cache_write), ("output", price.output)))
        if changed:
            execute(
                """
                INSERT INTO model_price_history (provider, model, input_usd, cached_usd,
                                                 cache_write_usd, output_usd)
                VALUES (:provider, :model, :input, :cached, :write, :output)
                """, params)
            if old is None:
                report["new"].append(price.to_dict())
            else:
                report["changed"].append({**price.to_dict(),
                                          "was": {"input": old["input"], "output": old["output"]}})
    invalidate()
    return report


# ── pricing a call ──────────────────────────────────────────────────────────

def invalidate() -> None:
    global _cache_at
    _cache_at = 0.0


def rates(model: str, provider: str = "openai") -> dict[str, float] | None:
    """The stored rate for a model, in the shape `cost_tracker` uses, or None.

    Cached for ten minutes: this is asked on every model call.
    """
    global _cache_at
    with _lock:
        if time.time() - _cache_at > _TTL_SECONDS:
            try:
                fresh = known(provider)
                _cache.clear()
                for name, row in fresh.items():
                    rate = {"input": row["input"], "output": row["output"]}
                    if row.get("cached") is not None:
                        rate["cached"] = row["cached"]
                    _cache[name] = rate
            except Exception as exc:  # noqa: BLE001
                logger.debug("Stored prices not readable (%s); using the built-in table.", exc)
            _cache_at = time.time()
        if model in _cache:
            return _cache[model]
        # A dated snapshot of a stored model: "gpt-6-luna-2026-09-01".
        for name in sorted(_cache, key=len, reverse=True):
            if model.startswith(name + "-"):
                return _cache[name]
        return None
