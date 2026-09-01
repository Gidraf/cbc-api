"""The SVG is a file. Postgres keeps what points at it.

The markup was written to both `diagram_registry.svg_markup` and MinIO, with
nothing keeping the two in step: edit the object and the column is stale, edit
the column and the served file is stale, and no reader could say which copy it
got.
"""
from __future__ import annotations

import inspect
from pathlib import Path

from app.services import diagram_svg

BACKEND = Path(__file__).resolve().parents[1]


def test_a_stored_url_resolves_to_its_object() -> None:
    from app.infra.storage import object_storage

    assert object_storage.object_name_of(
        "http://host:9000/cbc-assets/diagrams/d1.svg") == "diagrams/d1.svg"
    # A save that could not reach MinIO hands back this shape; it has to read
    # the same way rather than being an unhandled case later.
    assert object_storage.object_name_of("local://cbc-assets/diagrams/d1.svg") == "diagrams/d1.svg"
    assert object_storage.object_name_of("") == ""


def test_the_column_wins_while_a_row_is_still_unswept() -> None:
    """Order matters: a row that still has its markup has not been filed yet,
    and its object may not exist."""
    row = {"diagram_id": "d1", "svg_markup": "<svg>old</svg>",
           "storage_url": "http://host:9000/cbc-assets/diagrams/d1.svg"}
    assert diagram_svg.svg_for(row) == "<svg>old</svg>"


def test_a_swept_row_is_read_from_the_file(monkeypatch) -> None:
    from app.infra import storage

    monkeypatch.setattr(storage.object_storage, "read_text",
                        lambda name: f"<svg>{name}</svg>")
    diagram_svg.forget()

    row = {"diagram_id": "d1", "svg_markup": "",
           "storage_url": "http://host:9000/cbc-assets/diagrams/d1.svg"}
    assert diagram_svg.svg_for(row) == "<svg>diagrams/d1.svg</svg>"
    assert diagram_svg.with_svg(row)["svg_markup"] == "<svg>diagrams/d1.svg</svg>"
    diagram_svg.forget()


def test_one_paper_does_not_fetch_the_same_diagram_ten_times(monkeypatch) -> None:
    """A paper reuses a diagram across variants, and rendering it fetches every
    diagram on it."""
    from app.infra import storage

    calls: list[str] = []
    monkeypatch.setattr(storage.object_storage, "read_text",
                        lambda name: calls.append(name) or "<svg/>")
    diagram_svg.forget()

    row = {"svg_markup": "", "storage_url": "http://h/cbc-assets/diagrams/d1.svg"}
    for _ in range(5):
        diagram_svg.svg_for(row)
    assert len(calls) == 1
    diagram_svg.forget()


def test_a_missing_object_leaves_a_gap_rather_than_failing_the_render(monkeypatch) -> None:
    from app.infra import storage

    monkeypatch.setattr(storage.object_storage, "read_text", lambda name: "")
    diagram_svg.forget()

    assert diagram_svg.svg_for(
        {"svg_markup": "", "storage_url": "http://h/cbc-assets/diagrams/gone.svg"}) == ""
    diagram_svg.forget()


def test_a_storage_outage_does_not_lose_the_diagram() -> None:
    """`save_svg` swallows a failure and returns a `local://` URL. Writing an
    empty column on that would lose the diagram outright."""
    source = (BACKEND / "app/services/diagram_dedup.py").read_text()

    assert 'stored_in_minio = not storage_url.startswith("local://")' in source
    assert '"svg_markup": "" if stored_in_minio else instrumented,' in source


def test_the_sweep_reads_back_before_it_clears_the_column() -> None:
    """"Saved" is not the same fact as "readable", and only the second one
    makes it safe to drop the copy in the database."""
    from app.services import data_repairs

    assert "004_diagram_svg_to_object_storage" in [r[0] for r in data_repairs.REPAIRS]

    source = inspect.getsource(data_repairs._file_diagrams_in_object_storage)
    # Upload, read back, and only then clear.
    upload = source.index("save_svg")
    clear = source.index("SET svg_markup = ''")
    assert source.index("read_text") < clear and upload < clear
    assert "not readable back from storage" in source
    # A row that cannot be filed keeps its markup rather than being emptied.
    assert "continue" in source


def test_no_reader_takes_the_column_directly_any_more() -> None:
    """A reader that reads the column gets an empty string for every swept row,
    which renders as a blank space on a printed paper and nothing in the logs.
    """
    for path in ("app/routes/exams.py", "app/routes/questions.py"):
        source = (BACKEND / path).read_text()
        assert "diagram_svg" in source, path
        assert 'row.get("svg_markup") or ""' not in source, path
        assert 'r.get("svg_markup", "")' not in source, path
