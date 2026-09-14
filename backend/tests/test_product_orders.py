"""One request, one printed product."""
from __future__ import annotations

from app.services import product_orders as po


ROWS = [
    {"strand": "Numbers", "sub_strand": "Integers", "hours": 12.0},
    {"strand": "Numbers", "sub_strand": "Fractions", "hours": 10.0},
    {"strand": "Numbers", "sub_strand": "Decimals", "hours": 8.0},
    {"strand": "Algebra", "sub_strand": "Linear equations", "hours": 12.0},
    {"strand": "Algebra", "sub_strand": "Inequalities", "hours": 8.0},
    {"strand": "Geometry", "sub_strand": "Angles", "hours": 10.0},
]


def test_a_term_is_the_designs_order_split_by_hours(monkeypatch) -> None:
    monkeypatch.setattr(po, "sub_strands_for", lambda g, s: [dict(r) for r in ROWS])

    one = [r["sub_strand"] for r in po.term_scope("grade-9", "Mathematics", 1)]
    two = [r["sub_strand"] for r in po.term_scope("grade-9", "Mathematics", 2)]
    three = [r["sub_strand"] for r in po.term_scope("grade-9", "Mathematics", 3)]

    assert one == ["Integers", "Fractions"]
    assert two == ["Decimals", "Linear equations"]
    assert three == ["Inequalities", "Angles"]
    assert one + two + three == [r["sub_strand"] for r in ROWS], "every sub-strand lands in one term"


def test_scope_by_kind(monkeypatch) -> None:
    monkeypatch.setattr(po, "sub_strands_for", lambda g, s: [dict(r) for r in ROWS])

    assert [r["sub_strand"] for r in po.scope_for({"grade": "g", "subject": "s", "kind": "topical", "sub_strand": "angles"})] == ["Angles"]
    assert [r["sub_strand"] for r in po.scope_for({"grade": "g", "subject": "s", "kind": "strand", "strand": "Algebra"})] == ["Linear equations", "Inequalities"]
    assert [r["sub_strand"] for r in po.scope_for({"grade": "g", "subject": "s", "sub_strands": ["Decimals", "Angles"]})] == ["Decimals", "Angles"]


def test_an_order_runs_only_what_is_missing_then_freezes(monkeypatch) -> None:
    monkeypatch.setattr(po, "sub_strands_for", lambda g, s: [dict(r) for r in ROWS])
    have_notes = {"Integers"}
    have_items = {"Integers": 25, "Fractions": 3}
    monkeypatch.setattr(po, "_has_notes", lambda g, s, ss: ss in have_notes)
    monkeypatch.setattr(po, "_drawn_figures", lambda g, s, ss: 2 if ss == "Integers" else 0)
    monkeypatch.setattr(po, "_items_in_bank", lambda g, s, ss: have_items.get(ss, 0))
    ran: list[tuple[str, str, int | None]] = []
    frozen: dict = {}

    def run_station(kind, params):
        ran.append((kind, params["sub_strand"], params.get("count")))
        if kind == "notes":
            have_notes.add(params["sub_strand"])
        if kind == "questions":
            have_items[params["sub_strand"]] = have_items.get(params["sub_strand"], 0) + params["count"]
        return {}

    def freeze(params):
        frozen.update(params)
        return {"exam_id": "exam-1", "question_count": 30, "total_marks": 30,
                "render_urls": {"paper": "/p"}}

    out = po.run({"grade": "grade-9", "subject": "Mathematics", "kind": "term", "term": 1, "count": 30},
                 run_station, freeze)

    kinds = [(k, s) for k, s, _ in ran]
    assert ("notes", "Integers") not in kinds and ("notes", "Fractions") in kinds
    assert ("diagram", "Integers") not in kinds and ("diagram", "Fractions") in kinds
    # Twice the share: 30 items over 2 sub-strands wants 30 each in the bank.
    assert next(c for k, s, c in ran if k == "questions" and s == "Integers") == 5
    assert next(c for k, s, c in ran if k == "questions" and s == "Fractions") == 27
    assert kinds.index(("notes", "Fractions")) < kinds.index(("questions", "Fractions")), "guide before items"
    assert frozen["sub_strands"] == ["Integers", "Fractions"] and frozen["kind"] == "term" and frozen["term"] == 1
    assert out["paper"]["exam_id"] == "exam-1" and out["render_urls"] == {"paper": "/p"}
    assert [p["what"] for p in out["progress"]][:2] == ["Scope", "Notes"]


