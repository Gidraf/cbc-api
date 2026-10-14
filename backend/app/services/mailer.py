"""Email to one person: a password-reset link, an address to confirm.

Sent the way CVPAP sends its mail — SMTP with STARTTLS on 587 (or SSL on
465), signed in as the sending mailbox. The platform's SMTP_* settings come
first; CVPAP's own names (MAIL_SERVER, ADMIN_EMAIL, ADMIN_EMAIL_PASSWORD) are
read too, so the same mailbox can be used by copying its lines across.

The password is never logged, and a failure to send never raises: the
person sees the same answer either way, and the log says why.
"""
from __future__ import annotations

import html
import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from typing import Any

logger = logging.getLogger("cbc-mailer")


def config() -> dict[str, Any]:
    from ..settings import settings

    user = settings.smtp_user or os.getenv("MAIL_USERNAME") or os.getenv("ADMIN_EMAIL") or ""
    password = settings.smtp_password or os.getenv("MAIL_PASSWORD") or os.getenv("ADMIN_EMAIL_PASSWORD") or ""
    host = settings.smtp_host or os.getenv("MAIL_SERVER") or os.getenv("SMTP_SERVER") or ""
    if not host and os.getenv("DOMAIN") and user:
        host = f"mail.{os.getenv('DOMAIN')}"          # CVPAP's default
    port = int(os.getenv("SMTP_PORT") or os.getenv("MAIL_PORT") or settings.smtp_port or 587)
    ssl_on = settings.smtp_secure or os.getenv("MAIL_USE_SSL", "").lower() == "true" or port == 465
    # Send as the mailbox signed in, unless a real From address is set (compose's
    # placeholder, notifications@cbc-api.local, is not one: servers refuse it).
    sender = settings.smtp_from if settings.smtp_from and not settings.smtp_from.endswith(".local") else user
    return {"host": host, "port": port, "user": user, "password": password, "ssl": ssl_on,
            "sender": sender, "name": os.getenv("SMTP_FROM_NAME") or "CBC Factory"}


def configured() -> bool:
    c = config()
    return bool(c["host"] and c["user"] and c["password"])


def summary() -> dict[str, Any]:
    """What an admin may see: never the password."""
    c = config()
    return {"configured": configured(), "host": c["host"], "port": c["port"], "sender": c["sender"],
            "security": "SSL" if c["ssl"] else "STARTTLS"}


LAST_ERROR: dict[str, str] = {"error": ""}


def _why(exc: Exception) -> str:
    """The reason a send failed, in words an admin can act on."""
    import socket

    text = f"{type(exc).__name__}: {str(exc)[:200]}"
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return (text + " — the mail server refused the username or password. Check SMTP_USER and SMTP_PASSWORD "
                "(for Gmail, an app password, not the account password).")
    if isinstance(exc, socket.gaierror):
        return text + " — that SMTP_HOST name does not exist (DNS). Check the spelling."
    if isinstance(exc, (TimeoutError, socket.timeout, ConnectionRefusedError, OSError)) and not isinstance(exc, smtplib.SMTPException):
        return (text + " — could not reach the mail server on that port. Many VPS providers block outgoing mail "
                "ports (25/465/587) until you ask them to open them; or try the other port (587 STARTTLS / 465 SSL).")
    if isinstance(exc, smtplib.SMTPNotSupportedError):
        return text + " — the server does not offer STARTTLS on this port. Try port 465 with SMTP_SECURE=true."
    if isinstance(exc, ssl.SSLError):
        return text + " — the encryption failed: 465 needs SMTP_SECURE=true, 587 needs SMTP_SECURE=false."
    if isinstance(exc, (smtplib.SMTPSenderRefused, smtplib.SMTPRecipientsRefused)):
        return text + " — the server refused the sender or the recipient. The From address must be the mailbox signed in (or one it may send as)."
    return text


def send(to: str, subject: str, text: str, html_body: str = "") -> bool:
    """Send one email. True if the server took it."""
    c = config()
    if not (c["host"] and c["user"] and c["password"]):
        LAST_ERROR["error"] = "SMTP is not set up: SMTP_HOST, SMTP_USER and SMTP_PASSWORD are not all in the api's environment."
        logger.warning("Email not sent (%r to %s): SMTP is not set up.", subject, _mask(to))
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((c["name"], c["sender"]))
    msg["To"] = to
    # Date and Message-ID are required headers: without a Date, amavis on the
    # mail server blocks the message as BAD-HEADER and bounces it.
    msg["Date"] = formatdate(localtime=False, usegmt=True)
    msg["Message-ID"] = make_msgid(domain=(c["sender"].split("@")[-1] or None))
    msg.set_content(text)
    if html_body:
        msg.add_alternative(html_body, subtype="html")
    context = ssl.create_default_context()
    try:
        if c["ssl"]:
            server: smtplib.SMTP = smtplib.SMTP_SSL(c["host"], c["port"], timeout=15, context=context)
        else:
            server = smtplib.SMTP(c["host"], c["port"], timeout=15)
            server.starttls(context=context)
        try:
            server.login(c["user"], c["password"])
            server.send_message(msg)
        finally:
            try:
                server.quit()
            except Exception:  # noqa: BLE001
                pass
        logger.info("Email sent: %r to %s", subject, _mask(to))
        LAST_ERROR["error"] = ""
        return True
    except Exception as exc:  # noqa: BLE001
        LAST_ERROR["error"] = _why(exc)
        logger.error("Email not sent (%r to %s): %s", subject, _mask(to), LAST_ERROR["error"])
        return False


