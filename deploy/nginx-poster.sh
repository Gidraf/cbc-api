#!/usr/bin/env bash
# Adds the browser poster's screen (noVNC on 127.0.0.1:6080) to the site at
# /poster/. Finds the nginx file that serves the domain, backs it up, inserts
# the location before the site's "location / {", tests nginx, and reloads —
# or puts the backup back if the test fails.
#
#   sudo bash deploy/nginx-poster.sh [domain]      (default: cbc.gidraf.dev)
set -euo pipefail

DOMAIN="${1:-cbc.gidraf.dev}"
FILE="$(grep -rlE "server_name[^;]*\b${DOMAIN//./\\.}\b" /etc/nginx/ 2>/dev/null | grep -v '\.bak' | head -1 || true)"
if [ -z "$FILE" ]; then
  echo "No nginx file serves $DOMAIN. Files that mention it:"
  grep -rl "$DOMAIN" /etc/nginx/ 2>/dev/null || echo "  (none)"
  exit 1
fi
echo "nginx file: $FILE"

if grep -q "location /poster/" "$FILE"; then
  echo "/poster/ is already there."
else
  BACKUP="$FILE.bak.$(date +%Y%m%d%H%M%S)"
  cp "$FILE" "$BACKUP"
  python3 - "$FILE" <<'PY'
import re, sys
path = sys.argv[1]
text = open(path).read()
m = re.search(r"\n([ \t]*)location / \{", text)
if not m:
    sys.exit("No 'location / {' in the file — add the /poster/ block by hand.")
ind = m.group(1)
block = "\n".join([
    f"{ind}location /poster/ {{",
    f"{ind}    proxy_pass http://127.0.0.1:6080/;",
    f"{ind}    proxy_http_version 1.1;",
    f"{ind}    proxy_set_header Upgrade $http_upgrade;",
    f"{ind}    proxy_set_header Connection \"upgrade\";",
    f"{ind}    proxy_set_header Host $host;",
    f"{ind}    proxy_read_timeout 3600s;",
    f"{ind}}}",
])
text = text[:m.start()] + "\n" + block + "\n" + text[m.start():]
open(path, "w").write(text)
print("Added /poster/.")
PY
  if ! nginx -t; then
    cp "$BACKUP" "$FILE"
    echo "nginx rejected the change; the original is back. Nothing was reloaded."
    exit 1
  fi
fi

nginx -t && systemctl reload nginx
echo "Reloaded. Check: curl -sI https://$DOMAIN/poster/vnc.html | head -3"
