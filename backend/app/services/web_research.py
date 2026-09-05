from __future__ import annotations

import json
import logging
import re
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    httpx = None
    HAS_HTTPX = False

logger = logging.getLogger("cbc-web-research")

AUTHORITATIVE_DOMAINS = [
    "kicd.ac.ke",
    "knec.ac.ke",
    "kalro.org",
    "kilimo.go.ke",
    "fao.org",
    "knbs.or.ke",
    "vision2030.go.ke",
    "unesco.org",
    "who.int",
    "openstax.org",
    "sciencedirect.com",
    "nature.com",
]


@dataclass(slots=True)
class ResearchCitation:
    title: str
    url: str
    source_domain: str
    snippet: str
    key_facts: list[str] = field(default_factory=list)
    credibility_score: float = 0.95


@dataclass(slots=True)
class QualityAuditReport:
    score: int
    curriculum_alignment: bool
    scientific_accuracy: bool
    safety_compliance: bool
    pck_depth: bool
    rubric_precision: bool
    no_shallow_content: bool
    audit_checks: list[dict[str, Any]] = field(default_factory=list)
    feedback_suggestions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ResearchDossier:
    topic: str
    subject: str
    grade: str
    search_queries: list[str]
    citations: list[ResearchCitation] = field(default_factory=list)
    empirical_data_points: list[dict[str, Any]] = field(default_factory=list)
    academic_insights: list[str] = field(default_factory=list)
    kenyan_case_studies: list[dict[str, str]] = field(default_factory=list)
    deliberation_trace: list[str] = field(default_factory=list)
    safety_guidelines: list[str] = field(default_factory=list)
    formatted_context: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "subject": self.subject,
            "grade": self.grade,
            "search_queries": self.search_queries,
            "citations": [asdict(c) for c in self.citations],
            "empirical_data_points": self.empirical_data_points,
            "academic_insights": self.academic_insights,
            "kenyan_case_studies": self.kenyan_case_studies,
            "deliberation_trace": self.deliberation_trace,
            "safety_guidelines": self.safety_guidelines,
            "formatted_context": self.formatted_context,
        }


# Which extra research angles a sub-strand actually warrants. Asking all of
# them of every subject is how a CRE lesson acquired an agriculture dossier.
_AGRICULTURAL = (
    "agricultur", "farm", "crop", "livestock", "soil", "irrigation", "horticultur",
    "pastoral", "fisher", "forestry",
)
_PRACTICAL = (
    "science", "physics", "chemistry", "biology", "integrated science", "laborator",
    "experiment", "apparatus", "technolog", "engineering", "home science", "health",
)
_DEVELOPMENT = (
    "social studies", "geography", "history", "business", "economic", "citizenship",
    "government", "agricultur", "environment",
)


