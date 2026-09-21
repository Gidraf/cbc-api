"""The unattended runner: every grade, every subject, every term, PDFs saved,
a ledger that lets a stopped sweep resume — against a fake platform and a
fake model, in-process."""
from __future__ import annotations

import argparse
import json
import os

import pytest

from app.agent_clients import cbc_agent


class _Platform:
    """Answers the handful of routes the sweep uses."""

    def __init__(self, subjects_by_grade, fail=()):
        self.subjects = subjects_by_grade
        self.fail = set(fail)
        self.started: list[dict] = []
        self.completed = 0

    def __call__(self, method, path, body=None):
        if path.endswith("/subjects"):
            grade = path.split("/")[-2]
            return {"subjects": [{"name": n, "ingested": True} for n in self.subjects.get(grade, [])]
                    + [{"name": "Astrophysics", "ingested": False}]}
        if path == "/api/v1/agent/tasks":
            self.started.append(body)
            key = (body["grade"], body["subject"])
            if key in self.fail:
                raise SystemExit(f"POST /api/v1/agent/tasks → 400: No sub-strands found for {body['subject']}")
            # One prompt, then done.
            return {"task_id": f"t{len(self.started)}", "status": "awaiting",
                    "step": {"number": 1, "stage": "questions", "expect": "json",
                             "messages": [{"role": "user", "content": "write"}]}}
        if path.endswith("/complete"):
            self.completed += 1
            tid = path.split("/")[-2]
            n = int(tid[1:])
            body_ = self.started[n - 1]
            return {"task_id": tid, "status": "done", "steps_completed": 1,
                    "result": {"paper": {"exam_id": f"exam-{n}", "question_count": 30},
                               "render_urls": {"booklet_pdf": f"http://x/{n}/print.pdf?token=a&with_scheme=true",
                                               "answer_sheet": f"http://x/{n}/print?token=a&answer_sheet=true"},
                               "progress": [{"what": "Paper", "detail": f"{body_['grade']} {body_['subject']}"}]}}
        raise AssertionError(path)


@pytest.fixture
def fakes(monkeypatch, tmp_path):
    platform = _Platform({"grade-6": ["Mathematics", "English"], "grade-7": ["Mathematics"]},
                         fail=[("grade-7", "Mathematics")])
    monkeypatch.setattr(cbc_agent, "_platform", platform)
    monkeypatch.setattr(cbc_agent, "_model", lambda *a, **k: '{"questions": []}')
    fetched: list[str] = []

    def fetch(url, path):
        fetched.append(url)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(b"%PDF-1.4 fake")
        return 13
    monkeypatch.setattr(cbc_agent, "_fetch", fetch)
    return platform, fetched, tmp_path


def _args(tmp_path, **over):
    base = dict(from_grade="grade-6", to_grade="grade-7", grades=None, subjects=None, terms=[1, 2],
                order="given", count=30, instructions="", download=str(tmp_path / "papers"), redo=False,
                model="qwen2.5:32b", llm_url="http://localhost:11434/v1")
    base.update(over)
    return argparse.Namespace(**base)


def test_the_sweep_orders_every_ingested_subject_per_term_and_saves_the_pdfs(fakes, capsys):
    platform, fetched, tmp_path = fakes
    cbc_agent.sweep(_args(tmp_path))

    # 2 subjects × 2 terms in grade 6, plus grade 7 Mathematics × 2 (refused).
    assert len(platform.started) == 6
    assert {(b["grade"], b["subject"], b["kind"], b["term"]) for b in platform.started} == {
        ("grade-6", "Mathematics", "term", 1), ("grade-6", "Mathematics", "term", 2),
        ("grade-6", "English", "term", 1), ("grade-6", "English", "term", 2),
        ("grade-7", "Mathematics", "term", 1), ("grade-7", "Mathematics", "term", 2)}
    assert not any(b["subject"] == "Astrophysics" for b in platform.started), "not ingested → not ordered"

    papers = sorted(os.listdir(tmp_path / "papers"))
    assert sum(p.endswith("-booklet.pdf") for p in papers) == 4
    assert sum(p.endswith("-answer-sheet.html") for p in papers) == 4
    assert "grade-6-mathematics-term1-exam-1-booklet.pdf" in papers

    ledger = json.load(open(tmp_path / "papers" / "sweep-ledger.json"))
    assert ledger["grade-6|Mathematics|term1"]["status"] == "done"
    assert ledger["grade-6|Mathematics|term1"]["exam_id"] == "exam-1"
    assert ledger["grade-7|Mathematics|term1"]["status"] == "refused"
    assert "No sub-strands" in ledger["grade-7|Mathematics|term1"]["error"]
    out = capsys.readouterr().out
    assert "4 paper(s) saved, 2 failed, 0 already done" in out


def test_a_second_sweep_skips_what_is_done_and_retries_what_failed(fakes, capsys):
    platform, fetched, tmp_path = fakes
    cbc_agent.sweep(_args(tmp_path))
    started_before = len(platform.started)

    platform.fail.clear()          # the sub-strands arrived in the meantime
    cbc_agent.sweep(_args(tmp_path))
    assert len(platform.started) - started_before == 2, "only the two refused papers are retried"
    assert "2 paper(s) saved, 0 failed, 4 already done" in capsys.readouterr().out


