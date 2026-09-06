"""The prompts and the code, checked against each other on every run.

Two failures have happened here, both silent, both live for months:

  - A prompt names `{{ language_register }}` and no caller binds that name.
    The placeholder reaches the model as literal text, so the prompt looks
    complete in the Langfuse console and tells the agent nothing. Thirteen call
    sites computed `language_block(grade)` — the block that says how the words
    must SOUND for an age — bound it under a name no prompt used, and the
    instruction that stops a Grade 9 guide reading like a nursery rhyme never
    once reached a model.
  - A caller binds `min_visuals` and no prompt asks for it. The console had a
    control for it. Setting it did nothing, for the whole life of the field.

Neither shows up in a test of either half alone, and neither shows up at run
time — one renders a stray placeholder, the other renders nothing. So the two
halves are compared, and the comparison runs here: change a prompt or change a
call site, and whichever half was not updated is named.
"""
from __future__ import annotations

from app.services import prompt_bindings


def test_no_prompt_asks_for_a_variable_nothing_binds() -> None:
    """The hard failure. A placeholder nothing supplies reaches the model as
    the literal text `{{ language_register }}`."""
    report = prompt_bindings.alignment_report()

    assert not report["unsupplied"], report["says"]


# Variables the code binds that no prompt asks for. Every one of these is work
# the code does and throws away.
#
# `reviewer-panel` was the worst of them and is no longer here: it was handed
# the experiments, the questions and the safety guidance it exists to audit,
# and its prompt asked for none of them — so the audit was performed by reading
# whatever of a 60,000-character bundle the model happened to attend to.
#
# Frozen rather than fixed, because removing one means deciding whether the
# prompt should ask for it or the code should stop computing it, and that is a
# judgement about the content. The list may SHRINK freely; anything new fails,
# which is the point.
# Now empty. Every entry has been resolved — each one either became a slot the
# prompt asks for, or a binding the code stopped computing.
KNOWN_DEAD: dict[str, set[str]] = {}


def test_no_new_variable_is_computed_and_thrown_away() -> None:
    """A control that appears to work and does nothing is worse than none."""
    unused = prompt_bindings.unused_bindings()

    new: dict[str, list[str]] = {}
    for agent, names in unused.items():
        unexpected = sorted(set(names) - KNOWN_DEAD.get(agent, set()))
        if unexpected:
            new[agent] = unexpected

    assert not new, (
        "These variables are handed to an agent whose prompt never asks for "
        "them, so setting them does nothing. Either reference them in the "
        f"prompt or stop computing them: {new}")


def test_the_known_dead_list_does_not_go_stale() -> None:
    """A baseline that lists variables which are no longer dead teaches the
    next person to distrust it."""
    unused = prompt_bindings.unused_bindings()

    stale = {agent: sorted(names - set(unused.get(agent, [])))
             for agent, names in KNOWN_DEAD.items()
             if names - set(unused.get(agent, []))}

    assert not stale, f"No longer dead — take them off the list: {stale}"


def test_the_scanner_reads_every_shape_the_code_binds_in() -> None:
    """Four shapes are in use, and reading only the first reported working
    code as broken — which is how a check gets turned off."""
    import inspect

    source = inspect.getsource(prompt_bindings)

    assert "_keys_of(node)" in source, "a dict literal"
    assert "isinstance(node, ast.Tuple)" in source, '("name", value) pairs'
    assert 'getattr(node.func, "attr", "") == "replace"' in source, \
        'template.replace("{{ raw_text }}", text)'
    assert "_string_constants" in source, 'AGENT = "material-generator"'


def test_a_closure_binding_is_credited_to_its_function() -> None:
    """`_scope_chunk_reader` fetches the template and renders it inside a
    nested closure. Reading only the fetching call reported it as binding
    nothing at all."""
    bound = prompt_bindings.all_bindings()

    assert "level_register" in bound.get("grade-scope-extractor", set())
    assert "teacher_band" in bound.get("profile-generator", set())


def test_the_report_says_what_to_do_about_it() -> None:
    says = prompt_bindings.alignment_report()["says"]

    assert says
    assert ("agree" in says or "does nothing" in says or "renders empty" in says
            or "called by nothing" in says)


