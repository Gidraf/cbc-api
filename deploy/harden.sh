#!/usr/bin/env bash
# Makes the server's secrets its own and checks what the internet can reach.
# Run it on the server, from the repository, after `git pull` and before
# `docker compose up -d --build`:
#
#   cd /root/education/cbc-api && git pull && bash deploy/harden.sh
#
# It never prints a secret. It backs up .env first (.env.bak.<time>, readable
# only by you) and changes only what is missing or weak:
#
#   JWT_SECRET            missing/weak      -> a new random one (everyone signs in again)
#   CBC_MASTER_KEY        missing/published -> a new key; saved provider keys moved to it
#   MPESA_CALLBACK_TOKEN  missing           -> a new random one
#   LANGFUSE_NEXTAUTH_SECRET default        -> a new random one (Langfuse logs you out once)
#   *_PASSWORD            default/short     -> emptied (then: python -m app.admin_tools reset-password)
#   DEVELOPER_API_KEY     example/short     -> emptied
#
# Then it reports, without changing them: MinIO's default keys, Langfuse's
# salt, and every port that is open to the internet.
set -euo pipefail

cd "$(dirname "$0")/.."
[ -f .env ] || { echo "No .env here ($(pwd)). Run this from the repository on the server." >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 is needed." >&2; exit 1; }

STAMP="$(date +%Y%m%d%H%M%S)"
cp .env ".env.bak.$STAMP"
chmod 600 .env ".env.bak.$STAMP"
echo "Backed up .env to .env.bak.$STAMP"
echo

PUBLISHED_MASTER_KEY="u8iP_EgFrh50kABm2MvxAfv5mN53uV8SQEgrMwJwztw="

# get NAME -> the value in .env (empty if absent); set NAME VALUE -> write it.
get() { python3 - "$1" <<'PY'
import sys
name = sys.argv[1]
val = ""
for line in open(".env", encoding="utf-8"):
    s = line.strip()
    if s.startswith(name + "="):
        val = s.split("=", 1)[1].strip().strip('"').strip("'")
print(val, end="")
PY
}
set_env() { NAME="$1" VALUE="$2" python3 - <<'PY'
import os
name, value = os.environ["NAME"], os.environ["VALUE"]
lines = open(".env", encoding="utf-8").read().splitlines()
out, done = [], False
for line in lines:
    if line.strip().startswith(name + "="):
        if not done:
            out.append(f"{name}={value}")
            done = True
        continue
    out.append(line)
if not done:
    out.append(f"{name}={value}")
open(".env", "w", encoding="utf-8").write("\n".join(out) + "\n")
PY
}
random_token() { python3 -c "import secrets; print(secrets.token_urlsafe(${1:-48}))"; }
changed=()
warn=()

# ── signing secret ──
J="$(get JWT_SECRET)"
case "$J" in ""|change-me-jwt-secret|change-this-jwt-secret|changeme|secret) weak=1 ;; *) weak=0 ;; esac
[ "${#J}" -lt 32 ] && weak=1
if [ "$weak" = 1 ]; then set_env JWT_SECRET "$(random_token 48)"; changed+=("JWT_SECRET (new; everyone signs in again)"); fi

# ── M-Pesa callback token ──
if [ -z "$(get MPESA_CALLBACK_TOKEN)" ]; then set_env MPESA_CALLBACK_TOKEN "$(random_token 32)"; changed+=("MPESA_CALLBACK_TOKEN (new)"); fi

# ── Langfuse login secret (its salt is only reported: changing it breaks Langfuse's API keys) ──
N="$(get LANGFUSE_NEXTAUTH_SECRET)"
if [ -z "$N" ] || [ "$N" = "langfuse-secret-key-32-chars-long!" ]; then
  set_env LANGFUSE_NEXTAUTH_SECRET "$(random_token 32)"; changed+=("LANGFUSE_NEXTAUTH_SECRET (new; Langfuse signs you out once)")
fi
S="$(get LANGFUSE_SALT)"
if [ -z "$S" ] || [ "$S" = "langfuse-salt-key-32-chars-long!" ]; then
  warn+=("Langfuse uses its default SALT. Changing it invalidates Langfuse's API keys: set LANGFUSE_SALT to a random value only together with making new Langfuse keys.")
fi

# ── built-in account passwords ──
for NAME in ADMIN_PASSWORD OPERATOR_PASSWORD REVIEWER_PASSWORD DEVELOPER_PASSWORD; do
  V="$(get "$NAME")"
  if [ -n "$V" ]; then
    case "$V" in admin123|operator123|reviewer123|developer123|admin|password|changeme) bad=1 ;; *) bad=0 ;; esac
    [ "${#V}" -lt 12 ] && bad=1
    if [ "$bad" = 1 ]; then set_env "$NAME" ""; changed+=("$NAME (was a default or short: emptied)"); fi
  fi
