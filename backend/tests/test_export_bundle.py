"""Everything generated, as a folder of JSON you can review as a project.

Content that only exists inside a console is content nobody can review
properly. Reviewing a curriculum means opening it in an editor, searching
across it, and diffing this week's against last week's.
"""
from __future__ import annotations

import io
import json
import pathlib
import zipfile
from unittest.mock import patch

from app.services import export_bundle

BACKEND = pathlib.Path(__file__).resolve().parents[1]
FRONTEND = BACKEND.parent / "frontend-web"

_SUB = {
    "grade": "grade-pp1", "subject": "Christian Religious Education",
    "strand_id": "1.0", "strand_name": "Creation",
    "sub_strand_id": "1.1", "sub_strand_name": "Our God",
    "allocated_hours": "7 lessons",
    "slos": ["identify three qualities of God"],
    "source_pages": [202, 203, 207],
}


def _only_substrands(sql, params):
    return [dict(_SUB)] if "curriculum_substrands" in sql else []


def _export(**kw):
    with patch.object(export_bundle, "_rows", _only_substrands):
        return export_bundle.to_zip(kw.get("grade", "grade-pp1"),
                                    kw.get("subject", "Christian Religious Education"))


def _names(blob: bytes) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        return sorted(z.namelist())


def _read(blob: bytes, suffix: str) -> bytes:
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        name = next(n for n in z.namelist() if n.endswith(suffix))
        return z.read(name)


def test_the_export_is_a_folder_tree_not_one_blob():
    names = _names(_export()[0])

    assert any(n.endswith("/manifest.json") for n in names)
    assert any(n.endswith("/README.md") for n in names)
    assert any(n.endswith("curriculum/structure.json") for n in names)
    assert any(n.endswith("sub-strands/creation__our-god.json") for n in names)


def test_filenames_come_from_the_curriculum_not_from_database_ids():
    """So a diff pairs the right files, and a reviewer can find the one they
    mean without consulting a lookup table."""
    names = _names(_export()[0])
    target = next(n for n in names if "sub-strands/" in n)

    assert target.endswith("creation__our-god.json")
    # No uuids, hashes or row ids anywhere in the path.
    assert not any(part.startswith(("art_", "job_", "cd_")) for part in target.split("/"))


def test_two_exports_of_unchanged_content_are_byte_identical():
    """Without this a re-export rewrites every file and the diff is noise
    rather than the change."""
    first, _ = _export()
    second, _ = _export()

    def files(blob):
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            # The manifest carries the export time by design.
            return {n: z.read(n) for n in sorted(z.namelist()) if "manifest" not in n}

    assert files(first) == files(second)


def test_json_keys_are_sorted_so_a_diff_shows_the_change():
    body = _read(_export()[0], "creation__our-god.json").decode()
    keys = [line.split('"')[1] for line in body.splitlines()
            if line.startswith('  "')]
    assert keys == sorted(keys)


def test_the_manifest_records_which_generator_produced_it():
    from app.services.generation_version import VERSION

    manifest = json.loads(_read(_export()[0], "manifest.json"))
    assert manifest["generator"] == VERSION
    assert manifest["counts"]["sub_strands"] == 1
    assert manifest["grade"] == "grade-pp1"


def test_a_subject_wide_export_names_itself_for_all_subjects():
    with patch.object(export_bundle, "_rows", _only_substrands):
        _, report = export_bundle.to_zip("grade-pp1")
    manifest_path = "cbc-grade-pp1/manifest.json"
    assert manifest_path in [f"cbc-grade-pp1/{p}" for p in report.files]


def test_a_missing_table_does_not_fail_the_whole_export():
    """A deployment without one of these tables should still export the rest."""
    def explode(sql, params):
        if "substrand_media" in sql:
            raise RuntimeError("relation does not exist")
        return [dict(_SUB)] if "curriculum_substrands" in sql else []

    with patch.object(export_bundle, "_rows", export_bundle._rows):
        pass  # the real _rows already swallows and logs

    with patch("app.infra.db.fetch_all", side_effect=explode):
        files = export_bundle.collect("grade-pp1", "Christian Religious Education")
    assert any("structure.json" in p for p in files)


def test_slugs_are_filesystem_safe_and_stable():
    assert export_bundle.slug("Bible Story: David and Goliath") == "bible-story-david-and-goliath"
    assert export_bundle.slug("God our Creator") == "god-our-creator"
    assert export_bundle.slug("") == "unnamed"
    assert export_bundle.slug("4.3 Sharing with Others") == "4-3-sharing-with-others"


def test_the_readme_explains_how_to_review_it_as_a_project():
    body = _read(_export()[0], "README.md").decode()
    assert "git diff" in body
    assert "rubric_source" in body, "a reviewer needs to know which rubrics are KICD's"


def test_the_download_cannot_be_a_plain_link():
    """A plain <a href> carries no Authorization header, so the browser
    downloads the sign-in page instead of the archive."""
    api = (FRONTEND / "src/api.ts").read_text()
    assert "export async function fetchBlob" in api
    assert "Authorization" in api[api.index("fetchBlob"):]

    queries = (FRONTEND / "src/lib/queries.ts").read_text()
    export = queries[queries.index("export function useExportBundle"):]
    export = export[: export.index("export function useDiscardStaleDrafts")]
    assert "fetchBlob(" in export
    # The server names the file; the console does not guess it.
    assert "link.download = filename" in export