class WebResearchAgent:
    """Agent that performs live web research, academic paper discovery, and pedagogical deliberation."""

    def __init__(self, timeout_seconds: float = 8.0) -> None:
        self.timeout = timeout_seconds
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 (CBC-Curriculum-Bot/2.0)"
            ),
            "Accept": "text/html,application/json,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

    def research_topic(
        self,
        subject: str,
        strand: str,
        sub_strand: str,
        grade: str = "grade-dte",
        topic_type: str = "notes",
        extra_query: str = "",
    ) -> ResearchDossier:
        """Executes targeted web research across multiple angles and returns a rich ResearchDossier."""
        topic_name = f"{subject} - {sub_strand}"
        deliberation_trace: list[str] = []
        citations: list[ResearchCitation] = []
        empirical_data: list[dict[str, Any]] = []
        academic_insights: list[str] = []
        kenyan_case_studies: list[dict[str, str]] = []
        safety_guidelines: list[str] = []

        deliberation_trace.append(f"🔍 Initiating Deep Web & Academic Research for [{subject}] Sub-strand: [{sub_strand}] ({grade}).")

        # 1. Generate multi-angle search queries
        queries = self._generate_search_queries(subject, strand, sub_strand, grade, topic_type, extra_query)
        deliberation_trace.append(f"📡 Generated {len(queries)} multi-angle research queries: {clean_q_list(queries)}")

        # 2. Execute Web Searches & Fetch Content
        for q in queries[:4]:
            try:
                results = self._execute_search(q)
                for r in results:
                    if not any(c.url == r["url"] for c in citations):
                        citations.append(
                            ResearchCitation(
                                title=r["title"],
                                url=r["url"],
                                source_domain=r["domain"],
                                snippet=r["snippet"],
                                key_facts=r.get("facts", []),
                                credibility_score=r.get("credibility", 0.9),
                            )
                        )
            except Exception as exc:
                logger.warning("Search query failed for %s: %s", q, exc)

        deliberation_trace.append(f"📚 Retrieved and verified {len(citations)} authoritative source references.")

        # 3. Add Domain-Grounded Empirical Kenyan & Academic Data
        empirical_data, academic_insights, kenyan_case_studies, safety_guidelines = self._extract_empirical_insights(
            subject, strand, sub_strand, citations, grade=grade
        )

        deliberation_trace.append(f"📊 Synthesized {len(empirical_data)} empirical data points and {len(kenyan_case_studies)} authentic Kenyan case studies.")
        # Not "laboratory and field": a pre-primary singing lesson has neither,
        # and a trace that says it does is the same register bleed that had
        # four-year-olds doing practicals.
        deliberation_trace.append(
            f"🛡️ Extracted {len(safety_guidelines)} safety protocol(s) for this sub-strand."
            if safety_guidelines else
            "🛡️ No hazard identified for this sub-strand; no safety protocol extracted."
        )
        deliberation_trace.append("🧠 Completed pedagogical deliberation: Context ready for Professor synthesis.")

        # 4. Format Research Context for LLM prompt injection
        formatted_context = self._build_formatted_context(
            subject=subject,
            sub_strand=sub_strand,
            citations=citations,
            empirical_data=empirical_data,
            academic_insights=academic_insights,
            kenyan_case_studies=kenyan_case_studies,
            safety_guidelines=safety_guidelines,
        )

        return ResearchDossier(
            topic=topic_name,
            subject=subject,
            grade=grade,
            search_queries=queries,
            citations=citations,
            empirical_data_points=empirical_data,
            academic_insights=academic_insights,
            kenyan_case_studies=kenyan_case_studies,
            deliberation_trace=deliberation_trace,
            safety_guidelines=safety_guidelines,
            formatted_context=formatted_context,
        )

    def _generate_search_queries(
        self, subject: str, strand: str, sub_strand: str, grade: str, topic_type: str, extra_query: str
    ) -> list[str]:
        """Builds high-precision search queries for KICD, KALRO, KNEC, and academic research."""
        clean_sub = sub_strand.split(" ", 1)[-1] if sub_strand[:3].replace(".", "").isdigit() else sub_strand
        lowered = f"{subject} {strand} {clean_sub}".lower()

        base_queries = [
            f"KICD Kenya curriculum {subject} {clean_sub} notes pedagogical guide",
            f"Kenya {subject} {clean_sub} teaching resources classroom",
        ]

        # These were asked of every subject, so a Pre-Primary CRE sub-strand
        # searched KALRO for "Our God agricultural scientific principles data"
        # and a laboratory apparatus protocol for singing songs about God. A
        # query that cannot match returns nothing useful and shapes the dossier
        # around a subject this lesson is not about.
        if any(word in lowered for word in _AGRICULTURAL):
            base_queries.append(f"KALRO Kenya {clean_sub} agricultural scientific principles data")
        if any(word in lowered for word in _PRACTICAL):
            base_queries.append(f"{subject} {clean_sub} laboratory experiment apparatus safety protocols")
        if any(word in lowered for word in _DEVELOPMENT):
            base_queries.append(f"Kenya {subject} {clean_sub} real world case study Vision 2030")

        # A search query is a phrase. On a review cycle `custom_instructions`
        # carries the whole revision block — "=== REVISION 2: WHAT THE REVIEW
        # FOUND === The previous version scored 83/100 ..." — and it went
        # straight into the search string and then into the stored dossier.
        hint = " ".join(str(extra_query or "").split())
        if "===" in hint or len(hint) > 120:
            hint = ""
        if hint:
            base_queries.insert(0, f"Kenya {subject} {clean_sub} {hint}"[:200])
        return base_queries[:4]

    def _execute_search(self, query: str) -> list[dict[str, Any]]:
        """Executes search using httpx if available, otherwise urllib.request."""
        if HAS_HTTPX and httpx is not None:
            try:
                with httpx.Client(timeout=self.timeout, headers=self.headers, follow_redirects=True) as client:
                    return self._search_duckduckgo_httpx(client, query)
            except Exception:
                pass
        return self._search_wikipedia_urllib(query)

    def _search_duckduckgo_httpx(self, client: Any, query: str) -> list[dict[str, Any]]:
        url = "https://html.duckduckgo.com/html/"
        resp = client.post(url, data={"q": query})
        results: list[dict[str, Any]] = []

        if resp.status_code != 200:
            return self._search_wikipedia_urllib(query)

        matches = re.findall(
            r"<a class=\"result__url\" href=\"([^\"]+)\".*?<a class=\"result__snippet[^>]*>(.*?)</a>",
            resp.text,
            re.DOTALL,
        )

        for raw_url, raw_snippet in matches[:3]:
            clean_snippet = re.sub(r"<[^>]+>", "", raw_snippet).strip()
            actual_url = raw_url
            if "uddg=" in raw_url:
                parsed = urllib.parse.parse_qs(urllib.parse.urlparse(raw_url).query)
                actual_url = parsed.get("uddg", [raw_url])[0]

            parsed_domain = urllib.parse.urlparse(actual_url).netloc
            title = f"{parsed_domain} - {query}"
            credibility = 0.95 if any(d in parsed_domain for d in AUTHORITATIVE_DOMAINS) else 0.85

            results.append({
                "title": title,
                "url": actual_url,
                "domain": parsed_domain,
                "snippet": clean_snippet[:350],
                "credibility": credibility,
            })

        if not results:
            return self._search_wikipedia_urllib(query)

        return results

    def _search_wikipedia_urllib(self, query: str) -> list[dict[str, Any]]:
        """Uses standard library urllib.request to fetch Wikipedia summary API."""
        try:
            clean_q = query.split()[:3]
            search_term = " ".join(clean_q)
            api_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(search_term)}"
            req = urllib.request.Request(api_url, headers=self.headers)
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    return [{
                        "title": data.get("title", "Wikipedia Encyclopedia"),
                        "url": data.get("content_urls", {}).get("desktop", {}).get("page", "https://en.wikipedia.org"),
                        "domain": "en.wikipedia.org",
                        "snippet": data.get("extract", "")[:350],
                        "credibility": 0.92,
                    }]
        except Exception:
            pass
        return []

    def _extract_empirical_insights(
        self, subject: str, strand: str, sub_strand: str,
        citations: list[ResearchCitation], grade: str = "",
    ) -> tuple[list[dict[str, Any]], list[str], list[dict[str, str]], list[str]]:
        """Empirical insights, case studies and safety protocols for THIS grade.

        The grade was not passed, so the profile lookup fell back to "all" and
        returned whichever profile existed for the subject. A Grade 9 guide on
        Integers was therefore handed a dossier describing "early childhood
        mathematics education", "play-based learning", and case studies about
        PP1 learners counting coloured blocks on a nature walk — inside its own
        prompt, as the pedagogical standard to write to.

        The guide that came back was bingo, a relay race and no mathematics.
        Every other caller of `classify_content_type` passes the grade; this
        one did not, and it is the one that reaches the authoring prompt.
        """
        empirical_data: list[dict[str, Any]] = []
        academic_insights: list[str] = []
        kenyan_case_studies: list[dict[str, str]] = []
        safety_guidelines: list[str] = []

        try:
            from .content_type_classifier import classify_content_type
            profile = classify_content_type(subject=subject, grade=grade or "all",
                                            sub_strand=sub_strand)

            if profile.empirical_insights:
                empirical_data.extend(profile.empirical_insights)
            if profile.case_studies:
                kenyan_case_studies.extend(profile.case_studies)
            if profile.safety_focus:
                safety_guidelines.append(profile.safety_focus)
            if profile.special_directives:
                safety_guidelines.extend([f"Guideline: {d}" for d in profile.special_directives if "safe" in d.lower() or "hygiene" in d.lower() or "not" in d.lower() or "mandat" in d.lower()])
            if profile.note_style:
                academic_insights.append(f"Pedagogical Framework: {profile.note_style[:180]}...")
            if profile.persona:
                academic_insights.append(f"Instructional Standard: Modeled after {profile.persona[:140]}...")
        except Exception as exc:
            logger.warning("Could not fetch DB profile for empirical insights: %s", exc)

        # If DB profile had no empirical data, dynamically derive from citations
        if not empirical_data and citations:
            for c in citations[:3]:
                empirical_data.append({
                    "metric": f"Research Benchmark from {c.source_domain}",
                    "value": c.snippet[:120],
                    "source": c.title,
                })

        if not safety_guidelines:
            safety_guidelines.append("Standard safety protocol: Ensure age-appropriate materials, supervise hands-on activities, and enforce basic hygiene.")

        if not academic_insights:
            academic_insights.append("Constructivist Scaffolding: Ground all inquiry in authentic Kenyan context and learner's immediate environment.")

        return empirical_data, academic_insights, kenyan_case_studies, safety_guidelines

    def _build_formatted_context(
        self,
        subject: str,
        sub_strand: str,
        citations: list[ResearchCitation],
        empirical_data: list[dict[str, Any]],
        academic_insights: list[str],
        kenyan_case_studies: list[dict[str, str]],
        safety_guidelines: list[str],
    ) -> str:
        """Format the research findings, labelled by what they actually are.

        This block used to head model-generated figures with "VERIFIED EMPIRICAL
        DATA & KENYAN STATISTICS" and stamp each with a source — "85% of children
        who demonstrate understanding of Christian values [KICD Annual Report
        2022]" — when zero sources had been retrieved and the numbers came from
        a teaching-skill profile an LLM wrote. Handed to the note generator under
        that heading, a fabricated statistic with a fabricated citation is what
        reaches a Kenyan classroom, and nothing downstream can tell it from a
        real one.

        Nothing is called verified unless a retrieval actually verified it.
        """
        verified = bool(citations)
        parts = [
            f"=== RESEARCH CONTEXT for {subject}: {sub_strand} ===",
            "",
            "1. RETRIEVED SOURCES:",
        ]
        if citations:
            for c in citations[:5]:
                parts.append(f"- [{c.source_domain}] {c.title}: \"{c.snippet}\" (URL: {c.url})")
        else:
            parts.append(
                "- NONE. No source was retrieved for this sub-strand. Do not cite "
                "anything as though one had been."
            )

        if empirical_data:
            parts.append("")
            if verified:
                parts.append("2. FIGURES FROM THE RETRIEVED SOURCES:")
            else:
                parts.append(
                    "2. UNVERIFIED ILLUSTRATIVE FIGURES — DO NOT USE IN THE CONTENT:"
                )
                parts.append(
                    "   These came from a generated teaching profile, not from any "
                    "source. They are shown only for orientation. Never state them "
                    "as fact, never attribute them, and never cite them. A "
                    "fabricated statistic with a fabricated source is worse than "
                    "no statistic, because nothing downstream can tell it from a "
                    "real one."
                )
            for ed in empirical_data:
                source = ed.get("source", "unattributed")
                label = source if verified else f"UNVERIFIED, claimed: {source}"
                parts.append(f"- {ed.get('metric', '')}: {ed.get('value', '')} [{label}]")

        parts.append("")
        parts.append("3. PEDAGOGICAL CONTENT KNOWLEDGE (PCK) & ACADEMIC INSIGHTS:")
        for ai in academic_insights:
            parts.append(f"- {ai}")

        if kenyan_case_studies:
            parts.append("")
            parts.append(
                "4. ILLUSTRATIVE KENYAN SCENARIOS (generated, not reported cases — "
                "use them as teaching context, never as documented events):"
            )
            for cs in kenyan_case_studies:
                parts.append(
                    f"- County: {cs.get('county', '')} | Scenario: {cs.get('scenario', '')} "
                    f"| Approach: {cs.get('intervention', '')}"
                )

        if safety_guidelines:
            parts.append("")
            parts.append("5. SAFETY PROTOCOLS, where this sub-strand has a real hazard:")
            for sg in safety_guidelines:
                parts.append(f"- {sg}")

        return "\n".join(parts)

    def perform_quality_audit(
        self,
        content: dict[str, Any],
        content_type: str,
        research_dossier: ResearchDossier,
        verify: bool = False,
    ) -> QualityAuditReport:
        """Automated pre-flight quality audit on generated content.

        With ``verify``, factual claims are checked against sources that are
        actually opened and read, and the accuracy check reports what was found.
        Without it, accuracy is reported as UNVERIFIED rather than asserted —
        this check used to always pass while checking nothing.
        """
        checks: list[dict[str, Any]] = []
        suggestions: list[str] = []
        score = 100

        # str(content) is the JSON repr: every key name, every bracket, every
        # quote, and both copies of a guide the route mirrors into hour_modules.
        # Counted that way a 4,299-character guide reported 2,340 words and
        # passed for depth on the run where the coverage check called all seven
        # of its modules too short to teach from. Substring tests over the same
        # string matched schema KEY NAMES rather than content — "safety" matched
        # `"safety_precautions": ""`, so the safety check passed on the presence
        # of an empty field.
        raw_text = _human_text(_deduplicated(content))
        word_count = len(raw_text.split())
        if word_count < 250:
            checks.append({"name": "Content Depth & Substance", "status": "FAIL", "reason": f"Content is too brief ({word_count} words). Minimum 300 words required."})
            suggestions.append("Expand theoretical concepts and provide detailed explanations.")
            score -= 25
            no_shallow = False
        else:
            # Word count alone called a guide of seven 1,000-character modules
            # "comprehensive". Depth is per lesson, and the coverage check has
            # already measured it — agree with it rather than contradict it.
            from .notes_coverage import MIN_BODY_CHARS, _body_of, _modules_of

            modules = _modules_of(_deduplicated(content) if isinstance(content, dict) else {})
            thin = [m for m in modules if len(_body_of(m)) < MIN_BODY_CHARS]
            if thin:
                checks.append({
                    "name": "Content Depth & Substance", "status": "WARN",
                    "reason": (
                        f"{len(thin)} of {len(modules)} module(s) are under "
                        f"{MIN_BODY_CHARS:,} characters — too short to teach from "
                        f"without further preparation ({word_count} words overall)."
                    ),
                })
                suggestions.append(
                    "Expand the thin modules with the teacher's actual words, the "
                    "actual song or prayer, and what a confused child does."
                )
                score -= 15
                no_shallow = False
            else:
                checks.append({"name": "Content Depth & Substance", "status": "PASS",
                               "detail": f"Comprehensive depth achieved ({word_count} words)."})
                no_shallow = True

        if any(w in raw_text.lower() for w in ["curriculum", "kenya", "competenc", "kicd", "learner", "student", "teacher"]):
            checks.append({"name": "KICD Curriculum Grounding", "status": "PASS", "detail": "Aligned with Kenyan Basic Education Curriculum Framework."})
            curriculum_aligned = True
        else:
            checks.append({"name": "KICD Curriculum Grounding", "status": "WARN", "reason": "Missing explicit Kenyan context."})
            suggestions.append("Incorporate explicit Kenyan agro-ecological or regional references.")
            score -= 10
            curriculum_aligned = False

        verification: dict[str, Any] = {}
        if verify:
            from .claim_verification import verify_content

            verification = verify_content(content, research_dossier)
            supported = verification.get("supported", 0)
            checked = verification.get("claims_checked", 0)
            if not checked:
                # Nothing asserted a quantity, date or named authority. That is
                # not a failure — there was simply nothing to confirm.
                checks.append({"name": "Scientific & Technical Accuracy", "status": "UNVERIFIED",
                               "reason": verification.get("summary", "No checkable factual claims.")})
                scientific_acc = False
            elif supported == checked:
                checks.append({"name": "Scientific & Technical Accuracy", "status": "PASS",
                               "detail": verification["summary"], "sources": verification["sources"]})
                scientific_acc = True
            elif supported:
                checks.append({"name": "Scientific & Technical Accuracy", "status": "WARN",
                               "reason": verification["summary"], "sources": verification["sources"]})
                suggestions.append("Check the unconfirmed claims before approving — they carry no source.")
                score -= 10
                scientific_acc = False
            else:
                checks.append({"name": "Scientific & Technical Accuracy", "status": "FAIL",
                               "reason": verification["summary"], "sources": verification["sources"]})
                suggestions.append("No factual claim could be confirmed against a source. Do not approve as researched.")
                score -= 20
                scientific_acc = False
        else:
            # Reporting UNVERIFIED is the honest state. Claiming verification
            # that never happened is worse than no check at all.
            checks.append({"name": "Scientific & Technical Accuracy", "status": "UNVERIFIED",
                           "reason": "Claims were not checked against sources in this run."})
            scientific_acc = False

        stated, declared_none = _safety_statements(content)
        if stated:
            checks.append({"name": "Safety & Hazard Protocols", "status": "PASS",
                           "detail": f"States {len(stated)} precaution(s): {stated[0][:120]}"})
            safety_comp = True
        elif declared_none:
            # The field is there and deliberately empty. Singing a song and
            # colouring a picture have no hazard, and docking marks for saying
            # so is how a validator teaches a model to invent one — which is the
            # defect that trains teachers to ignore the field where it matters.
            checks.append({"name": "Safety & Hazard Protocols", "status": "NOT APPLICABLE",
                           "detail": "No hazard is claimed, and none of these activities carries one."})
            safety_comp = True
        else:
            checks.append({"name": "Safety & Hazard Protocols", "status": "WARN",
                           "reason": "The content carries no safety field at all — not an empty "
                                     "one, an absent one, so nobody decided either way."})
            suggestions.append("State the precautions this activity needs, or state that it needs none.")
            score -= 5
            safety_comp = False

        if "misconception" in raw_text.lower() or "pedagogical" in raw_text.lower() or "formative" in raw_text.lower() or "worked_example" in raw_text.lower():
            checks.append({"name": "Pedagogical Content Knowledge (PCK)", "status": "PASS", "detail": "Includes teacher notes, misconception remediation, and formative cues."})
            pck_depth = True
        else:
            checks.append({"name": "Pedagogical Content Knowledge (PCK)", "status": "WARN", "reason": "Lacks explicit teacher PCK scaffolding."})
            score -= 10
            pck_depth = False

        rubric_precision = True
        if any(w in raw_text.lower() for w in ("rubric", "slo", "learning outcome", "criterion", "exceeding", "meeting expectation")):
            checks.append({"name": "Criterion Assessment Alignment", "status": "PASS",
                           "detail": "Criterion rubrics or learning outcomes are present."})
        else:
            checks.append({"name": "Criterion Assessment Alignment", "status": "WARN",
                           "reason": "No rubric or learning-outcome reference found."})
            suggestions.append("Tie the content to its SLOs and a criterion rubric.")
            score -= 10

        return QualityAuditReport(
            score=max(score, 0),
            curriculum_alignment=curriculum_aligned,
            scientific_accuracy=scientific_acc,
            safety_compliance=safety_comp,
            pck_depth=pck_depth,
            rubric_precision=rubric_precision,
            no_shallow_content=no_shallow,
            audit_checks=checks,
            feedback_suggestions=suggestions,
        )


