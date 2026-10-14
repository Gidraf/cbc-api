"""The Mac poster as one downloadable file, fetched with a one-time link."""
import subprocess
import sys
from pathlib import Path

import pytest

from app.services import poster_installer as P

POSTER = Path(__file__).resolve().parents[2] / "poster"


def test_the_installer_carries_the_poster_and_nothing_private():
    import base64
    import io
    import tarfile

    body = P.build(POSTER, "https://cbc.gidraf.dev", api_key="cbc_live_abc-123").decode()
    head, payload = body.split("__PAYLOAD__\n", 1)
    names = tarfile.open(fileobj=io.BytesIO(base64.b64decode(payload)), mode="r:gz").getnames()
    assert "poster/__main__.py" in names and "requirements.txt" in names and "mac/install.sh" in names
    assert not any("__pycache__" in n or n.endswith(".pyc") or Path(n).name.startswith(".env") for n in names)
    assert 'CBC_API_KEY="cbc_live_abc-123"' in head and 'CBC_DEFAULT_URL="https://cbc.gidraf.dev"' in head
    assert 'rm -f "$0"' in head


def test_nothing_from_outside_can_break_out_of_the_script():
    head = P.build(POSTER, 'https://x.dev"; rm -rf ~; "', api_key='k"; echo pwned; "').decode().split("__PAYLOAD__")[0]
    assert "rm -rf ~" not in head and "echo pwned" not in head


def test_a_missing_poster_folder_says_so(tmp_path):
    with pytest.raises(FileNotFoundError):
        P.tarball(tmp_path)


@pytest.mark.skipif(sys.platform != "darwin", reason="the script is for a Mac (base64 -D)")
def test_the_script_unpacks_and_hands_over_the_key_then_deletes_itself(tmp_path):
    body = P.build(POSTER, "https://cbc.gidraf.dev", api_key="cbc_live_k").decode()
    # The real install would load a launch agent: stand in for it.
    body = body.replace('bash "$DEST/mac/install.sh" "$@"',
                        """bash -c 'echo "ran $CBC_API_KEY $CBC_DEFAULT_URL"'""", 1)
    script = tmp_path / P.FILENAME
    script.write_text(body)
    out = subprocess.run(["bash", str(script)], env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert "ran cbc_live_k https://cbc.gidraf.dev" in out.stdout
    assert (tmp_path / ".cbc/poster-src/mac/install.sh").exists()
    assert not script.exists()


def test_the_link_is_one_use_and_only_for_the_poster(monkeypatch):
    from fastapi.testclient import TestClient

    from app.infra import db
    from app.main import app
    from app.routes import agent

    rows = {"tok": {"token": "tok", "what": "poster", "created_by": "gidraf", "used_at": None, "expires_at": None}}
    monkeypatch.setattr(db, "fetch_one", lambda sql, p=None: rows.get(p["token"]) if "what = 'poster'" in sql else None)
    monkeypatch.setattr(db, "execute", lambda sql, p=None: rows["tok"].update(used_at="now") if "used_at = NOW()" in sql else None)
    minted = {}
    monkeypatch.setattr(agent, "_mint_key", lambda auth, label, role="operator": minted.update(role=role) or "cbc_live_minted")
    monkeypatch.setenv("POSTER_SRC", str(POSTER))
    c = TestClient(app)
    r = c.get("/api/v1/play/poster/mac-installer/tok")
    assert r.status_code == 200 and b'CBC_API_KEY="cbc_live_minted"' in r.content
    assert "cbc-poster-installer.command" in r.headers["content-disposition"]
    assert minted["role"] == "poster"            # the poster's own role, not an operator's
    assert c.get("/api/v1/play/poster/mac-installer/tok").status_code == 404     # used
    assert c.get("/api/v1/play/poster/mac-installer/nope").status_code == 404


def test_with_two_macs_only_the_newest_posts(monkeypatch):
    from app.services import social_export as X

    monkeypatch.setattr(X, "pull_poster", lambda: {"poster_id": "spare-mac", "online": True})
    assert X.standing_by("spare-mac") == ""
    assert "spare-mac is the active poster" in X.standing_by("main-mac")
    assert X.standing_by("") == ""                      # an older poster that does not say who it is
    monkeypatch.setattr(X, "pull_poster", lambda: None)
    assert X.standing_by("main-mac") == ""
