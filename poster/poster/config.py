"""The poster's settings, all from the environment."""
from __future__ import annotations

import os

CBC_API_URL = os.getenv("CBC_API_URL", "http://api:8000").rstrip("/")
CBC_API_KEY = os.getenv("CBC_API_KEY", "")            # a video maker's key (e.g. gidraf's)
POSTER_TOKEN = os.getenv("POSTER_TOKEN", "")          # the API commands the poster with this
BROWSER_CHANNEL = os.getenv("BROWSER_CHANNEL", "chrome")
PROFILE_DIR = os.getenv("PROFILE_DIR", "/data/profile")
SHOTS_DIR = os.getenv("SHOTS_DIR", "/data/shots")
TMP_DIR = os.getenv("TMP_DIR", "/data/tmp")
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "60"))
CONTROL_PORT = int(os.getenv("CONTROL_PORT", "6090"))
# YouTube asks whether each video is made for children (under 13). Junior
# Secondary content is for 12–15 year olds; set "yes" if your channel is for
# younger children. The legal choice is the channel owner's.
YOUTUBE_MADE_FOR_KIDS = os.getenv("YOUTUBE_MADE_FOR_KIDS", "no").lower() in ("1", "yes", "true")
