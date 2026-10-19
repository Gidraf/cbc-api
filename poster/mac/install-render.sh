#!/usr/bin/env bash
# The render helper: this Mac draws the server's queued videos and sends them
# back — about two minutes a video instead of fifteen on a server with no GPU.
#
#   bash poster/mac/install-render.sh      install, or update after git pull
#
# On a new Mac, one line gets the code and runs this:
#
#   cd ~ && { [ -d cbc-api ] || git clone https://github.com/Gidraf/cbc-api.git; } && cd cbc-api && git checkout main && git pull && bash poster/mac/install-render.sh
#
# Installs what it needs: Homebrew's ffmpeg, Cairo, Pango and pkg-config, and
# LaTeX (BasicTeX, if no LaTeX is here) with the packages Manim uses to set
# the maths — that asks for your Mac password once. It reads the server's
# address and key from ~/.cbc/poster/.env, and asks for them on a Mac without
# the poster. Needs Google Chrome. RENDER_SLOTS in ~/.cbc/render/.env says
# how many videos draw at once (2).
set -euo pipefail

HERE="$(cd "$(dirname "$0")/../.." && pwd)"          # the repository
HOME_DIR="$HOME/.cbc/render"
APP="$HOME_DIR/app"
VENV="$HOME_DIR/venv"
LABEL="com.cbc.render"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

[ -d "/Applications/Google Chrome.app" ] || { echo "Google Chrome is needed: https://www.google.com/chrome/" >&2; exit 1; }

# ── Homebrew and the drawing libraries ──
if ! command -v brew >/dev/null 2>&1; then
  for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do if [ -x "$b" ]; then eval "$("$b" shellenv)"; fi; done
fi
if ! command -v brew >/dev/null 2>&1; then
  echo "Installing Homebrew (asks for your password)…"
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do if [ -x "$b" ]; then eval "$("$b" shellenv)"; fi; done
fi
echo "Installing ffmpeg, Cairo, Pango and pkg-config (skipped if already there)…"
brew install ffmpeg cairo pango pkg-config >/dev/null
export PKG_CONFIG_PATH="$(brew --prefix)/lib/pkgconfig:${PKG_CONFIG_PATH:-}"
# A Homebrew upgrade of one of ffmpeg's libraries can leave ffmpeg unable to
# start ("Library not loaded"): test it, and rebuild it against the new ones.
if ! ffmpeg -version >/dev/null 2>&1; then
  echo "ffmpeg does not start (a library it uses was upgraded) — reinstalling it…"
  brew reinstall ffmpeg >/dev/null
fi
ffmpeg -version >/dev/null 2>&1 || { echo "ffmpeg still does not start: run  brew doctor  and  brew reinstall ffmpeg" >&2; exit 1; }
FFMPEG="$(command -v ffmpeg)"

# ── LaTeX, for Manim's maths ──
export PATH="/Library/TeX/texbin:$PATH"
for d in /usr/local/texlive/*/bin/universal-darwin; do if [ -d "$d" ]; then export PATH="$d:$PATH"; fi; done
if ! command -v latex >/dev/null 2>&1; then
  echo "Installing BasicTeX for the maths (asks for your password)…"
  brew install --cask basictex
  export PATH="/Library/TeX/texbin:$PATH"
fi
if command -v tlmgr >/dev/null 2>&1; then
  echo "Adding the LaTeX packages Manim uses (asks for your password once)…"
  TL="tlmgr"; [ -w "$(dirname "$(command -v tlmgr)")" ] || TL="sudo tlmgr"
  $TL update --self >/dev/null 2>&1 || true
  $TL install standalone preview doublestroke relsize fundus-calligra wasysym physics dvisvgm rsfs wasy \
      cm-super babel-english amsfonts amsmath ragged2e everysel setspace microtype >/dev/null 2>&1 || \
      echo "  (some LaTeX packages did not install — the board draws any step Manim cannot)"
fi

# ── the server's address and key ──
if [ ! -f "$HOME/.cbc/poster/.env" ]; then
  echo "This Mac has no poster settings: the render helper needs the server's address and an API key."
  read -r -p "CBC address [https://cbc.gidraf.dev]: " URL
  URL="${URL:-https://cbc.gidraf.dev}"
  read -r -s -p "API key (hidden as you type): " KEY; echo
  mkdir -p "$HOME/.cbc/poster"
  printf 'CBC_API_URL=%s\nCBC_API_KEY=%s\n' "$URL" "$KEY" > "$HOME/.cbc/poster/.env"
  chmod 600 "$HOME/.cbc/poster/.env"
fi
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
echo "Installing the renderer's Python packages (Manim included)…"
"$VENV/bin/python" -m pip install --quiet -r "$HERE/backend/requirements.txt"
# The Mac keychain's certificates, for networks that inspect HTTPS (see app/render_helper.py).
"$VENV/bin/python" -m pip install --quiet "truststore==0.10.1"
"$VENV/bin/python" -c "import manim" 2>/dev/null && echo "  Manim: ready" || echo "  Manim: not installed — videos render without it"

[ -f "$HOME_DIR/.env" ] || echo "RENDER_SLOTS=2" > "$HOME_DIR/.env"

cat > "$HOME_DIR/run.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
cd "$HOME/.cbc/render"
set -a; . ./.env; set +a
export PATH="/Library/TeX/texbin:/opt/homebrew/bin:/usr/local/bin:$PATH"
for d in /usr/local/texlive/*/bin/universal-darwin; do if [ -d "$d" ]; then export PATH="$d:$PATH"; fi; done
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
Update:  cd ~/cbc-api && git pull && bash poster/mac/install-render.sh
EOF