def test_run_passes_kind_and_term_through_and_downloads_when_asked(fakes):
    platform, fetched, tmp_path = fakes
    args = argparse.Namespace(station="order", grade="grade-6", subject="Mathematics", strand="", sub_strand="",
                              count=30, instructions="", model="m", llm_url="u", kind="term", term=3,
                              download=str(tmp_path / "out"))
    task = cbc_agent.run(args)
    assert platform.started[-1]["kind"] == "term" and platform.started[-1]["term"] == 3
    assert task["status"] == "done"
    assert any(f.endswith("-booklet.pdf") for f in os.listdir(tmp_path / "out"))


def test_the_pdf_falls_back_to_html_when_the_pdf_service_is_down(fakes, capsys):
    platform, fetched, tmp_path = fakes

    def fetch(url, path):
        if url.endswith("print.pdf?token=a&with_scheme=true"):
            raise RuntimeError("PDF service unavailable")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(b"<html>")
        return 6
    monkeypatch_fetch = fetch
    cbc_agent._fetch = monkeypatch_fetch  # the fakes fixture restores the module attribute
    result = {"paper": {"exam_id": "exam-9"},
              "render_urls": {"booklet_pdf": "http://x/9/print.pdf?token=a&with_scheme=true",
                              "booklet": "http://x/9/print?token=a&with_scheme=true"}}
    saved = cbc_agent.download_paper(result, str(tmp_path / "p"), "g")
    assert [os.path.basename(s) for s in saved] == ["g-exam-9-booklet.html"]


def test_middle_out_starts_in_the_middle_and_widens_a_step_each_way():
    grades = [f"grade-{n}" for n in range(6, 13)]
    assert cbc_agent.middle_out(grades) == ["grade-9", "grade-10", "grade-8", "grade-11", "grade-7", "grade-12", "grade-6"]
    assert cbc_agent.middle_out(["grade-7", "grade-8"]) == ["grade-7", "grade-8"]


def test_a_grade_finishes_before_the_next_and_a_term_before_the_next_term(fakes):
    platform, fetched, tmp_path = fakes
    platform.fail.clear()
    cbc_agent.sweep(_args(tmp_path, from_grade="grade-6", to_grade="grade-7", terms=[3, 1]))
    order = [(b["grade"], b["term"], b["subject"]) for b in platform.started]
    assert order == [("grade-6", 3, "Mathematics"), ("grade-6", 3, "English"),
                     ("grade-6", 1, "Mathematics"), ("grade-6", 1, "English"),
                     ("grade-7", 3, "Mathematics"), ("grade-7", 1, "Mathematics")]


class _Resp(__import__("io").BytesIO):
    headers = {}
    status = 200
    def __enter__(self): return self
    def __exit__(self, *a): return False


def test_a_thinking_models_reasoning_is_stripped_from_the_answer(monkeypatch):
    import urllib.request

    monkeypatch.setattr(cbc_agent, "_is_ollama", lambda url: False)   # the OpenAI-compatible path
    body = {"choices": [{"message": {"content": "<think>\nlet me see\n</think>\n{\"questions\": []}"}}]}
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=0: _Resp(json.dumps(body).encode()))
    out = cbc_agent._model("http://localhost:11434/v1", "qwen3:14b", [{"role": "user", "content": "x"}],
                           expect="json", temperature=0.3)
    assert out == '{"questions": []}'


def test_ollama_gets_its_native_api_with_the_context_window_set(monkeypatch):
    """Over /v1 the window cannot be set and Ollama's 4,096 default cuts the
    platform's prompts silently; the native call carries num_ctx."""
    import urllib.request

    seen = {}

    def urlopen(req, timeout=0):
        seen["url"] = req.full_url
        seen["body"] = json.loads(req.data.decode())
        return _Resp(json.dumps({"message": {"content": "<think>hm</think>{\"ok\": 1}"}}).encode())
    monkeypatch.setattr(cbc_agent, "_is_ollama", lambda url: True)
    monkeypatch.setattr(cbc_agent, "NUM_CTX", 16384)
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    out = cbc_agent._model("https://ollama.gidraf.dev/v1", "qwen3:14b", [{"role": "user", "content": "x"}],
                           expect="json", temperature=0.2)
    assert out == '{"ok": 1}'
    assert seen["url"] == "https://ollama.gidraf.dev/api/chat"
    assert seen["body"]["options"] == {"temperature": 0.2, "num_ctx": 16384} and seen["body"]["format"] == "json"


def test_a_prompt_wider_than_ollamas_window_is_warned_about_once(capsys, monkeypatch):
    monkeypatch.setattr(cbc_agent, "_is_ollama", lambda url: False)   # only the /v1 path has the trap
    monkeypatch.setattr(cbc_agent, "_context_warned", False)
    monkeypatch.delenv("OLLAMA_CONTEXT_LENGTH", raising=False)
    cbc_agent._warn_if_prompt_exceeds_context(40_000, "http://localhost:11434/v1")
    cbc_agent._warn_if_prompt_exceeds_context(40_000, "http://localhost:11434/v1")
    out = capsys.readouterr().out
    assert out.count("WARNING") == 1 and "OLLAMA_CONTEXT_LENGTH=16384" in out

    monkeypatch.setattr(cbc_agent, "_context_warned", False)
    monkeypatch.setenv("OLLAMA_CONTEXT_LENGTH", "16384")
    cbc_agent._warn_if_prompt_exceeds_context(40_000, "http://localhost:11434/v1")
    assert "WARNING" not in capsys.readouterr().out, "a window that fits is not warned about"

    monkeypatch.setattr(cbc_agent, "_context_warned", False)
    cbc_agent._warn_if_prompt_exceeds_context(40_000, "https://api.deepseek.com/v1")
    assert "WARNING" not in capsys.readouterr().out, "only Ollama has the small default"
