#!/usr/bin/env python3
"""Re-encrypt every stored secret from one CBC_MASTER_KEY to another, once.

What CBC_MASTER_KEY encrypts: provider_configs.encrypted_api_key (the OpenAI,
Anthropic and Gemini keys saved from the console). Nothing else.

The image holds only app/, so feed the script in on stdin. Run it inside the
api container, which already has DATABASE_URL:

    docker compose exec -T -e OLD_CBC_MASTER_KEY='<old>' -e NEW_CBC_MASTER_KEY='<new>' \\
        api python - --dry-run < backend/scripts/rotate_master_key.py

--dry-run counts the rows and checks every one decrypts; it writes nothing.
Drop it to re-encrypt, all rows in one transaction. A row already under the
new key is left alone, so running it twice is safe. If any row decrypts under
neither key, nothing is written.

Afterwards put CBC_MASTER_KEY=<new> in .env and restart the stack.
"""
from __future__ import annotations

import argparse
import os
import sys

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import create_engine, text

# (table, primary key, encrypted column) — every place CBC_MASTER_KEY is used.
ENCRYPTED_COLUMNS = [
    ("provider_configs", "provider", "encrypted_api_key"),
]


def fernet_from_env(name: str) -> Fernet:
    value = (os.getenv(name) or "").strip()
    if not value:
        sys.exit(f"{name} is not set.")
    try:
        return Fernet(value.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        sys.exit(f"{name} is not a valid Fernet key: {exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="count and check rows; write nothing")
    args = parser.parse_args()

    old, new = fernet_from_env("OLD_CBC_MASTER_KEY"), fernet_from_env("NEW_CBC_MASTER_KEY")
    if os.getenv("OLD_CBC_MASTER_KEY", "").strip() == os.getenv("NEW_CBC_MASTER_KEY", "").strip():
        sys.exit("OLD_CBC_MASTER_KEY and NEW_CBC_MASTER_KEY are the same key.")
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        sys.exit("DATABASE_URL is not set.")

    engine = create_engine(database_url)
    lock = " FOR UPDATE" if engine.dialect.name == "postgresql" else ""
    to_rotate: list[tuple[str, str, str, object, str]] = []
    already_new = failed = 0

    with engine.begin() as conn:
        for table, pk, column in ENCRYPTED_COLUMNS:
            rows = conn.execute(text(
                f"SELECT {pk} AS pk, {column} AS secret FROM {table} "
                f"WHERE {column} IS NOT NULL AND {column} <> ''{lock}"
            )).all()
            for row in rows:
                token = row.secret.encode("utf-8")
                try:
                    plain = old.decrypt(token)
                except InvalidToken:
                    try:
                        new.decrypt(token)
                        already_new += 1
                    except InvalidToken:
                        failed += 1
                        print(f"  {table}.{column} [{pk}={row.pk}]: decrypts under neither key")
                    continue
                to_rotate.append((table, pk, column, row.pk, new.encrypt(plain).decode("utf-8")))

        print(f"{len(to_rotate)} row(s) to re-encrypt, {already_new} already under the new key, "
              f"{failed} unreadable.")
        if failed:
            print("Nothing written: fix or clear the unreadable rows first.")
            raise SystemExit(1)  # rolls the transaction back
        if args.dry_run:
            print("Dry run: nothing written.")
            return 0

        for table, pk, column, pk_value, secret in to_rotate:
            conn.execute(text(f"UPDATE {table} SET {column} = :secret WHERE {pk} = :pk"),
                         {"secret": secret, "pk": pk_value})
    print(f"Re-encrypted {len(to_rotate)} row(s). Now set CBC_MASTER_KEY to the new key and restart.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
