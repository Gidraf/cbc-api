#!/usr/bin/env bash
# Brings the server up to date with GitHub, in one command:
#
#   bash deploy/update.sh
#
# 1. fetches main (and its version tags) and merges it: a fast-forward when
#    the server has nothing of its own, a merge commit when it has — so no
#    `--no-ff` or "divergent branches" question;
# 2. builds the images one at a time — api (which every backend service runs),
#    the poster, the console — so the server never unpacks them side by side;
# 3. starts what changed and waits for /health to report the new version;
# 4. drops the images the build left behind, so the disk does not fill up.
#
# A build that fails changes nothing that is running: the old containers keep
# serving, and the reason is printed (and kept in .deploy/history.log).
#
# deploy/autodeploy.sh runs this every two minutes with --if-changed, which
# does nothing unless GitHub has something new.
#
#   --if-changed   only when main has moved (and, for a minute or two, only
#                  once the release workflow has tagged its version)
#   --branch NAME  another branch than main (or DEPLOY_BRANCH=...)
set -euo pipefail

cd "$(dirname "$0")/.."
REPO="$(pwd)"
BRANCH="${DEPLOY_BRANCH:-main}"
IF_CHANGED=0
while [ $# -gt 0 ]; do
  case "$1" in
    --if-changed) IF_CHANGED=1 ;;
    --branch) BRANCH="$2"; shift ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

STATE="$REPO/.deploy"
mkdir -p "$STATE"
say() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*"; }
note() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$STATE/history.log"; }

# One deploy at a time: the timer never starts a second over a running one.
exec 9>"$STATE/lock"
if command -v flock >/dev/null && ! flock -n 9; then
  [ "$IF_CHANGED" = 1 ] || say "A deploy is already running — see .deploy/history.log."
  exit 0
fi

git fetch --quiet --tags origin "$BRANCH"
TARGET="$(git rev-parse "origin/$BRANCH")"
HEAD_NOW="$(git rev-parse HEAD)"
LAST="$(cat "$STATE/last" 2>/dev/null || true)"

if [ "$IF_CHANGED" = 1 ]; then
  if git merge-base --is-ancestor "$TARGET" HEAD && [ "$LAST" = "$HEAD_NOW" ]; then
    exit 0                                          # nothing new
  fi
  if [ "$(cat "$STATE/failed" 2>/dev/null || true)" = "$TARGET" ]; then
    exit 0                                          # this one failed already: not tried every two minutes
  fi
  # A push is tagged by the release workflow within a minute: wait for it, so
  # the deploy carries its version — but never more than ten minutes.
  if ! git describe --exact-match --tags --match 'v*' "$TARGET" >/dev/null 2>&1; then
    AGE=$(( $(date +%s) - $(git log -1 --format=%ct "$TARGET") ))
    [ "$AGE" -lt 600 ] && exit 0
  fi
fi

# Merge main in. A merge commit needs a name; the server may have none.
MERGE=(git)
if [ -z "$(git config user.email || true)" ]; then
  MERGE+=(-c user.name="CBC deploy" -c user.email="deploy@$(hostname)")
fi
if ! git merge-base --is-ancestor "$TARGET" HEAD; then
  say "Merging origin/$BRANCH ($(git log -1 --format='%h %s' "$TARGET"))"
  if ! "${MERGE[@]}" merge --no-edit "origin/$BRANCH"; then
    git merge --abort 2>/dev/null || true
    echo "$TARGET" > "$STATE/failed"
    note "FAILED merge of $TARGET — the server's own changes conflict with GitHub's (git status shows them)."
    say "Could not merge: the server's own changes conflict with GitHub's. Nothing was deployed."
    say "See them with: git status   (commit or drop them, then run this again)"
    exit 1
  fi
fi

VERSION="$(git describe --tags --match 'v*' --always 2>/dev/null || git rev-parse --short HEAD)"
SHA="$(git rev-parse --short HEAD)"
export APP_VERSION="$VERSION"
say "Deploying $VERSION ($SHA)"

for service in api social-poster frontend-web; do
  say "Building $service…"
  if ! docker compose build "$service"; then
    echo "$TARGET" > "$STATE/failed"
    note "FAILED build of $service for $VERSION ($SHA) — the running containers were left as they were."
    say "Building $service failed; what is running was not touched."
    say "The full error: docker compose build $service --progress=plain 2>&1 | tail -60"
    exit 1
  fi
done

say "Starting…"
docker compose up -d

# /health reports the version it runs: the deploy is done when it says ours.
PORT="${API_PORT:-8000}"
for _ in $(seq 1 60); do
  GOT="$(curl -fsS "http://127.0.0.1:$PORT/health" 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin).get("version",""))' 2>/dev/null || true)"
  [ "$GOT" = "$VERSION" ] && break
  sleep 3
done

docker image prune -f >/dev/null 2>&1 || true        # the images this build replaced

git rev-parse HEAD > "$STATE/last"
rm -f "$STATE/failed"
if [ "${GOT:-}" = "$VERSION" ]; then
  note "deployed $VERSION ($SHA)"
  say "Done: $VERSION is running."
else
  note "deployed $VERSION ($SHA) — /health did not report it within three minutes"
  say "Started $VERSION, but /health has not reported it yet: docker compose ps; docker compose logs --tail 50 api"
fi
