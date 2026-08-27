"""Versions, labels and diffs for everything the factory generates.

Prompts are versioned in Langfuse and a label decides which version is served.
Content was not: every generation overwrote the last, so there was no way to
compare two attempts, keep a good one while trying a better one, or say which
version is the approved one.
"""
from __future__ import annotations

import pytest

from app.errors import ApiError
from app.services import artifact_registry as registry


@pytest.fixture
def db(monkeypatch):
    state = {"artifacts": {}, "labels": {}}

    def fetch_one(sql, params=None):
        params = params or {}
        if "COALESCE(MAX(version)" in sql:
            versions = [a["version"] for a in state["artifacts"].values()
                        if a["artifact_key"] == params["key"]]
            return {"v": max(versions) if versions else 0}
        if "content_hash = :hash" in sql:
            for a in sorted(state["artifacts"].values(), key=lambda x: -x["version"]):
                if a["artifact_key"] == params["key"] and a["content_hash"] == params["hash"]:
                    return a
            return None
        if "SELECT artifact_key FROM artifacts" in sql:
            return state["artifacts"].get(params["id"])
        if "FROM artifact_labels" in sql and "artifact_id" in sql:
            return state["labels"].get((params.get("key"), params.get("label")))
        if "SELECT * FROM artifacts" in sql:
            return state["artifacts"].get(params["id"])
        return None

    def fetch_all(sql, params=None):
        params = params or {}
        if "SELECT label FROM artifact_labels" in sql:
            return [{"label": label} for (_k, label), v in state["labels"].items()
                    if v["artifact_id"] == params["id"]]
        return []

    def execute(sql, params=None):
        params = params or {}
        if "INSERT INTO artifacts" in sql:
            state["artifacts"][params["artifact_id"]] = dict(params)
        elif "INSERT INTO artifact_labels" in sql:
            state["labels"][(params["key"], params["label"])] = {"artifact_id": params["id"]}
        elif "DELETE FROM artifact_labels" in sql:
            for key in [k for k, v in state["labels"].items()
                        if v["artifact_id"] == params.get("ref") or k[0] == params.get("ref")]:
                if k_label := key[1]:
                    if k_label == params.get("label"):
                        state["labels"].pop(key, None)
        elif "DELETE FROM artifacts" in sql:
            state["artifacts"].pop(params["id"], None)
        elif "UPDATE artifacts SET status" in sql:
            row = state["artifacts"].get(params["id"])
            if row:
                row["status"] = "approved" if "'approved'" in sql else "superseded"

    monkeypatch.setattr("app.infra.db.fetch_one", fetch_one)
    monkeypatch.setattr("app.infra.db.fetch_all", fetch_all)
    monkeypatch.setattr("app.infra.db.execute", execute)
    monkeypatch.setattr("app.infra.db.to_json", lambda v: v)
    return state


def _create(content, **over):
    kwargs = dict(kind="notes", grade="grade-pp1",
                  subject="Christian Religious Education",
                  strand="The Bible", sub_strand="A Holy Book")
    kwargs.update(over)
    return registry.create_version(content=content, **kwargs)


def test_a_second_generation_is_a_version_not_an_overwrite(db) -> None:
    first = _create({"title": "Draft one"})
    second = _create({"title": "Draft two"})

    assert first.version == 1
    assert second.version == 2
    assert first.artifact_id != second.artifact_id
    assert first.artifact_key == second.artifact_key


def test_an_identical_regeneration_does_not_add_noise(db) -> None:
    """Filling the history with byte-identical versions makes "what changed
    since the approved one" harder to answer, not easier."""
    first = _create({"title": "Same"})
    again = _create({"title": "Same"})

    assert again.artifact_id == first.artifact_id
    assert again.version == 1


def test_an_unknown_kind_is_refused(db) -> None:
    with pytest.raises(ApiError) as caught:
        _create({"title": "x"}, kind="haiku")
    assert caught.value.code == "VALIDATION_FAILED"
    assert "not a known artifact kind" in caught.value.message


def test_a_label_points_at_exactly_one_version(db) -> None:
    first = _create({"title": "one"})
    second = _create({"title": "two"})

    registry.set_label(first.artifact_id, "production")
    moved = registry.set_label(second.artifact_id, "production")

    assert moved["moved_from"] == first.artifact_id
    assert registry.labels_of(first.artifact_id) == []
    assert registry.labels_of(second.artifact_id) == ["production"]


