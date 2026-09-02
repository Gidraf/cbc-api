"""Read a curriculum design with a model, and get the same JSON every time.

The regex extractor reads the designs it was written against and returns
nothing for the rest. A Grade 9 Agriculture design came back with zero
sub-strands because its PDF reader flattened the four-column table into
consecutive lines — and an empty design is indistinguishable, in the console,
from one nobody has run.

A model does not care how the columns landed. What it does care about is being
told exactly what to return, and being checked afterwards: the value here is
not the reading, it is the CONTRACT. Every key present every time, every fact
carrying the `page:line` it came from, and every one of those addresses
verified against the document before any of it is believed.

What this does NOT do is decide it knows better than the design. Anything the
summary table names and the detail pages do not yield is reported in
`unreadable` rather than invented, and a citation that does not resolve is
dropped with the fact it was attached to.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("cbc-design-agent")

AGENT = "curriculum-extractor"

# Keys the contract promises. A consumer must never have to ask whether one is
# there, so a missing key is filled rather than tolerated.
_TOP: dict[str, Any] = {
    "subject": "", "subject_code": "", "grade": "", "level": "",
    "essence_statement": "", "general_learning_outcomes": [],
    "naming": {}, "citations": [], "strands": [],
    "unreadable": [], "gaps": [],
}
_SUB: dict[str, Any] = {
    "theme": "", "sub_strand_name": "", "allocated_time": "",
    "slos": [], "learning_experiences": [], "key_inquiry_questions": [],
    "core_competencies": [], "values": [], "pertinent_and_contemporary_issues": [],
    "required_diagrams": [], "experiments": [], "safety_hazards_to_check": [],
    "source_pages": [], "citations": [],
}


@dataclass(slots=True)
class Reading:
    design: dict[str, Any] = field(default_factory=dict)
    citations_checked: int = 0
    citations_resolved: int = 0
    dropped: list[dict[str, Any]] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)

    @property
    def sub_strands(self) -> int:
        return sum(len(s.get("sub_strands") or []) for s in self.design.get("strands") or [])

    @property
    def citation_percentage(self) -> int:
        if not self.citations_checked:
            return 0
        return round(self.citations_resolved / self.citations_checked * 100)

    def to_dict(self) -> dict[str, Any]:
        return {
            "design": self.design,
            "sub_strands": self.sub_strands,
            "citations_checked": self.citations_checked,
            "citations_resolved": self.citations_resolved,
            "citation_percentage": self.citation_percentage,
            "dropped": self.dropped[:40],
            "findings": self.findings,
        }


def _listed(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, "", {}):
        return []
    return [value]


def shape(raw: Any) -> dict[str, Any]:
    """The model's answer, with every promised key present.

    Filling rather than rejecting: a design that came back without `gaps` is
    still a design, and failing the whole extraction over an absent empty list
    throws away a document that took a minute and a half to read.
    """
    out: dict[str, Any] = {}
    source = raw if isinstance(raw, dict) else {}
    for key, default in _TOP.items():
        value = source.get(key, default)
        out[key] = _listed(value) if isinstance(default, list) else (
            value if isinstance(value, type(default)) or default == "" else default
        )
    if not isinstance(out["naming"], dict):
        out["naming"] = {}
    out["naming"].setdefault("design_word", "")
    out["naming"].setdefault("uses_themes", False)

    strands = []
    for strand in _listed(source.get("strands")):
        if not isinstance(strand, dict):
            continue
        subs = []
        for sub in _listed(strand.get("sub_strands")):
            if not isinstance(sub, dict):
                continue
            filled = {k: (_listed(sub.get(k, d)) if isinstance(d, list) else sub.get(k, d))
                      for k, d in _SUB.items()}
            filled["sub_strand_name"] = str(filled["sub_strand_name"] or "").strip()
            if filled["sub_strand_name"]:
                subs.append(filled)
        strands.append({
            "strand_name": str(strand.get("strand_name") or "").strip(),
            "sub_strands": subs,
        })
    out["strands"] = [s for s in strands if s["strand_name"]]
    return out


def verify(design: dict[str, Any], text: str) -> Reading:
    """Drop every citation whose address does not resolve in this document.

    An address that does not resolve is worse than none, because it survives
    inspection: a reviewer clicks it, sees a page, and assumes the fact was
    read off it.
    """
    from . import document_index

    reading = Reading(design=design)
    try:
        pages = document_index.parse_pages(text)
    except Exception as exc:  # noqa: BLE001
        reading.findings.append(f"The document could not be indexed ({exc}); "
                                f"citations were not checked.")
        return reading

    def check(holder: dict[str, Any], where: str) -> None:
        kept = []
        for citation in _listed(holder.get("citations")):
            if not isinstance(citation, dict) or not citation.get("ref"):
                continue
            reading.citations_checked += 1
            if document_index.resolve_reference(pages, str(citation["ref"])):
                reading.citations_resolved += 1
                kept.append(citation)
            else:
                reading.dropped.append({**citation, "where": where})
        holder["citations"] = kept

    check(design, "the design")
    for strand in design.get("strands") or []:
        for sub in strand.get("sub_strands") or []:
            check(sub, f"{strand.get('strand_name')} / {sub.get('sub_strand_name')}")

    if reading.dropped:
        reading.findings.append(
            f"{len(reading.dropped)} citation(s) named an address that is not in "
            f"this document and were dropped."
        )
    return reading


def read(text: str, *, grade: str = "", stage: str = "ingest_extraction") -> Reading:
    """Read one design document into the contract's JSON.

    The prompt lives in Langfuse under `extract/curriculum`, so it is edited
    where every other prompt is edited and versioned the same way.
    """
    from .langfuse_context import langfuse_context_service
    from .llm_client import llm_client
    from .provider_router import provider_router
    from .run_log import step

    if not (text or "").strip():
        raise ValueError("There is no document to read.")

    prompt = langfuse_context_service.get_agent_prompt(AGENT)
    master = langfuse_context_service.get_master_context()
    rendered = (prompt
                .replace("{{ master_context }}", master)
                .replace("{{ raw_text }}", text))

    config = provider_router.resolve(stage)
    step("Reading the design", f"{len(text):,} characters · {config.model}", "ok")

    response = llm_client.generate(
        config,
        [{"role": "system", "content": "You return only valid JSON."},
         {"role": "user", "content": rendered}],
        temperature=0.1,
        top_p=0.9,
    )

    design = shape(response.content)
    if grade and not design.get("grade"):
        design["grade"] = grade

    reading = verify(design, text)
    step(
        "Design read",
        f"{reading.sub_strands} sub-strand(s), "
        f"{reading.citations_resolved} of {reading.citations_checked} citation(s) resolve",
        "ok" if reading.sub_strands and not reading.dropped else "warn",
    )
    return reading
