"""The strand generator's own findings must survive to where they are used.

Its schema asks for `strand_id`, `source_pages` and `sub_strand_names`, and the
design's summary table lists every sub-strand explicitly — CRE's twelve are on
page 202. Two places dropped all three: the copy serialiser printed only the
name and description, and the save endpoint stored `sub_strands: []` while
discarding the names the generator had just read.

So a copy made for verification could not be verified against anything, and the
sub-strand generator had to rediscover from scratch what had already been
extracted.
"""
from __future__ import annotations

import json
import re


def _clean_block() -> str:
    source = open("app/routes/curriculum.py").read()
    block = source[source.index("def factory_save_strands"):]
    return block[: block.index("\n@router.")]


def test_the_sub_strand_names_the_design_lists_are_kept() -> None:
    assert '"sub_strand_names"' in _clean_block()


def test_the_pages_the_strand_was_read_from_are_kept() -> None:
    """Without them a strand's description cannot be checked against the design."""
    assert '"source_pages"' in _clean_block()


def test_the_structure_read_returns_them_too() -> None:
    source = open("app/routes/curriculum.py").read()
    block = source[source.index("def factory_read_structure"):]
    block = block[: block.index("\n@router.")]

    assert '"sub_strand_names": entry.get("sub_strand_names")' in block
    assert '"source_pages": entry.get("source_pages")' in block


def test_the_copy_carries_what_the_generator_found() -> None:
    serializer = open("../frontend-web/src/lib/serialize.ts").read()
    block = serializer[serializer.index("export function strandToText"):]
    block = block[: block.index("\nexport function")]

    assert "strand.strand_id" in block
    assert "strand.source_pages" in block
    assert "strand.sub_strand_names" in block
    assert "Sub-strands the design names" in block


def test_the_strand_prompt_still_asks_for_all_three() -> None:
    """If the schema stops asking, keeping them downstream achieves nothing."""
    from app.services.langfuse_seed import SEED_AGENT_PROMPTS

    schema = SEED_AGENT_PROMPTS["strand-generator"]

    assert '"strand_id"' in schema
    assert '"sub_strand_names"' in schema
    assert '"source_pages"' in schema
