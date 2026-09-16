"""The kit's installer must survive being run twice.

It removes the `cbc/` folder after installing — a coding agent that finds
Python in its workspace edits it instead of using the tools — so a second
run has nothing to copy. That must rewrite the config, not fail.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import zipfile
from pathlib import Path

import pytest

from app.services import agent_pack


def _unpack(kit: bytes, into: Path) -> None:
    with zipfile.ZipFile(io.BytesIO(kit)) as zf:
        zf.extractall(into)


def _run(folder: Path, home: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["sh", "install.sh"], cwd=folder, capture_output=True, text=True,
        env={**os.environ, "HOME": str(home)},
    )


@pytest.fixture
def kit():
    return agent_pack.build_kit(agent="antigravity", base_url="https://papers.example.co.ke",
                                api_key="cbc_live_test_key")


def test_first_run_installs_the_server_outside_the_workspace(tmp_path, kit):
    work, home = tmp_path / "cbc-papers", tmp_path / "home"
    _unpack(kit, work)
    out = _run(work, home)
    assert out.returncode == 0, out.stderr

    installed = home / ".cbc" / "antigravity"
    assert (installed / "cbc_mcp.py").exists() and (installed / ".env").exists()
    assert not (work / "cbc").exists(), "the workspace keeps no Python for the agent to edit"

    config = json.loads((home / ".gemini" / "antigravity" / "mcp_config.json").read_text())
    server = config["mcpServers"]["cbc"]
    assert server["args"] == [str(installed / "cbc_mcp.py")]
    assert server["env"]["CBC_API_URL"] == "https://papers.example.co.ke"
    assert server["env"]["CBC_API_KEY"] == "cbc_live_test_key"
    assert server["env"]["CBC_DOWNLOAD_DIR"] == str(work / "papers")
    assert "server version" in out.stdout


def test_running_it_again_rewrites_the_config_instead_of_failing(tmp_path, kit):
    work, home = tmp_path / "cbc-papers", tmp_path / "home"
    _unpack(kit, work)
    assert _run(work, home).returncode == 0
    (home / ".gemini" / "antigravity" / "mcp_config.json").unlink()

    out = _run(work, home)
    assert out.returncode == 0, out.stderr + out.stdout
    assert "No such file or directory" not in out.stderr
    assert "already at" in out.stdout
    config = json.loads((home / ".gemini" / "antigravity" / "mcp_config.json").read_text())
    assert config["mcpServers"]["cbc"]["env"]["CBC_API_KEY"] == "cbc_live_test_key"


def test_a_fresh_kit_unzipped_over_the_folder_updates_the_server(tmp_path, kit):
    work, home = tmp_path / "cbc-papers", tmp_path / "home"
    _unpack(kit, work)
    _run(work, home)
    installed = home / ".cbc" / "antigravity" / "cbc_mcp.py"
    installed.write_text("# stale server\n")

    _unpack(kit, work)          # the new download, extracted over it
    assert _run(work, home).returncode == 0
    assert "stale server" not in installed.read_text()
    assert "cbc_mcp" in installed.read_text() or "def main" in installed.read_text()


def test_an_empty_folder_says_what_to_do_rather_than_writing_a_broken_config(tmp_path, kit):
    work, home = tmp_path / "cbc-papers", tmp_path / "home"
    work.mkdir(parents=True)
    (work / "install.sh").write_text(agent_pack._installer("antigravity"))

    out = _run(work, home)
    assert out.returncode == 1
    assert "Download the kit again" in out.stdout
    assert not (home / ".gemini" / "antigravity" / "mcp_config.json").exists()


def test_the_cli_command_fetches_a_kit_before_installing(monkeypatch):
    """`sh install.sh` alone cannot work twice, so the copied command must
    always unzip a fresh kit over the folder first."""
    from app.infra import db
    from app.routes import agent as agent_routes
    from app.services import platform_settings

    monkeypatch.setattr(platform_settings, "public_base_url",
                        lambda request=None: "https://papers.example.co.ke")
    monkeypatch.setattr(db, "execute", lambda *a, **k: None)

    out = agent_routes.make_pack_link(
        agent_routes.PackLinkRequest(agent="antigravity", grade="grade-9"),
        request=None,
        auth=type("A", (), {"subject": "ops@example.com", "role": "operator", "auth_type": "session"})(),
    )
    command = out["curl"]
    assert command.index("curl") < command.index("unzip") < command.index("sh install.sh")
    assert "-d ~/cbc-papers" in command and "mkdir -p ~/cbc-papers" in command
    assert "/tmp/" in command, "the zip is not left in the agent's workspace"
    assert out["url"] in command and out["folder"] == "~/cbc-papers"