def test_an_order_with_no_scope_says_so(monkeypatch) -> None:
    import pytest

    monkeypatch.setattr(po, "sub_strands_for", lambda g, s: [])
    with pytest.raises(ValueError):
        po.run({"grade": "grade-9", "subject": "Mathematics", "kind": "term", "term": 1}, lambda k, p: {}, lambda p: {})


def test_orders_are_a_queue_kind_a_station_and_a_route() -> None:
    import inspect

    from app.routes import agent, curriculum

    assert "order" in agent.STATIONS
    assert curriculum._BUNDLE_HANDLERS["order"] is curriculum._run_queued_order
    assert "order" not in curriculum._PIPELINE_HANDLERS, "an order is not a pipeline stage"
    assert 'job_queue.register("order", _run_queued_order)' in inspect.getsource(curriculum._register_queue_handlers)
    source = inspect.getsource(curriculum)
    assert '@router.post("/factory/orders")' in source and '@router.get("/factory/orders/scope")' in source
    assert '@router.get("/pack")' in inspect.getsource(agent)


def test_the_pack_carries_a_playbook_the_prompts_and_the_formats() -> None:
    import io
    import zipfile

    from app.services import agent_pack

    z = zipfile.ZipFile(io.BytesIO(agent_pack.build(base_url="https://p.example")))
    names = z.namelist()
    assert "AGENTS.md" in names and "CLAUDE.md" in names and "manifest.json" in names and "formats.json" in names
    assert sum(1 for n in names if n.startswith("prompts/")) > 30
    playbook = z.read("AGENTS.md").decode()
    assert "mid-term 1 assessment" in playbook and 'station: "order"' in playbook
    assert "https://p.example" in playbook
    assert "KENYA JUNIOR SCHOOL EDUCATION ASSESSMENT" in z.read("formats.json").decode()


def test_a_kit_is_ready_to_open_for_each_agent() -> None:
    import io
    import zipfile

    from app.services import agent_pack

    for agent in agent_pack.AGENTS:
        z = zipfile.ZipFile(io.BytesIO(agent_pack.build_kit(agent=agent, base_url="http://p.example", api_key="cbc_live_K")))
        names = z.namelist()
        assert {"AGENTS.md", "CLAUDE.md", "README.md", "cbc/cbc_mcp.py", "cbc/cbc_agent.py", "cbc/.env",
                "install.sh", "manifest.json", "formats.json"} <= set(names), agent
        env = z.read("cbc/.env").decode()
        assert "CBC_API_KEY=cbc_live_K" in env and "CBC_API_URL=http://p.example" in env
        assert f'case "{agent}" in' in z.read("install.sh").decode()
        playbook = z.read("AGENTS.md").decode()
        assert "Start here" in playbook and "Improving what came back" in playbook
        assert "cbc_produce" in playbook
    assert ".mcp.json" in zipfile.ZipFile(io.BytesIO(agent_pack.build_kit(agent="claude", base_url="u", api_key="k"))).namelist()
    assert "run.sh" in zipfile.ZipFile(io.BytesIO(agent_pack.build_kit(agent="ollama", base_url="u", api_key="k"))).namelist()
    assert "cbc/cbc_mcp.py" in zipfile.ZipFile(io.BytesIO(agent_pack.build_kit(agent="antigravity", base_url="u", api_key="k"))).namelist()


def test_the_kit_route_mints_a_key_only_for_admins_and_operators() -> None:
    import inspect

    from app.routes import agent

    source = inspect.getsource(agent.download_pack)
    assert 'if auth.role not in ("admin", "operator")' in source
    assert "_mint_key(auth, label=" in source
    assert "'operator'" in inspect.getsource(agent._mint_key), "a kit key is an operator key, never admin"
