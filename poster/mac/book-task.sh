#!/usr/bin/env bash
# The booking run as a scheduled task on this Mac: it keeps the next weeks
# booked for the auto-poster. Needs the poster installed (install.sh) — it
# uses the same key and code.
#
#   bash poster/mac/book-task.sh install    schedule it (and write book.env)
#   bash poster/mac/book-task.sh preview    show what a run would book now
#   bash poster/mac/book-task.sh now        book now
#   bash poster/mac/book-task.sh remove     unschedule it
#
# What and how much: ~/.cbc/poster/book.env. When: BOOK_DAYS_OF_MONTH there
# ("1 15" = every two weeks or so, "1" = monthly) at BOOK_HOUR. A run missed
# while the Mac slept happens when it wakes.
set -euo pipefail

HOME_DIR="$HOME/.cbc/poster"
BOOK_ENV="$HOME_DIR/book.env"
LABEL="com.cbc.book"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

if [ ! -x "$HOME_DIR/venv/bin/python" ] || [ ! -f "$HOME_DIR/.env" ]; then
  echo "Install the poster first: bash poster/mac/install.sh" >&2
  exit 1
fi

if [ ! -f "$BOOK_ENV" ]; then
  cat > "$BOOK_ENV" <<'EOF'
# What the scheduled booking books. Edit, then: bash poster/mac/book-task.sh install
BOOK_GRADE=grade-9
BOOK_SUBJECT=Mathematics
# Empty = every topic in the subject, mixed. Or one topic, e.g. "Indices and Logarithms".
BOOK_SUB_STRAND=""
BOOK_DAYS=25
BOOK_LOW=5
BOOK_HIGH=15
# Space-separated: facebook tiktok instagram youtube linkedin
BOOK_PLATFORMS="facebook"
# Days of the month to run on, and the hour (24h).
BOOK_DAYS_OF_MONTH="1 15"
BOOK_HOUR=7
EOF
  chmod 600 "$BOOK_ENV"
  echo "Wrote $BOOK_ENV (Grade 9 Mathematics, 25 days, 5–15 videos a day, Facebook)."
fi

run() {   # $1: extra args for python -m poster.book
  ( set -a; . "$HOME_DIR/.env"; . "$BOOK_ENV"; set +a
    cd "$HOME_DIR/app" && exec ../venv/bin/python -m poster.book ${1:-} )
}

case "${1:-install}" in
  preview) run --preview ;;
  now) run ;;
  remove)
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    echo "The scheduled booking is off. (Settings kept in $BOOK_ENV.)" ;;
  install)
    set -a; . "$BOOK_ENV"; set +a
    ENTRIES=""
    for d in ${BOOK_DAYS_OF_MONTH:-1 15}; do
      ENTRIES="$ENTRIES    <dict><key>Day</key><integer>$d</integer><key>Hour</key><integer>${BOOK_HOUR:-7}</integer><key>Minute</key><integer>0</integer></dict>
"
    done
    cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>-c</string>
    <string>set -a; . "\$HOME/.cbc/poster/.env"; . "\$HOME/.cbc/poster/book.env"; set +a; cd "\$HOME/.cbc/poster/app" &amp;&amp; echo "\$(date '+%Y-%m-%d %H:%M') booking" &amp;&amp; exec ../venv/bin/python -m poster.book</string>
  </array>
  <key>StartCalendarInterval</key>
  <array>
$ENTRIES  </array>
  <key>StandardOutPath</key><string>$HOME_DIR/book.log</string>
  <key>StandardErrorPath</key><string>$HOME_DIR/book.log</string>
</dict>
</plist>
EOF
    plutil -lint "$PLIST" >/dev/null
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$PLIST"
    echo "Scheduled: books on day(s) ${BOOK_DAYS_OF_MONTH:-1 15} of each month at ${BOOK_HOUR:-7}:00."
    echo "Preview now:   bash poster/mac/book-task.sh preview"
    echo "Book now:      bash poster/mac/book-task.sh now"
    echo "Log:           tail ~/.cbc/poster/book.log" ;;
  *) echo "usage: book-task.sh install|preview|now|remove" >&2; exit 2 ;;
esac
