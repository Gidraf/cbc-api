#!/usr/bin/env bash
# Installs the CBC poster on this Mac: it posts from your own Google Chrome,
# on your own internet connection, with the accounts you log into yourself.
#
#   bash poster/mac/install.sh              install, or update after git pull
#   bash poster/mac/install.sh --reconfigure   ask for the address and key again
#
# Everything lives in ~/.cbc/poster. It starts at login and keeps the Mac
# awake (not the screen) while it runs. Remove it with poster/mac/uninstall.sh.
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"          # the poster/ folder
HOME_DIR="$HOME/.cbc/poster"
APP="$HOME_DIR/app"
VENV="$HOME_DIR/venv"
ENV_FILE="$HOME_DIR/.env"
LABEL="com.cbc.poster"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

if [ ! -d "/Applications/Google Chrome.app" ]; then
  echo "Google Chrome is not in /Applications. Install it from google.com/chrome, then run this again." >&2
  exit 1
fi

PY=""
for c in python3.12 python3.13 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
    PY="$(command -v "$c")"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.10 or newer is needed:  brew install python@3.12" >&2
  exit 1
fi
echo "Python: $PY ($("$PY" --version 2>&1))"

mkdir -p "$HOME_DIR"/{profile,shots,tmp} "$HOME/Library/LaunchAgents"
chmod 700 "$HOME_DIR"

# The poster's code, copied so the repo can move or change branch.
rm -rf "$APP"
mkdir -p "$APP"
cp -R "$HERE/poster" "$APP/poster"
cp "$HERE/requirements.txt" "$APP/requirements.txt"
cp "$HERE/mac/run.sh" "$HOME_DIR/run.sh"
chmod +x "$HOME_DIR/run.sh"
find "$APP" -name '__pycache__' -prune -exec rm -rf {} +

if [ ! -x "$VENV/bin/python" ]; then
  "$PY" -m venv "$VENV"
fi
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet -r "$APP/requirements.txt"
# No browser download: it drives the Google Chrome you already have.

if [ ! -f "$ENV_FILE" ] || [ "${1:-}" = "--reconfigure" ]; then
  read -r -p "CBC address [https://cbc.gidraf.dev]: " URL
  URL="${URL:-https://cbc.gidraf.dev}"
  echo "Paste a CBC API key that belongs to a video maker (it is not shown as you paste):"
  read -r -s KEY
  echo
  if [ -z "$KEY" ]; then
    echo "No key given; nothing was installed as a service." >&2
    exit 1
  fi
  umask 077
  cat > "$ENV_FILE" <<EOF
POSTER_MODE=local
CBC_API_URL=$URL
CBC_API_KEY=$KEY
BROWSER_CHANNEL=chrome
POSTER_ID=$( (scutil --get ComputerName 2>/dev/null || hostname) | tr ' ' '-' | tr -cd '[:alnum:]._-')
POLL_SECONDS=60
YOUTUBE_MADE_FOR_KIDS=no
EOF
  unset KEY
  chmod 600 "$ENV_FILE"
  echo "Saved the settings in $ENV_FILE (only you can read it)."
fi

# Check the key before starting anything.
set -a; . "$ENV_FILE"; set +a
CODE="$(curl -s -o /dev/null -w '%{http_code}' -X POST -H "X-API-Key: $CBC_API_KEY" \
        -H 'Content-Type: application/json' -d "{\"poster_id\":\"$POSTER_ID\",\"status\":{\"online\":true,\"mode\":\"local\",\"note\":\"Installing\"}}" \
        "$CBC_API_URL/api/v1/play/poster/heartbeat" || true)"
case "$CODE" in
  200) echo "The CBC API accepted the key." ;;
  401) echo "The CBC API rejected the key — run: bash poster/mac/install.sh --reconfigure" >&2; exit 1 ;;
  403) echo "That key's account may not make videos (ask an admin to add it to video makers)." >&2; exit 1 ;;
  *)   echo "Could not reach $CBC_API_URL (HTTP $CODE). Installing anyway; it will keep trying." >&2 ;;
esac

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
  <key>ProcessType</key><string>Interactive</string>
  <key>StandardOutPath</key><string>$HOME_DIR/poster.log</string>
  <key>StandardErrorPath</key><string>$HOME_DIR/poster.log</string>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl kickstart -k "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true

cat <<EOF

The poster is running. A Chrome window with its own profile opens shortly —
it is separate from your everyday Chrome, so your normal browsing is untouched.

Next, in the console (Play → Auto-post):
  1. Press "Log in" for each platform; log in in that Chrome window yourself.
  2. Press "Check", then "Dry run" on one platform before turning posting on.

Logs:    tail -f ~/.cbc/poster/poster.log
Stop:    launchctl bootout gui/\$(id -u)/$LABEL
Start:   launchctl bootstrap gui/\$(id -u) $PLIST
Remove:  bash poster/mac/uninstall.sh
EOF