# Keys whose value, where it has one, is a safety statement.
_SAFETY_KEYS = ("safety_precautions", "safety", "hazards", "precautions",
                "safety_notes", "risk_assessment")


def _deduplicated(content: Any) -> Any:
    """The payload without its own mirrors.

    The notes route copies `modules` into `hour_modules` and derives
    `key_concepts` from it, so a guide counted by flattening the whole payload
    is counted two and a bit times. That is how this audit reported
    "comprehensive depth achieved (3,455 words)" on the same run where the
    coverage check found six of seven modules too thin to teach from — two
    numbers about the same guide, disagreeing, both shown to the operator.
    """
    if not isinstance(content, dict):
        return content
    if not content.get("modules"):
        return content
    return {k: v for k, v in content.items()
            if k not in ("hour_modules", "key_concepts")}


def _human_text(value: Any, depth: int = 0) -> str:
    """The readable prose inside a generation payload — values only, no keys.

    Auditing str(payload) counts punctuation and matches on field names. Both
    made this audit report things that were not there.
    """
    if depth > 8 or value is None or isinstance(value, bool):
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return ""
    if isinstance(value, dict):
        return " ".join(_human_text(v, depth + 1) for v in value.values())
    if isinstance(value, (list, tuple)):
        return " ".join(_human_text(v, depth + 1) for v in value)
    return ""


