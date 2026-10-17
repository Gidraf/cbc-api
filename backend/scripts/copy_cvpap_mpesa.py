"""Copy CVPAP's M-Pesa till into this repository's .env — nothing is printed.

    python3 backend/scripts/copy_cvpap_mpesa.py ../../ajiriwa/CVPAP/app/utils/config.py .env

CBC uses the same till with its own callback (the callback URL goes with each
payment request), so CVPAP's payments are untouched. Says which keys it set,
never their values. A random MPESA_CALLBACK_TOKEN is made if there is none.
"""
import re
import secrets
import sys
from pathlib import Path

src, env = Path(sys.argv[1]), Path(sys.argv[2] if len(sys.argv) > 2 else ".env")
text = src.read_text()


def value(name: str) -> str:
    m = re.search(rf'^\s*{name}\s*=\s*["\']([^"\']+)["\']', text, re.M)
    if not m:
        raise SystemExit(f"{name} is not in {src}")
    return m.group(1).strip()


want = {"MPESA_ENV": "production", "MPESA_TYPE": "till",
        "MPESA_CONSUMER_KEY": value("consumer_key"), "MPESA_CONSUMER_SECRET": value("consumer_secret"),
        "MPESA_SHORTCODE": value("paybill"), "MPESA_TILL_NUMBER": value("partyB"), "MPESA_PASSKEY": value("passkey")}
lines = env.read_text().splitlines() if env.exists() else []
have = {l.split("=", 1)[0].strip() for l in lines if "=" in l and not l.lstrip().startswith("#")}
if "MPESA_CALLBACK_TOKEN" not in have:
    want["MPESA_CALLBACK_TOKEN"] = secrets.token_urlsafe(24)
out = [l for l in lines if l.split("=", 1)[0].strip() not in want]
out += [f"{k}={v}" for k, v in want.items()]
env.write_text("\n".join(out) + "\n")
env.chmod(0o600)
print("Set in", env, ":", ", ".join(want))
