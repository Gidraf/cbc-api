"""Every drawing a sub-strand has, in one place, as the book sees them.

The console listed visuals per diagram ARTIFACT VERSION; the book numbers its
figures across the whole lesson. So `DIAGRAM 1.2` on the page lived in a
different artifact version from `1.1`, behind a row of version tabs every one
of which was labelled "Integers". There was no route to it at all — the
operator could see the figure on the page and had no way to touch it.
"""
from __future__ import annotations

import inspect

import pytest

from app.routes import curriculum
from app.services import asset_uploads, lesson_assets

ROWS = [
    {"asset_id": "ast_line", "kind": "diagram", "what": "Number line",
     "title": "Representation of Integers on a Number Line",
     "alt_text": "A number line.", "storage_url": "", "source": "drawn",
     "svg": '<svg viewBox="0 0 340 200"><rect x="12" y="12" width="316" '
            'height="120" fill="none" stroke="#111"/>'
            '<text x="12" y="180" font-size="14">Number line</text></svg>'},
    {"asset_id": "ast_ops", "kind": "diagram", "what": "Operations",
     "title": "Basic Operations on Integers", "alt_text": "Four operations.",
     "storage_url": "", "source": "drawn",
     # The real failure: the explanations run into each other under the line.
     "svg": '<svg viewBox="0 0 340 200">'
            '<line x1="12" y1="100" x2="320" y2="100" stroke="#111"/>'
            '<text x="12" y="150" font-size="11">Addition — combines two integers</text>'
            '<text x="120" y="150" font-size="11">Subtraction — removes one integer</text>'
            '<text x="12" y="30" font-size="14">Operations</text></svg>'},
]


@pytest.fixture
def filed(monkeypatch):
    monkeypatch.setattr(asset_uploads, "list_for", lambda *a, **k: list(ROWS))
    monkeypatch.setattr(asset_uploads, "by_id",
                        lambda aid: [r for r in ROWS if r["asset_id"] == aid])


def test_the_asset_id_travels_with_the_picture() -> None:
    """Without it every figure on the page is anonymous, and nothing can offer
    to change or delete this exact drawing."""
    source = inspect.getsource(lesson_assets.collect)

    assert '"asset_id": str(row.get("asset_id") or "")' in source


def test_the_library_numbers_them_the_way_the_page_does(filed, monkeypatch) -> None:
    monkeypatch.setattr(lesson_assets, "collect",
                        lambda g, s, ss="": [
                            {"kind": "diagram", "title": r["title"],
                             "svg": r["svg"], "url": "", "alt": r["alt_text"],
                             "asset_id": r["asset_id"], "source": "drawn"}
                            for r in ROWS])

    out = curriculum.factory_diagrams(grade="grade-9", subject="Mathematics",
                                      sub_strand="Integers", _=None)

    assert [d["number"] for d in out["diagrams"]] == ["1.1", "1.2"]
    assert [d["title"] for d in out["diagrams"]] == [
        "Representation of Integers on a Number Line",
        "Basic Operations on Integers"]
    assert all(d["editable"] for d in out["diagrams"]), "each one reachable"


def test_each_one_carries_what_is_wrong_with_it(filed, monkeypatch) -> None:
    monkeypatch.setattr(lesson_assets, "collect",
                        lambda g, s, ss="": [
                            {"kind": "diagram", "title": ROWS[1]["title"],
                             "svg": ROWS[1]["svg"], "url": "", "alt": "",
                             "asset_id": "ast_ops", "source": "drawn"}])

    only = curriculum.factory_diagrams(grade="grade-9", subject="Mathematics",
                                       sub_strand="Integers", _=None)["diagrams"][0]

    assert only["layout"]["fits"] is False
    assert only["layout"]["overlapping_labels"] == 1
    assert any("sit on top of" in f for f in only["layout"]["findings"])


