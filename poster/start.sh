#!/usr/bin/env bash
# A screen, a window manager, the screen shared over VNC (password required,
# local only), noVNC in front of it for the browser, then the poster.
set -euo pipefail

mkdir -p "$PROFILE_DIR" "$SHOTS_DIR" "$TMP_DIR"
# A browser killed mid-run leaves its profile locked; the lock belongs to a
# process that no longer exists.
rm -f "$PROFILE_DIR"/Singleton* 2>/dev/null || true

if [ -z "${VNC_PASSWORD:-}" ]; then
  echo "VNC_PASSWORD is required: it protects the logged-in browser's screen." >&2
  exit 1
fi
if [ -z "${POSTER_TOKEN:-}" ]; then
  echo "POSTER_TOKEN is required: the API uses it to command the poster." >&2
  exit 1
fi

Xvfb :99 -screen 0 1440x900x24 -nolisten tcp &
sleep 1
fluxbox >/dev/null 2>&1 &
x11vnc -storepasswd "$VNC_PASSWORD" /tmp/vncpass >/dev/null
x11vnc -display :99 -rfbauth /tmp/vncpass -forever -shared -rfbport 5900 -localhost -quiet -bg
websockify --web /usr/share/novnc 6080 localhost:5900 >/dev/null 2>&1 &

exec python -m poster