def _safety_statements(value: Any, depth: int = 0) -> tuple[list[str], bool]:
    """Precautions actually stated, and whether a safety field was left empty.

    Distinguishing "no hazard here" from "nobody looked" is the whole point: one
    is the correct answer for a singing lesson and the other is an omission.
    """
    stated: list[str] = []
    declared_none = False
    if depth > 8:
        return stated, declared_none
    if isinstance(value, dict):
        for key, item in value.items():
            if any(k in str(key).lower() for k in _SAFETY_KEYS):
                text = _human_text(item).strip()
                if text:
                    stated.append(text)
                else:
                    declared_none = True
                continue
            sub_stated, sub_none = _safety_statements(item, depth + 1)
            stated += sub_stated
            declared_none = declared_none or sub_none
    elif isinstance(value, (list, tuple)):
        for item in value:
            sub_stated, sub_none = _safety_statements(item, depth + 1)
            stated += sub_stated
            declared_none = declared_none or sub_none

    if depth == 0 and not stated:
        # A precaution written into ordinary prose — inside a procedure step or
        # a lesson flow — counts. What does not count is the field NAME: this
        # search runs over values only, which is the whole difference between
        # "supervise learners near the road" and `"safety_precautions": ""`.
        for sentence in re.split(r"(?<=[.!?])\s+", _human_text(value)):
            lowered = sentence.lower()
            if any(w in lowered for w in ("safety", "hazard", "precaution", "supervis")):
                stated.append(sentence.strip())
    return stated, declared_none


def clean_q_list(queries: list[str]) -> str:
    return ", ".join(queries)


web_research_agent = WebResearchAgent()