def test_a_drawing_already_filed_can_be_mended_without_redrawing(filed) -> None:
    """Trimming the explanation off a label happens when a drawing is MADE. A
    figure filed before that went in still prints "Addition — combines two
    integers" struck through its own line-work, and redrawing it from scratch
    to fix a label is a poor trade."""
    stored: dict = {}

    class _Auth:
        subject = "someone"

    import app.services.asset_uploads as au
    original = au.file_drawing
    au.file_drawing = lambda **k: stored.update(k) or {
        "asset_id": "ast_ops", "storage_url": "", "stored_in_minio": True}
    try:
        out = curriculum.factory_edit_drawing(
            "ast_ops", curriculum.EditDrawingRequest(repair=True), auth=_Auth())
    finally:
        au.file_drawing = original

    assert out["changed"] is True
    assert any("Cut the explanation" in r for r in out["repairs"])
    assert "combines two integers" not in stored["svg"]
    assert "removes one integer" not in stored["svg"]
    # Repair trims and enlarges; it does not MOVE anything. Cutting the
    # explanations is enough here because they were what collided.
    assert out["layout"]["overlapping_labels"] == 0
    assert stored["source"] == "repaired"


def test_a_drawing_with_nothing_to_mend_is_left_alone(filed) -> None:
    class _Auth:
        subject = "someone"

    out = curriculum.factory_edit_drawing(
        "ast_line", curriculum.EditDrawingRequest(repair=True), auth=_Auth())

    assert out["changed"] is False
    assert out["repairs"] == []


def test_a_pasted_edit_is_sanitised_before_it_is_filed() -> None:
    source = inspect.getsource(curriculum.factory_edit_drawing)

    assert "extract_and_sanitize_svg" in source
    assert "asset_uploads.file_drawing(" in source


def test_an_id_that_is_not_filed_says_so() -> None:
    source = inspect.getsource(curriculum.factory_edit_drawing)

    assert 'raise_api_error("NOT_FOUND"' in source


# ── the console ─────────────────────────────────────────────────────────────

from pathlib import Path  # noqa: E402

FRONTEND = Path(__file__).resolve().parents[2] / "frontend-web"


def test_the_station_lists_the_drawings_the_book_shows() -> None:
    factory = " ".join((FRONTEND / "src/views/ContentFactory.tsx").read_text().split())

    assert "DiagramLibrary" in factory
    assert 'station.id === "visuals"' in factory


def test_each_drawing_can_be_reached_mended_and_deleted() -> None:
    panel = " ".join((FRONTEND / "src/ui/DiagramLibrary.tsx").read_text().split())

    assert "DIAGRAM {row.number}" in panel, "numbered as the page numbers them"
    assert "Fix the labels" in panel
    assert "Save this drawing" in panel
    assert "Delete it" in panel
    # Deleting is a second press, never one.
    assert "confirming === row.asset_id" in panel
    # And it is shown at the size it prints, not stretched across the panel.
    assert 'width: "85mm"' in panel


def test_a_version_can_be_deleted_but_not_an_approved_one() -> None:
    """Nine versions for one sub-strand, most of them attempts nobody will
    read again. But an approved version is what coverage counts and what a
    teacher is handed."""
    review = " ".join((FRONTEND / "src/views/VersionReview.tsx").read_text().split())

    assert "useDeleteVersion" in review
    assert 'disabled={data.labels.includes("approved")}' in review
    assert "Take the label off first" in review
    assert "confirmingDelete" in review, "a confirmation, not a single press"


def test_deleting_a_version_does_not_leave_the_screen_asking_for_it() -> None:
    """The delete worked and the screen reported

        Could not load this — No artifact 'art_diagram_561a62b0198f0ead'.

    because it went on holding the id it had just deleted: the mutation
    invalidated that artifact's query, which refetched it, which 404'd.
    """
    queries = " ".join((FRONTEND / "src/lib/queries.ts").read_text().split())

    deleting = queries.split("export function useDeleteVersion()")[1][:900]
    assert "qc.removeQueries({ queryKey: keys.artifact(artifactId) })" in deleting
    assert 'invalidateQueries({ queryKey: ["artifact"] })' not in deleting, \
        "invalidating refetches the version that no longer exists"


def test_the_screen_moves_to_a_surviving_version() -> None:
    review = " ".join((FRONTEND / "src/views/VersionReview.tsx").read_text().split())

    # Worked out BEFORE the delete: afterwards the sibling list no longer
    # carries the version being removed.
    assert "const next = rows.find((v) => v.artifact_id !== data.artifact_id)" in review
    assert "if (next) select(next); else setPicked('')".replace("'", '"') in review
    # And a parent still naming the deleted version must not re-select it.
    assert "!deleted.includes(artifactId)" in review
