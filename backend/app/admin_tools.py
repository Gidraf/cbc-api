"""Admin tools that run inside the api container (the image has only app/).

    docker compose exec api python -m app.admin_tools reset-password --username admin [--role admin] [--ask]
        A new random password for an account, printed once (or, with --ask, one
        you type); switches it on.

    docker compose exec api python -m app.admin_tools test-email you@example.com
        Checks each step of sending email — settings, Public address, the mail
        server's name, connecting, encryption, signing in — and sends a test
        email. Says which step fails and why; never prints the password.

    docker compose exec api python -m app.admin_tools teacher-now [--mode alternate] [--limit 60] [--keep-lessons]
        Teacher videos first: turns the 3D teacher on, pauses the lesson videos
        (queued ones cancelled, daily batch 0) and queues the booked posts'
        videos again with the teacher, the soonest post first.
    docker compose exec api python -m app.admin_tools promo-video [--audience teachers] [--mode classroom]
        A marketing video: the 3D teacher walks teachers, parents or students
        through the console (sign up, set a paper, take it online, share the
        link, see the marks). Prints where the MP4 is; it goes to Drive too.
    docker compose exec api python -m app.admin_tools lessons-resume [--target 200]
        The daily lesson videos again.

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


def reset_password(username: str, role: str = "", ask: bool = False) -> int:
    import getpass
    import secrets

    from app.infra.db import execute, run_migrations
    from app.services.auth import ROLES, hash_password

    if role and role not in ROLES:
        print(f"Unknown role {role!r}.")
        return 2
    run_migrations()
    if ask:
        # Typed, not passed on the command line: it never lands in shell history or `ps`.
        from app.state import KNOWN_WEAK

        password = getpass.getpass(f"New password for {username}: ")
        if getpass.getpass("Again: ") != password:
            print("They do not match; nothing changed.")
            return 2
        if len(password) < 12 or password.lower() in KNOWN_WEAK or password.lower() == username.lower():
            print("Use 12 characters or more, not a default and not the username; nothing changed.")
            return 2
    else:
        password = secrets.token_urlsafe(18)
    execute("""INSERT INTO app_users (username, password_plain, password_hash, role, is_active, updated_at)
               VALUES (:u, '', :h, :r, TRUE, NOW())
               ON CONFLICT (username) DO UPDATE SET password_plain = '', password_hash = EXCLUDED.password_hash,
                   role = CASE WHEN :keep THEN app_users.role ELSE EXCLUDED.role END, is_active = TRUE, updated_at = NOW()""",
            {"u": username, "h": hash_password(password), "r": role or "admin", "keep": not role})
    if ask:
        print(f"{username}: password set.")
    else:
        print(f"{username}: new password (shown once, not stored anywhere readable):")
        print(f"  {password}")
        print("Sign in with it, then set your own: Account → Change password in the console.")
    return 0


def test_email(to: str) -> int:
    from .infra.db import fetch_all
    from .services import email_links, mailer

    ok_all = True
    for step, ok, detail in mailer.diagnose(""):
        print(f"[{'ok' if ok else 'FAIL'}] {step}: {detail}")
        ok_all = ok_all and ok
    base = email_links.base_url()
    print(f"[{'ok' if base else 'FAIL'}] public address: "
          + (f"links point to {base}" if base else "not set — the console's Settings → Public address (or PUBLIC_BASE_URL). No link is sent without it."))
    try:
        rows = fetch_all("SELECT username, role, COALESCE(email, '') AS email, email_verified_at FROM app_users WHERE is_active ORDER BY username")
        with_email = [r for r in rows if r["email"]]
        print(f"[info] accounts: {len(rows)} active, {len(with_email)} with an email — a reset link only goes to an account that has one.")
        for r in rows:
            if r["role"] == "admin":
                print(f"[info]   {r['username']} (admin): {r['email'] or 'NO EMAIL — add it in Account → Email & password'}"
                      + (" (confirmed)" if r["email_verified_at"] else ""))
    except Exception as exc:  # noqa: BLE001
        print(f"[info] accounts: could not read ({type(exc).__name__})")
    if ok_all and to:
        sent = mailer.send(to, "CBC Factory test email", "Email from the platform works.", "<p>Email from the platform works.</p>")
        print(f"[{'ok' if sent else 'FAIL'}] send: " + (f"sent to {to} — check the inbox and the spam folder" if sent else mailer.LAST_ERROR["error"]))
        ok_all = sent
    return 0 if ok_all and base else 1


def teacher_now(how: str, limit: int, keep_lessons: bool) -> int:
    from .services import job_queue, teacher

    # The job kinds are registered where the web app loads them; this is a
    # separate process. And it only adds rows: the api's own worker renders
    # them — a worker started here would die with this command mid-video.
    from .routes import curriculum  # noqa: F401
    job_queue.start_worker = lambda: False

    out = teacher.render_now(how, limit=limit, pause_lessons=not keep_lessons, by="admin_tools")
    print(f"Teacher: {out['teacher']}")
    if not keep_lessons:
        print(f"Lesson videos paused: {out['lessons_cancelled']} queued cancelled; daily batch 0 "
              f"(was {out['daily_target_was']}). Bring them back: python -m app.admin_tools lessons-resume --target {out['daily_target_was'] or 200}")
    print(f"Booked posts' videos: {out['booked_videos']} — {out['queued']} queued with the teacher, "
          f"{out['already_with_teacher']} already made or rendering.")
    for f in out["failed"]:
        print("  not queued:", f)
    print("Watch them render in the console: Videos → batches, or the Jobs screen.")
    return 0


def promo_video(audience: str, how: str) -> int:
    from .services import promo

    def tick(stage: str, n: int = 0, total: int = 0) -> None:
        if stage != "draw" or n % 300 == 0:
            print(f"  {stage} {n}/{total}", flush=True)

    out = promo.render(audience, how=how, progress=tick)
    print(f"Video ({out.get('seconds') or '?'} s): {out['url']}")
    if out.get("thumbnail_url"):
        print(f"Cover: {out['thumbnail_url']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m app.admin_tools")
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("reset-password", help="a new random password for an account")
    r.add_argument("--username", default="admin")
    r.add_argument("--role", default="", help="also give it this role (a new account is an admin)")
    r.add_argument("--ask", action="store_true", help="type the password yourself instead of a random one")
    k = sub.add_parser("rotate-master-key", help="move saved provider keys to NEW_MASTER_KEY")
    k.add_argument("--dry-run", action="store_true")
    tn = sub.add_parser("teacher-now", help="turn the teacher on and render the booked posts' videos with it first")
    tn.add_argument("--mode", default="alternate", choices=["female", "male", "alternate", "classroom"])
    tn.add_argument("--limit", type=int, default=60, help="how many booked videos to queue (soonest first)")
    tn.add_argument("--keep-lessons", action="store_true", help="do not pause the daily lesson videos")
    pv = sub.add_parser("promo-video", help="a marketing video: the teacher shows how to sign up, set a paper and test online")
    pv.add_argument("--audience", default="teachers", choices=["teachers", "parents", "students"])
    pv.add_argument("--mode", default="classroom", choices=["female", "male", "classroom"])
    lr = sub.add_parser("lessons-resume", help="the daily lesson videos again")
    lr.add_argument("--target", type=int, default=200)
    t = sub.add_parser("test-email", help="check each step of sending email, and send a test")
    t.add_argument("to", nargs="?", default="", help="send a test email here")
    args = parser.parse_args(argv)
    if args.cmd == "teacher-now":
        return teacher_now(args.mode, args.limit, args.keep_lessons)
    if args.cmd == "promo-video":
        return promo_video(args.audience, args.mode)
    if args.cmd == "lessons-resume":
        from .services import teacher

        print("Daily lesson videos:", teacher.resume_lessons(args.target, by="admin_tools"), "a day")
        return 0
    if args.cmd == "test-email":
        return test_email(args.to)
    if args.cmd == "reset-password":
        return reset_password(args.username, args.role, ask=args.ask)
    return rotate_master_key(args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
