#!/usr/bin/env bash
# Deploys what is pushed to GitHub, by itself: every two minutes the server
# looks at main and, when it has moved, runs deploy/update.sh.
#
# The server pulls; GitHub holds no key to it and needs no open port.
#
#   bash deploy/autodeploy.sh install   # start watching (run as root on the server)
#   bash deploy/autodeploy.sh status    # watching? and the last deploys
#   bash deploy/autodeploy.sh logs      # what each run printed
#   bash deploy/autodeploy.sh now       # deploy now, without waiting
#   bash deploy/autodeploy.sh remove    # stop watching
set -euo pipefail

cd "$(dirname "$0")/.."
REPO="$(pwd)"
UNIT=cbc-autodeploy

case "${1:-status}" in
  install)
    command -v systemctl >/dev/null || { echo "This needs systemd (Ubuntu/Debian servers have it)." >&2; exit 1; }
    cat > "/etc/systemd/system/$UNIT.service" <<EOF
[Unit]
Description=CBC: deploy what was pushed to GitHub
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=$REPO
ExecStart=/bin/bash $REPO/deploy/update.sh --if-changed
TimeoutStartSec=3600
EOF
    cat > "/etc/systemd/system/$UNIT.timer" <<EOF
[Unit]
Description=CBC: look for a new push every two minutes

[Timer]
OnBootSec=2min
OnUnitInactiveSec=2min
Persistent=true

[Install]
WantedBy=timers.target
EOF
    systemctl daemon-reload
    systemctl enable --now "$UNIT.timer"
    echo "Watching GitHub: a push to main is deployed within a few minutes."
    echo "Status: bash deploy/autodeploy.sh status   ·   Stop: bash deploy/autodeploy.sh remove"
    ;;
  remove)
    systemctl disable --now "$UNIT.timer" 2>/dev/null || true
    rm -f "/etc/systemd/system/$UNIT.service" "/etc/systemd/system/$UNIT.timer"
    systemctl daemon-reload
    echo "No longer deploying by itself. Deploy by hand: bash deploy/update.sh"
    ;;
  status)
    systemctl list-timers "$UNIT.timer" --no-pager 2>/dev/null || true
    echo
    echo "Running now: $(curl -fsS http://127.0.0.1:${API_PORT:-8000}/health 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin).get("version","?"))' 2>/dev/null || echo 'the API is not answering')"
    echo "Last deploys:"
    tail -n 10 .deploy/history.log 2>/dev/null || echo "  none yet"
    ;;
  logs)
    journalctl -u "$UNIT.service" -n 200 --no-pager
    ;;
  now)
    rm -f .deploy/failed
    bash deploy/update.sh
    ;;
  *)
    echo "Use: install | status | logs | now | remove" >&2; exit 2 ;;
esac
