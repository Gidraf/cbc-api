#!/usr/bin/env bash
# Started by launchd (see install.sh). Reads the settings and runs the poster.
set -euo pipefail
cd "$HOME/.cbc/poster"
set -a; . ./.env; set +a
# A Chrome that was killed leaves its profile locked by a process that is gone.
if ! pgrep -f -- "--user-data-dir=$HOME/.cbc/poster/profile" >/dev/null 2>&1; then
  rm -f profile/Singleton* 2>/dev/null || true
fi
echo "$(date '+%Y-%m-%d %H:%M:%S') starting the poster"
cd app
exec ../venv/bin/python -m poster
