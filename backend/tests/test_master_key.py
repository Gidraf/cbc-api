"""CBC_MASTER_KEY has no default: missing, published or malformed keys stop startup."""
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from app.state import PUBLISHED_MASTER_KEY, load_master_key

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("value", ["", "   "])
def test_missing_key_refuses(value):
    with pytest.raises(RuntimeError, match="CBC_MASTER_KEY is not set"):
        load_master_key(value)


def test_published_key_refuses():
    with pytest.raises(RuntimeError, match="published in this repository"):
        load_master_key(PUBLISHED_MASTER_KEY)


def test_malformed_key_refuses():
    with pytest.raises(RuntimeError, match="not a valid Fernet key"):
        load_master_key("not-a-key")


def test_good_key_round_trips():
    f = load_master_key(Fernet.generate_key().decode())
    assert f.decrypt(f.encrypt(b"sk-test")) == b"sk-test"


def test_compose_has_no_fallback_key():
    compose = (ROOT / "docker-compose.yml").read_text()
    assert "${CBC_MASTER_KEY:?" in compose
    assert PUBLISHED_MASTER_KEY not in compose
    assert PUBLISHED_MASTER_KEY not in (ROOT / ".env.example").read_text()


def _run_rotation(tmp_path, old, new, *args):
    import os
    import sqlite3
    import subprocess
    import sys

    env = {**os.environ, "OLD_CBC_MASTER_KEY": old, "NEW_CBC_MASTER_KEY": new,
           "DATABASE_URL": f"sqlite:///{tmp_path / 'db.sqlite'}"}
    script = ROOT / "backend" / "scripts" / "rotate_master_key.py"
    # Fed on stdin, as it is run inside the api container.
    proc = subprocess.run([sys.executable, "-", *args], stdin=script.open(), env=env,
                          capture_output=True, text=True)
    rows = dict(sqlite3.connect(tmp_path / "db.sqlite").execute(
        "SELECT provider, encrypted_api_key FROM provider_configs").fetchall())
    return proc, rows


def _seed(tmp_path, rows):
    import sqlite3

    db = sqlite3.connect(tmp_path / "db.sqlite")
    db.execute("CREATE TABLE provider_configs (provider TEXT PRIMARY KEY, encrypted_api_key TEXT)")
    db.executemany("INSERT INTO provider_configs VALUES (?, ?)", rows)
    db.commit()


def test_rotation_script_dry_run_then_apply(tmp_path):
    old, new = Fernet(PUBLISHED_MASTER_KEY), Fernet.generate_key().decode()
    _seed(tmp_path, [("openai", old.encrypt(b"sk-1").decode()),
                     ("anthropic", Fernet(new).encrypt(b"sk-2").decode()),
                     ("ollama", None)])

    proc, before = _run_rotation(tmp_path, PUBLISHED_MASTER_KEY, new, "--dry-run")
    assert proc.returncode == 0, proc.stderr
    assert "1 row(s) to re-encrypt, 1 already under the new key, 0 unreadable" in proc.stdout
    assert old.decrypt(before["openai"].encode()) == b"sk-1"

    proc, after = _run_rotation(tmp_path, PUBLISHED_MASTER_KEY, new)
    assert proc.returncode == 0, proc.stderr
    assert Fernet(new).decrypt(after["openai"].encode()) == b"sk-1"
    assert Fernet(new).decrypt(after["anthropic"].encode()) == b"sk-2"
    assert after["ollama"] is None


def test_rotation_script_writes_nothing_if_a_row_is_unreadable(tmp_path):
    old, new = Fernet(PUBLISHED_MASTER_KEY), Fernet.generate_key().decode()
    original = old.encrypt(b"sk-1").decode()
    _seed(tmp_path, [("openai", original),
                     ("gemini", Fernet(Fernet.generate_key()).encrypt(b"x").decode())])

    proc, after = _run_rotation(tmp_path, PUBLISHED_MASTER_KEY, new)
    assert proc.returncode == 1
    assert "decrypts under neither key" in proc.stdout
    assert after["openai"] == original
