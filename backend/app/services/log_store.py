"""Recent log lines from every process, kept where the API can read them.

Diagnosing a generation meant asking the operator to shell into the box,
find the worker container, and paste lines. The API and the worker are
different processes, so a buffer in the API never held the worker's lines —
and the worker's lines are the ones that matter. This handler writes INFO
and above from any process to a table, in batches from a background thread
so a log line never waits on the database, and prunes to the last KEEP rows.
`recent()` reads them back, and the admin route serves them as text.
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from collections import deque
from typing import Any

KEEP = int(os.getenv("LOG_KEEP_ROWS", "20000"))
RETENTION_DAYS = int(os.getenv("LOG_RETENTION_DAYS", "7"))
FLUSH_EVERY = 2.0      # seconds
FLUSH_AT = 200         # rows

# Anything that looks like a credential is not for a log a link can reach.
_SECRET = re.compile(
    r"(sk-[A-Za-z0-9_\-]{8,}|pk-lf-[A-Za-z0-9_\-]{8,}|sk-lf-[A-Za-z0-9_\-]{8,}"
    r"|Bearer\s+[A-Za-z0-9._\-]{12,}|eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,})")


def redact(text: str) -> str:
    return _SECRET.sub("[redacted]", text)


class DbLogHandler(logging.Handler):
    """Buffers records and writes them in one INSERT per batch."""

    def __init__(self, process: str) -> None:
        super().__init__(level=logging.INFO)
        self.process = process
        self._rows: deque[tuple[str, str, str]] = deque()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.ensure_running()

    def ensure_running(self) -> None:
        """Start the flush thread, or start it again after a fork.

        A prefork worker inherits this handler from its parent and not the
        parent's threads: the buffer fills in the child and nothing writes
        it. Called from the child's own startup.
        """
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._loop, name="log-store", daemon=True)
        self._thread.start()

    def emit(self, record: logging.LogRecord) -> None:
        # Never log the database's own chatter back into the database.
        if record.name.startswith(("sqlalchemy", "psycopg", "urllib3", "httpx", "httpcore",
                                   "uvicorn.access", "watchfiles", "asyncio")):
            return
        try:
            message = redact(self.format(record))[:4000]
        except Exception:  # noqa: BLE001
            return
        with self._lock:
            self._rows.append((record.levelname, record.name, message))
            if len(self._rows) > 5 * FLUSH_AT:
                self._rows.popleft()

    def _loop(self) -> None:
        last_prune = 0.0
        while not self._stop.wait(FLUSH_EVERY):
            self.flush_now()
            if time.time() - last_prune > 300:
                last_prune = time.time()
                self._prune()

    def flush_now(self) -> None:
        with self._lock:
            if not self._rows:
                return
            batch = list(self._rows)
            self._rows.clear()
        try:
            from ..infra.db import get_engine
            from sqlalchemy import text

            engine = get_engine()
            with engine.begin() as conn:
                conn.execute(
                    text("INSERT INTO service_logs (process, level, logger, message) "
                         "VALUES (:process, :level, :logger, :message)"),
                    [{"process": self.process, "level": lvl, "logger": name, "message": msg}
                     for lvl, name, msg in batch])
        except Exception:  # noqa: BLE001
            # A database that is down is exactly when logs matter and exactly
            # when they cannot be stored. Dropping the batch is the only move
            # that does not take the process down with it.
            return

    def _prune(self) -> None:
        try:
            prune()
        except Exception:  # noqa: BLE001
            return


def prune(keep: int = KEEP, retention_days: int = RETENTION_DAYS) -> int:
    """Drop lines older than the retention, and any beyond the row cap.
    Returns how many went."""
    from ..infra.db import execute, fetch_one

    before = int((fetch_one("SELECT COUNT(*) AS n FROM service_logs") or {}).get("n") or 0)
    execute("DELETE FROM service_logs WHERE at < NOW() - (:days || ' days')::interval",
            {"days": str(max(1, int(retention_days)))})
    execute("DELETE FROM service_logs WHERE id < "
            "(SELECT COALESCE(MAX(id), 0) - :keep FROM service_logs)", {"keep": int(keep)})
    after = int((fetch_one("SELECT COUNT(*) AS n FROM service_logs") or {}).get("n") or 0)
    return max(0, before - after)


def clear(older_than_minutes: int = 0) -> int:
    """Delete stored log lines — all of them, or only those older than N minutes."""
    from ..infra.db import execute, fetch_one

    if older_than_minutes > 0:
        where = "at < NOW() - (:minutes || ' minutes')::interval"
        params: dict[str, Any] = {"minutes": str(int(older_than_minutes))}
    else:
        where, params = "1=1", {}
    count = int((fetch_one(f"SELECT COUNT(*) AS n FROM service_logs WHERE {where}", params) or {}).get("n") or 0)
    if count:
        execute(f"DELETE FROM service_logs WHERE {where}", params)
    return count


_installed: DbLogHandler | None = None


def install(process: str) -> None:
    """Attach the handler to the root logger once per process."""
    global _installed
    if _installed is not None:
        _installed.process = process or _installed.process
        _installed.ensure_running()
        return
    if not os.getenv("DATABASE_URL"):
        return
    handler = DbLogHandler(process)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    # The API process never configured logging, so the root logger sat at
    # WARNING and dropped every INFO record before any handler saw it — the
    # meter's cost lines, the raw usage the provider returned, the per-lesson
    # token counts. The store holds INFO and above.
    if root.level == logging.NOTSET or root.level > logging.INFO:
        root.setLevel(logging.INFO)
    _installed = handler


def recent(*, lines: int = 500, grep: str = "", level: str = "",
           since_minutes: int = 0, process: str = "") -> list[dict[str, Any]]:
    """The newest matching lines, oldest first."""
    from ..infra.db import fetch_all

    where = ["1=1"]
    params: dict[str, Any] = {"limit": max(1, min(int(lines), KEEP))}
    if grep:
        where.append("message ILIKE :grep")
        params["grep"] = f"%{grep}%"
    if level:
        order = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        wanted = level.upper()
        if wanted in order:
            where.append("level = ANY(:levels)")
            params["levels"] = order[order.index(wanted):]
    if since_minutes:
        where.append("at > NOW() - (:minutes || ' minutes')::interval")
        params["minutes"] = str(int(since_minutes))
    if process:
        where.append("process = :process")
        params["process"] = process
    rows = fetch_all(
        f"SELECT at, process, level, logger, message FROM service_logs "
        f"WHERE {' AND '.join(where)} ORDER BY id DESC LIMIT :limit", params) or []
    return list(reversed(rows))


def as_text(rows: list[dict[str, Any]]) -> str:
    out = []
    for row in rows:
        at = row.get("at")
        stamp = at.strftime("%Y-%m-%d %H:%M:%S") if hasattr(at, "strftime") else str(at)
        out.append(f"{stamp} {row.get('process', ''):<6} {row.get('level', ''):<7} "
                   f"{row.get('logger', '')}: {row.get('message', '')}")
    return "\n".join(out) + ("\n" if out else "")
