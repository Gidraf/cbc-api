#!/usr/bin/env python3
"""Is the code you edited the code that is running?

Four rounds went on one error that was fixed after the first. Every round the
same question went unanswered: is this a live fault, or a process running an
older build? Nothing on either side could tell them apart.

    python diagnose.py            # what THIS checkout contains
    python diagnose.py --api      # ...and what the running API reports

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
