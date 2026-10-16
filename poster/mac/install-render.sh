#!/usr/bin/env bash
# The render helper: this Mac draws the server's queued videos and sends them
# back — about two minutes a video instead of fifteen on a server with no GPU.
#
#   bash poster/mac/install-render.sh      install, or update after git pull
#
# Needs the poster installed first (it reads its key from ~/.cbc/poster/.env),
# Google Chrome, and ffmpeg (brew install ffmpeg). RENDER_SLOTS in
# ~/.cbc/render/.env says how many videos draw at once (2).
set -euo pipefail

HERE="$(cd "$(dirname "$0")/../.." && pwd)"          # the repository
HOME_DIR="$HOME/.cbc/render"
APP="$HOME_DIR/app"
VENV="$HOME_DIR/venv"
LABEL="com.cbc.render"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

[ -f "$HOME/.cbc/poster/.env" ] || { echo "Install the poster first: bash poster/mac/install.sh" >&2; exit 1; }
FFMPEG="$(command -v ffmpeg || ls /opt/homebrew/bin/ffmpeg /usr/local/bin/ffmpeg 2>/dev/null | head -1 || true)"
[ -n "$FFMPEG" ] || { echo "ffmpeg is needed: brew install ffmpeg" >&2; exit 1; }
[ -d "/Applications/Google Chrome.app" ] || { echo "Google Chrome is needed." >&2; exit 1; }
PY="$(command -v python3.12 || command -v python3.11 || command -v python3 || true)"
[ -n "$PY" ] || { echo "Python 3.11+ is needed: https://www.python.org/downloads/macos/" >&2; exit 1; }

mkdir -p "$HOME_DIR" "$HOME/Library/LaunchAgents"
# The server's own code, copied so the repository can move or change branch.
rm -rf "$APP"
mkdir -p "$APP"
cp -R "$HERE/backend/app" "$APP/app"
find "$APP" -name '__pycache__' -prune -exec rm -rf {} +

if [ ! -x "$VENV/bin/python" ]; then
  echo "Setting up Python for the renderer (one time, a few minutes)…"
  "$PY" -m venv "$VENV"
fi
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet -r "$HERE/backend/requirements.txt"

[ -f "$HOME_DIR/.env" ] || echo "RENDER_SLOTS=2" > "$HOME_DIR/.env"

cat > "$HOME_DIR/run.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
cd "$HOME/.cbc/render"
set -a; . ./.env; set +a
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
echo "$(date '+%Y-%m-%d %H:%M:%S') starting the render helper"
cd app
exec ../venv/bin/python -m app.render_helper
EOF
chmod +x "$HOME_DIR/run.sh"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/caffeinate</string>
    <string>-i</string>
    <string>$HOME_DIR/run.sh</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>StandardOutPath</key><string>$HOME_DIR/render.log</string>
  <key>StandardErrorPath</key><string>$HOME_DIR/render.log</string>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl kickstart -k "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true

cat <<EOF

The render helper is running: this Mac now draws queued videos for the server.
Keep the Mac on and plugged in while it works.

Logs:    tail -f ~/.cbc/render/render.log
Faster:  RENDER_SLOTS=3 in ~/.cbc/render/.env, then run this again
Stop:    launchctl bootout gui/\$(id -u)/$LABEL
EOF
