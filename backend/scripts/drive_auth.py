#!/usr/bin/env python3
"""Sign the platform in to your Google Drive, once.

Makes the refresh token the server uses to move finished videos to your
Drive. Run it on your own computer (it opens a browser):

    python3 backend/scripts/drive_auth.py ~/Downloads/client_secret_XXXX.json

Before you run it, in Google Cloud Console (console.cloud.google.com):
  1. Create a project (or pick one) and enable the "Google Drive API".
  2. APIs & Services → OAuth consent screen: External, add yourself as a
     test user (or publish it).
  3. APIs & Services → Credentials → Create credentials → OAuth client ID →
     Application type "Desktop app". Copy the client ID and secret.

The permission asked for is `drive.file`: the platform can see and change
only the files it creates, never anything else in your Drive.

Then put the three lines it prints in the server's .env and restart.
"""
from __future__ import annotations

import base64
import getpass
import hashlib
import http.server
import json
import os
import secrets
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser

SCOPE = "https://www.googleapis.com/auth/drive.file"
AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"


def _from_file(path: str) -> tuple[str, str]:
    """The client ID and secret from the JSON Google Cloud lets you download
    when you create an OAuth client (client_secret_….json)."""
    with open(os.path.expanduser(path), encoding="utf-8") as fh:
        data = json.load(fh)
    client = data.get("installed") or data.get("web") or data
    if "web" in data and "installed" not in data:
        print("Note: this is a 'Web application' client; create a 'Desktop app' client instead if sign-in "
              "fails with redirect_uri_mismatch.")
    return str(client.get("client_id") or ""), str(client.get("client_secret") or "")


def main() -> None:
    client_id, client_secret = "", ""
    if len(sys.argv) > 1 and sys.argv[1].endswith(".json"):
        client_id, client_secret = _from_file(sys.argv[1])
    client_id = client_id or os.getenv("GOOGLE_DRIVE_CLIENT_ID") or input("OAuth client ID: ").strip()
    client_secret = client_secret or os.getenv("GOOGLE_DRIVE_CLIENT_SECRET") or getpass.getpass("OAuth client secret: ").strip()
    if not client_id or not client_secret:
        sys.exit("A client ID and secret are needed (see the notes at the top of this file).")

    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    got: dict[str, str] = {}

    class Reply(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
            got.update(query)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            ok = "code" in query and query.get("state") == state
            self.wfile.write(("<h2>Done — you can close this tab.</h2>" if ok else
                              f"<h2>Sign-in did not complete: {query.get('error', 'no code')}</h2>").encode())

        def log_message(self, *args: object) -> None:
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Reply)
    redirect = f"http://127.0.0.1:{server.server_port}/"
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    url = AUTH + "?" + urllib.parse.urlencode({
        "client_id": client_id, "redirect_uri": redirect, "response_type": "code", "scope": SCOPE,
        "access_type": "offline", "prompt": "consent", "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256"})
    print("Opening your browser to sign in to Google…\nIf it does not open, visit:\n" + url + "\n")
    webbrowser.open(url)
    thread.join(timeout=300)
    server.server_close()
    if got.get("state") != state or "code" not in got:
        sys.exit(f"Sign-in did not complete: {got.get('error') or 'no reply within five minutes'}")

    body = urllib.parse.urlencode({"code": got["code"], "client_id": client_id, "client_secret": client_secret,
                                   "redirect_uri": redirect, "grant_type": "authorization_code",
                                   "code_verifier": verifier}).encode()
    with urllib.request.urlopen(urllib.request.Request(TOKEN, data=body), timeout=30) as resp:
        tokens = json.loads(resp.read())
    refresh = tokens.get("refresh_token")
    if not refresh:
        sys.exit("Google returned no refresh token. Remove the app's access at "
                 "myaccount.google.com/permissions and run this again.")
    print("Signed in. Put these three lines in the server's .env, then restart the stack:\n")
    print(f"GOOGLE_DRIVE_CLIENT_ID={client_id}")
    print(f"GOOGLE_DRIVE_CLIENT_SECRET={client_secret}")
    print(f"GOOGLE_DRIVE_REFRESH_TOKEN={refresh}")


if __name__ == "__main__":
    main()