# Prompts that are seeded and called by nothing. `content-repair` came off
# this list when the question path started repairing what the structure gate
# blocked instead of discarding it. The two left need a decision about WHERE
# they sit in the pipeline, which is a design question rather than a defect.
# Empty. Both were wired into the fit check: `slo-aligner` measures which
# outcomes the content actually serves, and `layer-reviewer` whether it is
# pitched for the learner it names and the teacher who reads it.
KNOWN_UNCALLED: set[str] = set()


def test_no_new_prompt_is_seeded_and_left_uncalled() -> None:
    """A prompt nothing calls is a prompt nobody maintains, and it reads as
    working machinery to the next person."""
    never = set(prompt_bindings.alignment_report()["never_called"])

    assert not (never - KNOWN_UNCALLED), (
        f"seeded and called by nothing: {sorted(never - KNOWN_UNCALLED)}")
    assert not (KNOWN_UNCALLED - never), (
        f"now called — take them off the list: {sorted(KNOWN_UNCALLED - never)}")


def test_the_reviewer_panel_is_shown_what_it_audits() -> None:
    """It was handed the questions, the practicals and the safety guidance and
    asked for none of them, so the safety audit was carried out on whichever
    part of a 60,000-character bundle the model happened to read."""
    from app.services.langfuse_seed import SEED_AGENT_PROMPTS

    prompt = SEED_AGENT_PROMPTS["reviewer-panel"]

    for slot in ("{{ questions }}", "{{ experiments }}",
                 "{{ safety_guidelines }}", "{{ safety_hazard_criteria }}",
                 "{{ notes_title }}"):
        assert slot in prompt, slot

    # And each sits under the protocol that uses it, not in a heap at the top.
    audit = prompt.split("3. CRITICAL SAFETY & HAZARD AUDIT")[1]
    assert "{{ experiments }}" in audit
    assert "{{ safety_hazard_criteria }}" in audit
    diagrams = prompt.split("1. VISUAL-SEMANTIC ALIGNMENT")[1].split("2. AUTHENTIC")[0]
    assert "{{ questions }}" in diagrams


def test_the_reviewer_is_not_sent_the_same_content_twice() -> None:
    """The questions and practicals are named under their own protocols now.
    Leaving them in the bundle as well would pay for them twice on every
    review."""
    import inspect

    from app.services import pipeline

    source = inspect.getsource(pipeline)
    bundle = source.split('"content_to_review": json.dumps(')[1][:600]

    assert 'if k not in ("experiments", "safety_guidelines")' in bundle
    assert '"questions": questions_output,' not in bundle


def test_a_reviewer_is_never_handed_more_than_it_can_hold() -> None:
    """Handed three hundred questions it reads the first few dozen and returns
    a verdict phrased as though it read them all. Truncating silently does the
    same thing while looking complete."""
    from app.services.pipeline import _capped

    short = [{"q": i} for i in range(5)]
    assert _capped(short, "questions") is short

    long = [{"q": i} for i in range(200)]
    out = _capped(long, "questions", limit=60)
    assert len(out) == 61
    assert "140 further questions were not shown" in out[-1]["_note"]
    assert "covers the 60 above only" in out[-1]["_note"]


def test_capping_leaves_anything_that_is_not_a_list_alone() -> None:
    from app.services.pipeline import _capped

    assert _capped(None, "questions") is None
    assert _capped({"a": 1}, "questions") == {"a": 1}


def test_the_approvers_are_shown_the_bundle_they_approve() -> None:
    """Both prompts said "evaluate the complete CBC educational bundle" and
    neither was ever given one. The deliberation ran on a title, two counts, a
    status and a hazard flag — five scalar facts — and returned
    `ready_for_human_review: true`. The last gate before a person signs had
    never seen a word of the content."""
    from app.services.langfuse_seed import SEED_AGENT_PROMPTS

    for agent in ("approver-agent1", "approver-agent2"):
        prompt = SEED_AGENT_PROMPTS[agent]
        assert "{{ content_to_review }}" in prompt, agent
        assert "{{ reviewer_findings }}" in prompt, agent
        for slot in ("{{ notes_title }}", "{{ level }}", "{{ questions_count }}",
                     "{{ experiments_count }}", "{{ reviewer_status }}",
                     "{{ has_hazards }}"):
            assert slot in prompt, f"{agent} {slot}"


