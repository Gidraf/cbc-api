"""The poster's settings, all from the environment."""
from __future__ import annotations

import os
import socket

# "server": inside the stack, commanded by the API (noVNC screen).
# "local": on the owner's own computer — it asks the API for its commands,
# because the server cannot reach it.
POSTER_MODE = os.getenv("POSTER_MODE", "server").lower()
POSTER_ID = os.getenv("POSTER_ID", "") or socket.gethostname()
_HOME = os.path.expanduser("~/.cbc/poster")

CBC_API_URL = os.getenv("CBC_API_URL", "http://api:8000").rstrip("/")
CBC_API_KEY = os.getenv("CBC_API_KEY", "")            # a video maker's key (e.g. gidraf's)
POSTER_TOKEN = os.getenv("POSTER_TOKEN", "")          # the API commands the poster with this
BROWSER_CHANNEL = os.getenv("BROWSER_CHANNEL", "chrome")
_DATA = "/data" if POSTER_MODE == "server" else _HOME
PROFILE_DIR = os.getenv("PROFILE_DIR", f"{_DATA}/profile")
SHOTS_DIR = os.getenv("SHOTS_DIR", f"{_DATA}/shots")
TMP_DIR = os.getenv("TMP_DIR", f"{_DATA}/tmp")
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "60"))
CONTROL_PORT = int(os.getenv("CONTROL_PORT", "6090"))
# YouTube asks whether each video is made for children (under 13). Junior
# Secondary content is for 12–15 year olds; set "yes" if your channel is for
# younger children. The legal choice is the channel owner's.
YOUTUBE_MADE_FOR_KIDS = os.getenv("YOUTUBE_MADE_FOR_KIDS", "no").lower() in ("1", "yes", "true")