def test_approving_supersedes_the_version_it_replaced(db) -> None:
    first = _create({"title": "one"})
    second = _create({"title": "two"})

    registry.set_label(first.artifact_id, "approved")
    registry.set_label(second.artifact_id, "approved")

    assert db["artifacts"][first.artifact_id]["status"] == "superseded"
    assert db["artifacts"][second.artifact_id]["status"] == "approved"


def test_an_unknown_label_is_refused(db) -> None:
    artifact = _create({"title": "one"})
    with pytest.raises(ApiError) as caught:
        registry.set_label(artifact.artifact_id, "blessed")
    assert "not a known label" in caught.value.message


def test_a_labelled_version_cannot_be_deleted(db) -> None:
    """Deleting the approved copy out from under everything reading it is the
    one deletion that must not be quiet."""
    artifact = _create({"title": "one"})
    registry.set_label(artifact.artifact_id, "approved")

    with pytest.raises(ApiError) as caught:
        registry.delete_version(artifact.artifact_id)

    assert "holds the label" in caught.value.message
    assert artifact.artifact_id in db["artifacts"]


def test_a_human_edit_creates_the_next_version(db) -> None:
    """Editing in place would make an approved version mean whatever it was
    last edited into."""
    first = _create({"title": "one"})
    edited = registry.update_content(first.artifact_id, {"title": "corrected"},
                                     edited_by="gidraf")

    assert edited.version == 2
    assert edited.parent_artifact_id == first.artifact_id
    assert edited.provenance["source"] == "human"
    assert db["artifacts"][first.artifact_id]["content"] == {"title": "one"}


def test_the_diff_names_what_changed() -> None:
    previous = registry.Artifact(artifact_id="a", version=1, content={
        "title": "A House of God",
        "slos": ["state one difference", "observe church buildings"],
    })
    current = registry.Artifact(artifact_id="b", version=2, content={
        "title": "A House of God",
        "slos": ["state three differences", "observe church buildings", "respect it"],
    })

    result = registry.diff(previous, current)

    assert result["counts"] == {"added": 1, "removed": 0, "changed": 1}
    changed = result["changed"][0]
    assert changed["path"] == "slos[0]"
    assert changed["was"] == "state one difference"
    assert not result["identical"]


def test_an_unchanged_regeneration_reads_as_identical() -> None:
    same = {"title": "A House of God"}
    result = registry.diff(
        registry.Artifact(artifact_id="a", version=1, content=same),
        registry.Artifact(artifact_id="b", version=2, content=dict(same)),
    )
    assert result["identical"]
    assert result["counts"] == {"added": 0, "removed": 0, "changed": 0}


def test_the_key_is_the_thing_not_the_attempt() -> None:
    key = registry.artifact_key(
        "notes", "grade-pp1", "Christian Religious Education", "The Bible", "A Holy Book"
    )
    assert key == "notes:grade-pp1:christian-religious-education:the-bible:a-holy-book"
    # Every kind the factory produces can be stored.
    for kind in ("strand", "sub_strand", "notes", "hour_module", "diagram",
                 "photo_prompt", "video_prompt", "experiment", "activity",
                 "question", "answer", "ingest"):
        assert kind in registry.KINDS


def test_the_static_routes_are_not_shadowed_by_the_id_route() -> None:
    """/artifacts/versions must not be read as an artifact called "versions"."""
    from app.main import app

    paths = [r.path for r in app.routes if hasattr(r, "path")]
    ordered = [p for p in paths if p.startswith("/api/v1/artifacts")]

    assert ordered.index("/api/v1/artifacts/versions") < ordered.index(
        "/api/v1/artifacts/{artifact_id}"
    )


def test_every_station_files_a_version(monkeypatch) -> None:
    """Review and approval are decisions about a specific version, so a
    generation that is not versioned cannot be approved at all."""
    source = open("app/routes/curriculum.py").read()

    assert '_record_artifact(\n            "sub_strand"' in source
    assert '_record_artifact(\n        "strand"' in source
    assert '"photo_prompt" if kind == "photo" else "video_prompt"' in source


def test_recording_a_version_never_breaks_the_generation() -> None:
    """Bookkeeping that fails the work it books is worse than no bookkeeping."""
    from app.routes import curriculum

    monkey = curriculum.artifact_registry.create_version
    try:
        curriculum.artifact_registry.create_version = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("table missing")
        )
        result = curriculum._record_artifact("notes", "grade-pp1", "CRE", {"a": 1})
        assert "error" in result
    finally:
        curriculum.artifact_registry.create_version = monkey
