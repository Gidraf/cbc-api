"""Admin tools that run inside the api container (the image has only app/).

    docker compose exec api python -m app.admin_tools reset-password --username admin [--role admin]
        A new random password for an account, printed once; switches it on.

    docker compose run --rm -e OLD_MASTER_KEY -e NEW_MASTER_KEY api python -m app.admin_tools rotate-master-key [--dry-run]
        Moves the saved provider keys from one CBC_MASTER_KEY to another. Both
        keys come from the environment, never the command line (shell history,
        `ps`). Every value is read with the old key and written with the new
        one in one transaction: all move, or none. Prints counts, never values.
"""
from __future__ import annotations

import os
import sys

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import text

from app.infra.db import get_engine

# Every column that holds a value encrypted with CBC_MASTER_KEY.
COLUMNS = [("provider_configs", "provider", "encrypted_api_key")]


def rotate_master_key(dry: bool) -> int:
    old, new = os.getenv("OLD_MASTER_KEY", "").strip(), os.getenv("NEW_MASTER_KEY", "").strip()
    if not old or not new:
        print("Set OLD_MASTER_KEY and NEW_MASTER_KEY in the environment.")
        return 2
    if old == new:
        print("The old and new keys are the same: nothing to do.")
        return 0
    try:
        f_old, f_new = Fernet(old.encode()), Fernet(new.encode())
    except ValueError:
        print("A key is not a valid Fernet key (make one with: python -c \"from cryptography.fernet import Fernet; "
              "print(Fernet.generate_key().decode())\").")
        return 2
    moved = 0
    with get_engine().begin() as conn:
        for table, key_col, col in COLUMNS:
            rows = conn.execute(text(f"SELECT {key_col}, {col} FROM {table} WHERE COALESCE({col}, '') <> ''")).all()
            for ident, value in rows:
                try:
                    plain = f_old.decrypt(value.encode())
                except InvalidToken:
                    try:
                        f_new.decrypt(value.encode())
                        continue                     # already on the new key (a run that was repeated)
                    except InvalidToken:
                        print(f"{table}.{col} for {ident!r} is readable with neither key: stopping, nothing written.")
                        raise SystemExit(1)
                if not dry:
                    conn.execute(text(f"UPDATE {table} SET {col} = :v WHERE {key_col} = :k"),
                                 {"v": f_new.encrypt(plain).decode(), "k": ident})
                moved += 1
    print(f"{'Would move' if dry else 'Moved'} {moved} saved key(s) to the new master key.")
    return 0


def reset_password(username: str, role: str = "") -> int:
    import secrets

    from app.infra.db import execute, run_migrations
    from app.services.auth import ROLES, hash_password

    if role and role not in ROLES:
        print(f"Unknown role {role!r}.")
        return 2
    run_migrations()
    password = secrets.token_urlsafe(18)
    execute("""INSERT INTO app_users (username, password_plain, password_hash, role, is_active, updated_at)
               VALUES (:u, '', :h, :r, TRUE, NOW())
               ON CONFLICT (username) DO UPDATE SET password_plain = '', password_hash = EXCLUDED.password_hash,
                   role = CASE WHEN :keep THEN app_users.role ELSE EXCLUDED.role END, is_active = TRUE, updated_at = NOW()""",
            {"u": username, "h": hash_password(password), "r": role or "admin", "keep": not role})
    print(f"{username}: new password (shown once, not stored anywhere readable):")
    print(f"  {password}")
    return 0


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m app.admin_tools")
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("reset-password", help="a new random password for an account")
    r.add_argument("--username", default="admin")
    r.add_argument("--role", default="", help="also give it this role (a new account is an admin)")
    k = sub.add_parser("rotate-master-key", help="move saved provider keys to NEW_MASTER_KEY")
    k.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.cmd == "reset-password":
        return reset_password(args.username, args.role)
    return rotate_master_key(args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
