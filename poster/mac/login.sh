#!/usr/bin/env bash
# Log in to the platforms in plain Chrome, with the poster's own profile.
#
#   bash poster/mac/login.sh
#
# Facebook and others ask for more checks (codes, "is this you?") when the
# window says "Chrome is being controlled by automated test software". This
# stops the poster, opens the same profile in ordinary Chrome so you can log
# in and answer any check yourself, and starts the poster again when you quit
# that Chrome window (Cmd+Q). The login stays in the profile.
set -euo pipefail

HOME_DIR="$HOME/.cbc/poster"
LABEL="com.cbc.poster"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
sleep 2   # let the poster's Chrome close and release the profile

echo "Log in to each site in the Chrome window that opens; quit it (Cmd+Q) when done."
open -n -W -a "Google Chrome" --args --user-data-dir="$HOME_DIR/profile" \
  --no-first-run --no-default-browser-check \
  https://www.facebook.com/ https://studio.youtube.com/ https://www.tiktok.com/login

if [ -f "$PLIST" ]; then
  launchctl bootstrap "gui/$(id -u)" "$PLIST"
  echo "The poster is running again. In the console press \"Check\" to confirm the logins."
fi
