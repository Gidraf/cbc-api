#!/usr/bin/env bash
# Stops the poster and removes it from login. Your logged-in Chrome profile is
# kept unless you pass --all (then every platform needs logging in again).
set -euo pipefail
LABEL="com.cbc.poster"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
if [ "${1:-}" = "--all" ]; then
  rm -rf "$HOME/.cbc/poster"
  echo "Removed the poster, its settings and its Chrome profile."
else
  rm -rf "$HOME/.cbc/poster/app" "$HOME/.cbc/poster/venv" "$HOME/.cbc/poster/run.sh"
  echo "Removed the poster. Kept ~/.cbc/poster/.env and the Chrome profile (logins)."
  echo "To remove those too: bash poster/mac/uninstall.sh --all"
fi
