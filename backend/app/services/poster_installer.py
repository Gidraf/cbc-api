"""The Mac poster as one file to download and run on another Mac.

The server builds it from the poster folder of the deployed checkout (mounted
read-only into the API container at POSTER_SRC), so the download is always the
code that is running. It is a shell script with the poster's code appended as
a base64 tarball: it unpacks into ~/.cbc/poster-src and runs mac/install.sh.
Fetched with a one-time console link, it carries a key minted for that link
(the way the agent kits do), hands it to the installer, and deletes itself.
"""
from __future__ import annotations

import base64
import io
import os
import tarfile
from pathlib import Path

FILENAME = "cbc-poster-installer.command"
# What the Mac needs: the package, its requirements and the mac/ scripts.
PARTS = ("poster", "requirements.txt", "mac")


def source_dir() -> Path:
    return Path(os.getenv("POSTER_SRC", "/app/poster_src"))


def _skip(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
    name = Path(info.name).name
    if name == "__pycache__" or name.endswith(".pyc") or name == ".DS_Store" or name.startswith(".env"):
        return None
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    return info


def tarball(src: Path) -> bytes:
    missing = [p for p in PARTS if not (src / p).exists()]
    if missing:
        raise FileNotFoundError(f"The poster folder at {src} has no {', '.join(missing)}.")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for part in PARTS:
            tar.add(src / part, arcname=part, filter=_skip)
    return buf.getvalue()


def build(src: Path, default_url: str, api_key: str = "") -> bytes:
    """The installer: a script, then the payload after the __PAYLOAD__ line."""
    url = "".join(ch for ch in default_url if ch.isalnum() or ch in ":/._-") or "https://cbc.gidraf.dev"
    key = "".join(ch for ch in api_key if ch.isalnum() or ch in "_-")
    payload = base64.encodebytes(tarball(src)).decode()
    head = f"""#!/bin/bash
# CBC poster for this Mac: it posts from your own Google Chrome, with the
# accounts you log into yourself. Run it in Terminal:
#
#   bash ~/Downloads/{FILENAME}
#
# It unpacks into ~/.cbc/poster-src and runs the installer there with the key
# this file carries, then deletes itself. Needs Google Chrome and Python 3.10+.
set -euo pipefail
DEST="$HOME/.cbc/poster-src"
rm -rf "$DEST"
mkdir -p "$DEST"
sed -n '/^__PAYLOAD__$/,$p' "$0" | tail -n +2 | base64 -D | tar -xzf - -C "$DEST"
status=0
CBC_DEFAULT_URL="{url}" CBC_API_KEY="{key}" bash "$DEST/mac/install.sh" "$@" || status=$?
rm -f "$0"   # it carries a key: no copy left in Downloads
exit $status
__PAYLOAD__
"""
    return (head + payload).encode()