def _mask(address: str) -> str:
    name, _, domain = address.partition("@")
    return (name[:2] + "…@" + domain) if domain else "…"


def diagnose(to: str = "") -> list[tuple[str, bool, str]]:
    """Each step of sending, in order, and where it stops. Never shows the password."""
    import socket

    c = config()
    steps: list[tuple[str, bool, str]] = []
    missing = [n for n, v in (("SMTP_HOST", c["host"]), ("SMTP_USER", c["user"]), ("SMTP_PASSWORD", c["password"])) if not v]
    steps.append(("settings", not missing,
                  f"host {c['host'] or '-'}:{c['port']} ({'SSL' if c['ssl'] else 'STARTTLS'}), user {c['user'] or '-'}, "
                  f"from {c['sender'] or '-'}, password {'set' if c['password'] else 'MISSING'}"
                  + (f" — missing: {', '.join(missing)} (put them in .env, then `docker compose up -d api worker`)" if missing else "")))
    if missing:
        return steps
    try:
        socket.getaddrinfo(c["host"], c["port"])
        steps.append(("dns", True, f"{c['host']} resolves"))
    except Exception as exc:  # noqa: BLE001
        steps.append(("dns", False, _why(exc)))
        return steps
    context = ssl.create_default_context()
    try:
        server = (smtplib.SMTP_SSL(c["host"], c["port"], timeout=15, context=context) if c["ssl"]
                  else smtplib.SMTP(c["host"], c["port"], timeout=15))
        steps.append(("connect", True, f"reached {c['host']}:{c['port']}"))
    except Exception as exc:  # noqa: BLE001
        steps.append(("connect", False, _why(exc)))
        return steps
    try:
        if not c["ssl"]:
            server.starttls(context=context)
            steps.append(("encryption", True, "STARTTLS ok"))
        else:
            steps.append(("encryption", True, "SSL ok"))
        server.login(c["user"], c["password"])
        steps.append(("sign-in", True, f"signed in as {c['user']}"))
    except Exception as exc:  # noqa: BLE001
        steps.append(("sign-in" if isinstance(exc, smtplib.SMTPAuthenticationError) else "encryption", False, _why(exc)))
        return steps
    finally:
        try:
            server.quit()
        except Exception:  # noqa: BLE001
            pass
    if to:
        ok = send(to, "CBC Factory test email", "Email from the platform works.", "<p>Email from the platform works.</p>")
        steps.append(("send", ok, f"sent to {to} — check the inbox and spam" if ok else LAST_ERROR["error"]))
    return steps


# ── the two emails ───────────────────────────────────────────────────────────

def _page(heading: str, lines: list[str], button: str, link: str, small: str) -> str:
    esc = html.escape
    paras = "".join(f"<p style='margin:0 0 14px'>{esc(x)}</p>" for x in lines)
    return f"""<!doctype html><html><body style="margin:0;background:#f4f6f8;font-family:Arial,Helvetica,sans-serif;color:#1f2933">
<div style="max-width:520px;margin:0 auto;padding:28px 16px">
 <div style="background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:28px">
  <h2 style="margin:0 0 16px;font-size:20px">{esc(heading)}</h2>
  {paras}
  <p style="margin:22px 0"><a href="{esc(link, quote=True)}" style="background:#2563eb;color:#fff;text-decoration:none;
     padding:12px 20px;border-radius:8px;font-weight:bold;display:inline-block">{esc(button)}</a></p>
  <p style="margin:0 0 6px;font-size:12px;color:#64748b">If the button does not work, open this link:</p>
  <p style="margin:0 0 18px;font-size:12px;word-break:break-all"><a href="{esc(link, quote=True)}" style="color:#2563eb">{esc(link)}</a></p>
  <p style="margin:0;font-size:12px;color:#64748b">{esc(small)}</p>
 </div>
</div></body></html>"""


def send_reset(to: str, username: str, link: str, minutes: int) -> bool:
    lines = [f"Hello {username},",
             "Someone asked to reset the password of your CBC Factory account. If it was you, choose a new one with the button below.",
             f"The link works once, for {minutes} minutes."]
    small = "If you did not ask for this, ignore this email: your password stays as it is."
    text = "\n\n".join(lines + [link, small])
    return send(to, "Reset your CBC Factory password", text, _page("Reset your password", lines, "Choose a new password", link, small))


def send_confirm(to: str, username: str, link: str, days: int) -> bool:
    lines = [f"Hello {username},",
             "Confirm this is your email address, so we can send you a link if you ever forget your password.",
             f"The link works for {days} days."]
    small = "If you did not create a CBC Factory account, ignore this email."
    text = "\n\n".join(lines + [link, small])
    return send(to, "Confirm your email address", text, _page("Confirm your email", lines, "Confirm my email", link, small))
