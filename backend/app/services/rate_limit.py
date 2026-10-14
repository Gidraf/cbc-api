"""How often a thing may be tried: logins, sign-ups, M-Pesa prompts, API calls.

A sliding window per key, kept in this process (the API runs as one), so it
costs nothing per request and needs no Redis. Over the limit, the caller gets
429 with how long to wait. A restart forgets the windows — acceptable for
limits meant to stop guessing and flooding, not to bill.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any

from ..errors import raise_api_error

_lock = threading.Lock()
_hits: dict[str, deque[float]] = {}
_MAX_KEYS = 50_000

# name: (how many, in how many seconds)
LIMITS: dict[str, tuple[int, int]] = {
    "login_user": (10, 15 * 60),        # wrong or right, per username
    "login_ip": (60, 15 * 60),          # per address, across usernames
    "register_ip": (5, 60 * 60),
    "register_all": (200, 60 * 60),     # everyone together: a flood of sign-ups
    "topup_owner": (5, 10 * 60),        # M-Pesa prompts an account may send
    "topup_phone": (3, 10 * 60),        # prompts one phone may receive
    "content_key": (120, 60),           # developer API calls, per account
    "link_owner": (10, 60 * 60),        # install links made
    "test_start_ip": (150, 10 * 60),    # students opening tests from one address (a whole class shares one)
    "test_code_ip": (60, 10 * 60),      # test codes looked up: no guessing them
    "watch_owner": (300, 60 * 60),      # video links handed out
    "forgot_ip": (10, 60 * 60),         # reset emails asked for, per address
    "forgot_who": (3, 60 * 60),         # ... and per username or email: no inbox flooding
    "email_link_ip": (30, 15 * 60),     # reset / confirm links tried: no guessing them
    "confirm_owner": (5, 60 * 60),      # confirm emails an account may resend
}


def _prune(now: float) -> None:
    if len(_hits) < _MAX_KEYS:
        return
    longest = max(w for _, w in LIMITS.values())
    for key in [k for k, q in _hits.items() if not q or now - q[-1] > longest]:
        _hits.pop(key, None)


def hit(name: str, who: str, *, cost: int = 1) -> None:
    """Count one try for `who` under the limit `name`; 429 if over it."""
    limit, window = LIMITS[name]
    key = f"{name}:{who}"
    now = time.monotonic()
    with _lock:
        _prune(now)
        q = _hits.setdefault(key, deque())
        while q and now - q[0] > window:
            q.popleft()
        if len(q) + cost > limit:
            wait = int(window - (now - q[0])) + 1 if q else window
            raise_api_error("RATE_LIMITED", f"Too many tries. Wait {_human(wait)} and try again.",
                            detail={"retry_after_seconds": wait})
        for _ in range(cost):
            q.append(now)


def clear(name: str, who: str) -> None:
    """Forget the tries (a login that succeeded)."""
    with _lock:
        _hits.pop(f"{name}:{who}", None)


def reset_all() -> None:
    with _lock:
        _hits.clear()


def client_ip(request: Any) -> str:
    """The caller's address. Behind our own proxies (nginx on the host, then
    the console's proxy) the last address they added is the real one; a
    value the caller put in X-Forwarded-For themselves sits further left
    and is never trusted."""
    peer = getattr(getattr(request, "client", None), "host", "") or ""
    forwarded = [p.strip() for p in str(request.headers.get("x-forwarded-for", "")).split(",") if p.strip()]
    if forwarded and _private(peer):
        # Walk back through our own hops; the first public address is the client.
        for addr in reversed(forwarded):
            if not _private(addr):
                return addr
        return forwarded[0]
    return peer or "unknown"


def _private(addr: str) -> bool:
    import ipaddress

    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback


def _human(seconds: int) -> str:
    return f"{seconds} seconds" if seconds < 90 else f"{round(seconds / 60)} minutes"
