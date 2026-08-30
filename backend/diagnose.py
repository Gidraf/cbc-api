#!/usr/bin/env python3
"""Is the code you edited the code that is running?

Four rounds went on one error that was fixed after the first. Every round the
same question went unanswered: is this a live fault, or a process running an
older build? Nothing on either side could tell them apart.

    python diagnose.py            # what THIS checkout contains
    python diagnose.py --api      # ...and what the running API reports
    python diagnose.py --jobs     # ...and which failures are still on the board
    python diagnose.py --models   # ...and which models each provider will serve

Run it inside the container to see what the container has:

    docker compose exec api python diagnose.py
    docker compose exec generation-worker python diagnose.py
"""
from __future__ import annotations

import sys


def main() -> int:
    print("=" * 62)
    print("SOURCE IN THIS CHECKOUT")
    print("=" * 62)

    ok = True
    try:
        from app.services.generation_version import VERSION
        print(f"  generator build          {VERSION}")
    except Exception as exc:  # noqa: BLE001
        print(f"  generator build          UNAVAILABLE ({exc})")
        ok = False

    try:
        import app.routes.curriculum as curriculum

        registered = curriculum._QUEUEABLE.get("notes")
        if isinstance(registered, tuple):
            endpoint, model = registered
            print(f"  notes station            {endpoint} -> {model.__name__}")
            print("  payload resolution       explicit (no annotation lookup)")
            print("\n  This source CANNOT raise "
                  "\"'str' object has no attribute 'model_fields'\".")
        else:
            print(f"  notes station            {registered!r}")
            print("  payload resolution       FROM ANNOTATIONS — old build")
            print("\n  This source CAN raise "
                  "\"'str' object has no attribute 'model_fields'\".")
            ok = False
    except Exception as exc:  # noqa: BLE001
        print(f"  routes                   UNAVAILABLE ({exc})")
        ok = False

    try:
        from app.routes import artifacts

        bad = [
            kind for kind, plan in artifacts._REGENERATORS.items()
            if not hasattr(getattr(curriculum, plan.get("request", ""), None),
                           "model_fields")
        ]
        if "request" not in next(iter(artifacts._REGENERATORS.values()), {}):
            print("  regeneration path        FROM ANNOTATIONS — old build")
            print("\n  This source CAN raise the model_fields error when you "
                  "regenerate.")
            ok = False
        elif bad:
            print(f"  regeneration path        BROKEN for {', '.join(bad)}")
            ok = False
        else:
            print("  regeneration path        explicit (no annotation lookup)")
    except Exception as exc:  # noqa: BLE001
        print(f"  regeneration path        UNAVAILABLE ({exc})")
        ok = False

    # A failed job row lives for ever. Four rounds went on this error partly
    # because the console kept showing a failure that had already been fixed —
    # nothing on the panel says WHEN a job failed relative to the build.
    if "--jobs" in sys.argv:
        print()
        print("=" * 62)
        print("FAILURES STILL ON THE BOARD")
        print("=" * 62)
        try:
            from app.infra.db import fetch_all

            rows = fetch_all(
                "SELECT job_id, kind, sub_strand, finished_at, error "
                "FROM jobs WHERE status = 'failed' "
                "ORDER BY finished_at DESC NULLS LAST LIMIT 20"
            ) or []
            if not rows:
                print("  none — the board is clear.")
            for r in rows:
                when = r.get("finished_at")
                print(f"  {str(when)[:19]:20s} {str(r.get('kind')):12s} "
                      f"{str(r.get('sub_strand'))[:24]:26s} "
                      f"{str(r.get('error'))[:60]}")
            print("\n  Compare the newest timestamp against 'process started'")
            print("  below. A failure OLDER than the running process is a row")
            print("  nobody cleared, not a fault in the code now running.")
            print("  Retry it from the queue panel to find out for certain.")
        except Exception as exc:  # noqa: BLE001
            print(f"  could not read the jobs table: {exc}")

    # A binding to a model the vendor no longer serves fails with a 404 in the
    # middle of a run, after the queue, the claim and whatever was spent
    # reaching the call. Asking the vendor costs one request.
    if "--models" in sys.argv:
        print()
        print("=" * 62)
        print("WHAT EACH PROVIDER ACTUALLY SERVES")
        print("=" * 62)
        try:
            from app.services import model_catalogue

            for provider in ("openai", "anthropic", "gemini", "ollama"):
                listed = model_catalogue.live_models(provider)
                if not listed.get("ok"):
                    print(f"  {provider:12s} — {listed.get('error')}")
                    continue
                names = listed["models"]
                print(f"  {provider:12s} {len(names)} model(s)")
                for name in names:
                    print(f"      {name}")

            print()
            print("  STAGE BINDINGS")
            report = model_catalogue.check_bindings()
            for row in report.get("bindings", []):
                mark = {"OK": "  ok  ", "NOT SERVED": " FAIL ",
                        "UNKNOWN": "  ??  "}.get(row["status"], "      ")
                print(f"  [{mark}] {row['stage']:24s} {row['provider']}/{row['model']}")
                if row.get("detail"):
                    print(f"           {row['detail']}")
            if not report.get("bindings"):
                print("  no stage bindings configured — every station uses its default")
        except Exception as exc:  # noqa: BLE001
            print(f"  could not check models: {exc}")

    if "--api" in sys.argv:
        print()
        print("=" * 62)
        print("WHAT THE RUNNING API REPORTS")
        print("=" * 62)
        try:
            import json
            import urllib.request

            url = "http://localhost:8000/health"
            with urllib.request.urlopen(url, timeout=5) as response:
                body = json.load(response)
            print(f"  generator build          {body.get('generator')}")
            print(f"  process started          {body.get('started_at')}")
            print(f"  worker                   {body.get('worker')}")
            print("\n  If 'process started' is older than your last rebuild, the")
            print("  API is serving code you have already changed.")
        except Exception as exc:  # noqa: BLE001
            print(f"  could not reach the API: {exc}")

    print()
    if ok:
        print("This checkout is current. If a job still fails with the")
        print("model_fields error, the process running it is NOT this code:")
        print("    docker compose up -d --build api generation-worker")
        print("(`restart` reuses the existing image and will not pick this up.)")
    else:
        print("This checkout is missing the fix.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
