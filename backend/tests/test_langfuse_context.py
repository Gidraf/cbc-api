from __future__ import annotations

from app.services.langfuse_context import langfuse_context_service


def test_master_context_retrieval():
    master = langfuse_context_service.get_master_context()
    assert "Basic Education Curriculum Framework" in master
    assert "National Goals of Education" in master
    assert "Core Competencies" in master
    assert "Criterion-Referenced" in master


def test_context_assembly_structure():
    compiled = langfuse_context_service.assemble_agent_context(
        agent_name="note-generator",
        grade_slug="grade-7",
        subject="Integrated Science",
        template_vars={"strand": "Matter", "sub_strand": "Classification of Matter", "slo_id": "MS-G7-ISCI-MAT-CLM-01"},
    )
    assert compiled.prompt_name == "note-generator"
    assert len(compiled.prompt_hash) == 64
    assert len(compiled.messages) == 3
    assert compiled.messages[0]["role"] == "system"
    assert compiled.messages[1]["role"] == "system"
    assert compiled.messages[2]["role"] == "user"
    assert "Integrated Science" in compiled.messages[1]["content"]