def test_an_approver_may_not_simply_restate_the_reviewer() -> None:
    """Given the counts and the reviewer's verdict, the cheapest passing answer
    is to repeat them back. The prompt has to close that off."""
    from app.services.langfuse_seed import SEED_AGENT_PROMPTS

    # Line wrapping is not the instruction; a rule spanning two lines is one
    # rule, and an assertion that breaks when a sentence rewraps tests the
    # margin rather than the rule.
    prompt = " ".join(SEED_AGENT_PROMPTS["approver-agent1"].split())

    assert "without a finding of your own from the bundle is not an audit" in prompt
    assert "the signature that follows yours is a person's" in prompt


def test_the_second_auditor_is_told_agreement_is_not_free() -> None:
    from app.services.langfuse_seed import SEED_AGENT_PROMPTS

    prompt = " ".join(SEED_AGENT_PROMPTS["approver-agent2"].split())

    assert "agreement is a finding only where the content supports it" in prompt
    assert "Check it AGAINST the bundle above" in prompt


def test_the_second_auditor_actually_sees_the_first_ones_verdict() -> None:
    """Both directives went into one system message and one model answered as
    both auditors, so "Auditor 2 cross-examines Auditor 1" was one model
    writing agreement with itself."""
    import inspect

    from app.services import pipeline

    source = inspect.getsource(pipeline.PipelineService._run_multi_agent_approver)

    assert source.count("llm_client.generate(") == 2, "two opinions, two calls"
    assert "AUDITOR 1 RETURNED THIS" in source
    assert "first_text" in source
    # And the reviewer's actual words, not only its verdict.
    assert "reviewer_findings" in source


def test_the_two_calls_are_reported_as_one_stage_cost() -> None:
    """The stage records one cost; hiding the second call's spend would make
    the board understate what a run costs."""
    import inspect

    from app.services import pipeline

    source = inspect.getsource(pipeline.PipelineService._run_multi_agent_approver)

    assert 'for attribute in ("usage", "cost_usd", "total_cost_usd")' in source


def test_the_activity_station_is_shown_what_the_design_asks_for() -> None:
    """`target_experiments` is the curriculum design's OWN list of practicals
    for this sub-strand, and `safety_hazard_criteria` its hazard list. Neither
    reached the prompt, so the station invented practicals the design never
    asked for and wrote safety protocols from a general idea of what is
    dangerous."""
    from app.services.langfuse_seed import SEED_AGENT_PROMPTS

    prompt = " ".join(SEED_AGENT_PROMPTS["activity-generator"].split())

    assert "{{ target_experiments }}" in prompt
    assert "{{ safety_hazard_criteria }}" in prompt
    assert "{{ notes_title }}" in prompt
    assert "Do NOT invent a practical the design does not ask for" in prompt
    # Every named hazard has to reach the teacher's own warning list.
    assert "MUST appear in `safety_protocols.hazard_warnings`" in prompt


def test_the_diagram_station_knows_which_figure_it_is_drawing() -> None:
    """It is called once per required diagram, and was told neither which one
    of them this was nor how many there were — so two calls could cover the
    same concept and leave a gap where a third should have been."""
    from app.services.langfuse_seed import SEED_AGENT_PROMPTS

    prompt = " ".join(SEED_AGENT_PROMPTS["diagram-generator"].split())

    assert "Figure {{ diagram_index }} of {{ diagram_total }}" in prompt
    assert "{{ diagrams_required }}" in prompt
    assert "you are drawing that ONE figure" in prompt
    # And the routes plan them all at once, which the same prompt has to serve
    # without claiming to be figure 1 of 5.
    assert "figure number above is 0 you are PLANNING all" in prompt


def test_the_diagram_prompt_asks_for_the_size_the_book_prints() -> None:
    """It hardcoded `viewBox='0 0 800 500'` for a figure printed 85mm wide in a
    two-column book. That is where the unreadable drawings began: labels sized
    for an 800-unit canvas resolve to about 2mm on the page."""
    from app.services.langfuse_seed import SEED_AGENT_PROMPTS

    prompt = " ".join(SEED_AGENT_PROMPTS["diagram-generator"].split())

    assert "0 0 800 500" not in prompt
    assert "viewBox='0 0 340 200'" in prompt
    assert "85mm wide" in prompt
    assert "No text below font-size 13" in prompt
    # And the same rule the drawing station's own brief enforces.
    assert "no label may lie across a shape or another label" in prompt