done

# ── fixed developer key ──
D="$(get DEVELOPER_API_KEY)"
if [ -n "$D" ] && { [ "${#D}" -lt 32 ] || echo "$D" | grep -qi example; }; then
  set_env DEVELOPER_API_KEY ""; changed+=("DEVELOPER_API_KEY (was an example or short: emptied)")
fi

# ── the master key: move the saved provider keys, then switch ──
M="$(get CBC_MASTER_KEY)"
if [ -z "$M" ] || [ "$M" = "$PUBLISHED_MASTER_KEY" ]; then
  echo "CBC_MASTER_KEY is missing or the one published in the repository: moving the saved provider keys to a new key."
  NEW_KEY="$(python3 -c 'import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())')"
  OLD_KEY="${M:-$PUBLISHED_MASTER_KEY}"
  echo "  Building the api image (it has the rotation script)…"
  docker compose build api >/dev/null
  if OLD_MASTER_KEY="$OLD_KEY" NEW_MASTER_KEY="$NEW_KEY" \
       docker compose run --rm --no-deps -e OLD_MASTER_KEY -e NEW_MASTER_KEY api python -m app.admin_tools rotate-master-key; then
    set_env CBC_MASTER_KEY "$NEW_KEY"
    changed+=("CBC_MASTER_KEY (new; saved provider keys moved to it)")
  else
    warn+=("Moving the saved provider keys failed, so CBC_MASTER_KEY was NOT changed. Nothing was lost; see the message above.")
  fi
  unset NEW_KEY OLD_KEY
fi

# ── reported, not changed ──
MA="$(get MINIO_ACCESS_KEY)"; MS="$(get MINIO_SECRET_KEY)"
if [ -z "$MA" ] || [ "$MA" = "minioadmin" ] || [ -z "$MS" ] || [ "$MS" = "minioadmin" ]; then
  warn+=("MinIO uses its default keys (minioadmin). Anyone who can reach MinIO can read and replace every file. Change MINIO_ROOT_USER/MINIO_ROOT_PASSWORD on the MinIO server, then MINIO_ACCESS_KEY/MINIO_SECRET_KEY here to match.")
fi
if command -v ss >/dev/null; then
  OPEN="$(ss -Htln 2>/dev/null | awk '{print $4}' | grep -E '^(0\.0\.0\.0|\*|\[::\]):' | sed -E 's/.*:([0-9]+)$/\1/' | sort -un | tr '\n' ' ')"
  for P in $OPEN; do
    case "$P" in
      22|80|443) ;;
      5432|6379|9000|9001|3000|3001|5173|8000|6080|6090)
        warn+=("Port $P is open to the internet (listening on every address). After this deploy the app's own ports listen on 127.0.0.1; if $P is still open afterwards, close it (it is not the app's: check what runs it with: ss -tlnp | grep :$P).") ;;
      *) warn+=("Port $P is open to the internet: check it is meant to be (ss -tlnp | grep :$P).") ;;
    esac
  done
fi
NGINX_FILE="$(grep -rlE 'server_name[^;]*cbc\.gidraf\.dev' /etc/nginx/ 2>/dev/null | grep -v '\.bak' | head -1 || true)"
if [ -n "$NGINX_FILE" ] && grep -E 'proxy_pass' "$NGINX_FILE" | grep -vqE '127\.0\.0\.1|localhost|unix:'; then
  warn+=("nginx ($NGINX_FILE) forwards to an address that is not 127.0.0.1/localhost. The app's ports now listen on 127.0.0.1 only: point proxy_pass at http://127.0.0.1:<port> before deploying.")
fi

chmod 600 .env
echo
echo "Changed in .env:"
if [ ${#changed[@]} -eq 0 ]; then echo "  nothing — it was already in order"; else printf '  • %s\n' "${changed[@]}"; fi
if [ ${#warn[@]} -gt 0 ]; then echo; echo "Look at these yourself:"; printf '  ! %s\n' "${warn[@]}"; fi
cat <<'EOF'

Next:
  docker compose up -d --build
  docker compose logs api | grep -iE "switched off|too weak|CBC_MASTER_KEY|JWT_SECRET" || true

An account the logs say was switched off used an old default password. Give it a new one (printed once):
  docker compose exec api python -m app.admin_tools reset-password --username admin
EOF
