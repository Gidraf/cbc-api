"""Book the next weeks for the auto-poster, from the Mac on a schedule.

    python -m poster.book            book (what the scheduled task runs)
    python -m poster.book --preview  show the plan, book nothing

The scope and pace come from the environment (~/.cbc/poster/book.env):
BOOK_GRADE, BOOK_SUBJECT, BOOK_SUB_STRAND (empty = the whole subject),
BOOK_DAYS, BOOK_LOW, BOOK_HIGH, BOOK_PLATFORMS. The server keeps the rules:
it fills from the day after the last booked post up to BOOK_DAYS ahead, so
running this every two weeks or every month only tops the calendar up.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

try:
    import truststore

    truststore.inject_into_ssl()
except ImportError:
    pass

import httpx

from . import config


def _settings(preview: bool) -> dict:
    platforms = [p.strip().lower() for p in os.getenv("BOOK_PLATFORMS", "facebook").replace(",", " ").split() if p.strip()]
    return {"grade": os.getenv("BOOK_GRADE", "grade-9"), "subject": os.getenv("BOOK_SUBJECT", "Mathematics"),
            "sub_strand": os.getenv("BOOK_SUB_STRAND", ""), "days": int(os.getenv("BOOK_DAYS", "25")),
            "low": int(os.getenv("BOOK_LOW", "5")), "high": int(os.getenv("BOOK_HIGH", "15")),
            "platforms": platforms, "dry": preview}


def _notify(text: str) -> None:
    """A macOS notification, so a scheduled run is seen without opening a log."""
    script = f"display notification {json.dumps(text)} with title \"CBC auto-poster\""
    try:
        subprocess.run(["osascript", "-e", script], check=False, timeout=10, capture_output=True)
    except Exception:  # noqa: BLE001
        pass


def summary(out: dict) -> str:
    if not out.get("posts"):
        return (out.get("notes") or ["Nothing to add."])[0]
    head = (f"{'Booked' if out.get('booked') else 'Preview'}: {out['videos']} videos, {out['posts']} posts, "
            f"{out['first_day']} → {out['last_day']}")
    if out.get("to_render"):
        head += f"; {out['to_render']} videos {'queued to be made' if out.get('booked') else 'to make'}"
    return head + "".join(f"\n  note: {n}" for n in out.get("notes") or [])


def main(argv: list[str]) -> int:
    preview = "--preview" in argv
    if not config.CBC_API_KEY:
        print("CBC_API_KEY is not set (~/.cbc/poster/.env).", file=sys.stderr)
        return 2
    body = _settings(preview)
    try:
        r = httpx.post(f"{config.CBC_API_URL}/api/v1/play/social/book", json=body,
                       headers={"X-API-Key": config.CBC_API_KEY}, timeout=600)
    except httpx.HTTPError as exc:
        msg = f"Could not reach {config.CBC_API_URL}: {type(exc).__name__} {exc}"
        print(msg, file=sys.stderr)
        _notify("Booking failed — " + msg[:120])
        return 1
    if r.status_code == 404:
        msg = "The server has no booking yet — deploy it (git pull && docker compose up -d --build)."
    elif r.status_code in (401, 403):
        msg = "The CBC API refused the key (run poster/mac/install.sh --reconfigure)."
    elif r.status_code in (502, 503, 504):
        msg = f"The server is not answering ({r.status_code}) — it may be restarting. The next run will try again."
    elif r.status_code >= 400:
        try:
            msg = "; ".join(e.get("message", "") for e in r.json().get("errors", [])) or r.text[:200]
        except ValueError:
            msg = r.text[:200]
        msg = f"Booking failed ({r.status_code}): {msg}"
    else:
        out = r.json()
        print(f"{body['grade']} {body['subject']}{' / ' + body['sub_strand'] if body['sub_strand'] else ''} "
              f"on {', '.join(body['platforms'])}")
        print(summary(out))
        for d in out.get("days", []):
            print(f"  {d['date']}  {d['videos']:>2} videos  {' '.join(t.split()[0] for t in d['times'])}")
        if not preview:
            _notify(summary(out).splitlines()[0])
        return 0
    print(msg, file=sys.stderr)
    if not preview:
        _notify(msg)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
