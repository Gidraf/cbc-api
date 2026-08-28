from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from ..infra.db import execute, fetch_all, fetch_one, to_json
from ..models import now_iso
from . import dna_scoring
from .dna_scoring import ScoreSet
from .grade_order import grade_ordinal

logger = logging.getLogger("cbc-artifact-dna")

# A certificate is only marked verified when its computed metrics clear this bar.
VERIFY_THRESHOLD = 0.75
REVIEW_THRESHOLD = 0.55


def _status_for(mean: float | None, verified_label: str = "verified") -> str:
    """Derive status from measured quality rather than asserting it."""
    if mean is None:
        return "unscored"
    if mean >= VERIFY_THRESHOLD:
        return verified_label
    if mean >= REVIEW_THRESHOLD:
        return "needs_review"
    return "rejected"


@dataclass(slots=True)
class DnaCertificate:
    dna_id: str
    artifact_type: str  # 'dataset', 'subject', 'strand', 'substrand', 'notes', 'diagram', 'activity', 'question', 'bundle'
    artifact_id: str
    universal_slo_id: str
    curriculum_link: dict[str, Any]
    dna_payload: dict[str, Any]
    compliance_scores: dict[str, Any]
    provenance: dict[str, Any]
    parent_dna_id: str | None
    status: str
    created_at: str
    # Retained in memory so a bundle can aggregate its stages' measurements.
    # Not persisted directly; the detail lives in dna_payload["score_detail"].
    score_set: ScoreSet | None = field(default=None, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dna_id": self.dna_id,
            "artifact_type": self.artifact_type,
            "artifact_id": self.artifact_id,
            "universal_slo_id": self.universal_slo_id,
            "curriculum_link": self.curriculum_link,
            "dna_payload": self.dna_payload,
            "compliance_scores": self.compliance_scores,
            "provenance": self.provenance,
            "parent_dna_id": self.parent_dna_id,
            "status": self.status,
            "created_at": self.created_at,
        }


class UniversalArtifactDnaService:
    """Compliance certificates for the CBC hierarchy: Dataset → Subject → Strand
    → Substrand → Artifacts → Bundle.

    Every score carries the method that produced it. Metrics that cannot be known
    at generation time — item discrimination, for instance, which needs learner
    response data — are recorded as pending rather than asserted as a constant.
    """

    # ── 1. CURRICULUM LEVEL DNAs (Dataset → Subject → Strand → Substrand) ────

    def generate_dataset_dna(
        self,
        dataset_id: str,
        raw_text: str,
        source_meta: dict[str, Any],
    ) -> DnaCertificate:
        raw_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()

        dna_payload = {
            "dataset_id": dataset_id,
            "raw_sha256": raw_hash,
            "char_count": len(raw_text),
            "source_meta": source_meta,
            "provenance_signature": f"KICD_RAW_SOURCE_{raw_hash[:16]}",
        }

        # Integrity of a stored blob genuinely is deterministic: the bytes either
        # hash to the recorded digest or they do not.
        scores = {
            "data_integrity": 1.0 if raw_text else 0.0,
            "source_present": 1.0 if raw_text.strip() else 0.0,
        }

        cert = DnaCertificate(
            dna_id=f"dna_raw_{dataset_id[-12:]}",
            artifact_type="dataset",
            artifact_id=dataset_id,
            universal_slo_id="ROOT",
            curriculum_link={"source": source_meta.get("source", "raw")},
            dna_payload=dna_payload,
            compliance_scores=scores,
            provenance=source_meta,
            parent_dna_id=None,
            status="verified" if raw_text.strip() else "rejected",
            created_at=now_iso(),
        )
        self._persist_dna(cert)
        return cert

    def generate_subject_dna(
        self,
        subject: str,
        grade: str,
        level: str,
        essence_statement: str,
        general_outcomes: list[str],
        parent_dataset_dna_id: str,
        raw_snippet: str,
    ) -> DnaCertificate:
        raw_source_hash = hashlib.sha256(raw_snippet.encode("utf-8")).hexdigest()

        grounding = dna_scoring.containment(subject, raw_snippet)
        essence_grounding = (
            dna_scoring.containment(essence_statement, raw_snippet) if essence_statement.strip() else 0.0
        )

        dna_payload = {
            "subject": subject,
            "grade": grade,
            "level": level,
            "essence_statement_hash": hashlib.sha256(essence_statement.encode()).hexdigest(),
            "general_outcomes_count": len(general_outcomes),
            "raw_source_hash": raw_source_hash,
            "score_detail": {
                "subject_name_grounding": {
                    "value": grounding,
                    "method": "term_containment_in_source",
                    "evidence": "fraction of the subject name's terms found in the source design",
                },
                "essence_grounding": {
                    "value": essence_grounding,
                    "method": "term_containment_in_source",
                    "evidence": "how much of the essence statement traces to the source text",
                },
            },
        }

        scores = {
            "subject_name_grounding": grounding,
            "essence_grounding": essence_grounding,
            "outcomes_present": 1.0 if general_outcomes else 0.0,
        }
        mean = round(sum(scores.values()) / len(scores), 4)

        subject_slug = subject.lower().replace(" ", "_")[:12]
        cert = DnaCertificate(
            dna_id=f"dna_subj_{grade}_{subject_slug}",
            artifact_type="subject",
            artifact_id=f"{grade}_{subject}",
            universal_slo_id=f"SUBJ-{subject_slug.upper()}",
            curriculum_link={"subject": subject, "grade": grade, "level": level},
            dna_payload=dna_payload,
            compliance_scores=scores,
            provenance={"parent_dataset_dna_id": parent_dataset_dna_id},
            parent_dna_id=parent_dataset_dna_id,
            status=_status_for(mean),
            created_at=now_iso(),
        )
        self._persist_dna(cert)
        return cert

    def generate_strand_dna(
        self,
        strand_id: str,
        strand_name: str,
        grade: str,
        subject: str,
        parent_subject_dna_id: str,
        raw_strand_snippet: str,
    ) -> DnaCertificate:
        grounding = dna_scoring.containment(strand_name, raw_strand_snippet)

        dna_payload = {
            "strand_id": strand_id,
            "strand_name": strand_name,
            "strand_hash": hashlib.sha256(strand_name.encode("utf-8")).hexdigest(),
            "raw_source_hash": hashlib.sha256(raw_strand_snippet.encode("utf-8")).hexdigest(),
        }

        scores = {"strand_name_grounding": grounding}

        clean_strand = strand_id.replace(".", "_")
        cert = DnaCertificate(
            dna_id=f"dna_strand_{grade}_{clean_strand}",
            artifact_type="strand",
            artifact_id=f"{grade}_{subject}_{strand_id}",
            universal_slo_id=f"STRAND-{strand_id}",
            curriculum_link={"subject": subject, "grade": grade, "strand": strand_name},
            dna_payload=dna_payload,
            compliance_scores=scores,
            provenance={"parent_subject_dna_id": parent_subject_dna_id},
            parent_dna_id=parent_subject_dna_id,
            status=_status_for(grounding),
            created_at=now_iso(),
        )
        self._persist_dna(cert)
        return cert

    def generate_substrand_dna(
        self,
        grade: str,
        subject: str,
        strand_name: str,
        sub_strand_id: str,
        sub_strand_name: str,
        allocated_hours: str,
        slos: list[dict[str, str]],
        kiqs: list[str],
        diagrams_required: list[str],
        experiments: list[str],
        parent_strand_dna_id: str,
        raw_substrand_snippet: str,
    ) -> DnaCertificate:
        source_hash = hashlib.sha256(raw_substrand_snippet.encode("utf-8")).hexdigest()

        per_slo = [
            dna_scoring.containment(s.get("text", "") if isinstance(s, dict) else str(s), raw_substrand_snippet)
            for s in (slos or [])
        ]
        grounded_slos = sum(1 for c in per_slo if c >= 0.5)
        grounding_ratio = round(grounded_slos / len(per_slo), 4) if per_slo else 0.0

        dna_payload = {
            "sub_strand_id": sub_strand_id,
            "sub_strand_name": sub_strand_name,
            "allocated_hours": allocated_hours,
            "slo_count": len(slos or []),
            "kiq_count": len(kiqs or []),
            "diagrams_discovered": diagrams_required,
            "experiments_discovered": experiments,
            "raw_source_hash": source_hash,
            "score_detail": {
                "slo_grounding": {
                    "value": grounding_ratio,
                    "method": "slo_term_containment_in_source",
                    "evidence": f"{grounded_slos} of {len(per_slo)} SLOs traced to the source design",
                    "sample_size": len(per_slo),
                }
            },
        }

        scores = {
            "slo_grounding": grounding_ratio,
            "blueprint_completeness": round(
                sum([bool(slos), bool(kiqs), bool(allocated_hours), bool(diagrams_required)]) / 4, 4
            ),
        }
        mean = round(sum(scores.values()) / len(scores), 4)

        clean_sub = sub_strand_id.replace(".", "_")
        cert = DnaCertificate(
            dna_id=f"dna_sub_{grade}_{clean_sub}",
            artifact_type="substrand",
            artifact_id=f"{grade}_{subject}_{sub_strand_name}",
            universal_slo_id=f"SUBSTRAND-{sub_strand_id}",
            curriculum_link={
                "subject": subject,
                "grade": grade,
                "strand": strand_name,
                "sub_strand": sub_strand_name,
            },
            dna_payload=dna_payload,
            compliance_scores=scores,
            provenance={"parent_strand_dna_id": parent_strand_dna_id},
            parent_dna_id=parent_strand_dna_id,
            status=_status_for(mean) if mean >= REVIEW_THRESHOLD else "flagged_hallucination_risk",
            created_at=now_iso(),
        )
        self._persist_dna(cert)
        return cert

    # ── 2. GENERATION STAGE ARTIFACT DNAs ───────────────────────────────────

    def generate_notes_dna(
        self,
        notes_id: str,
        curriculum: dict[str, Any],
        notes_content: dict[str, Any],
        provenance: dict[str, Any],
        parent_substrand_dna_id: str | None = None,
        blueprint_slos: list[Any] | None = None,
        raw_source: str = "",
    ) -> DnaCertificate:
        scores = dna_scoring.score_notes(
            notes_content,
            blueprint_slos or [],
            grade_ordinal(curriculum.get("grade")),
            raw_source,
        )

        modules = notes_content.get("modules") or notes_content.get("hour_modules") or notes_content.get("key_concepts") or notes_content.get("sections") or []
        dna_payload = {
            "title": notes_content.get("title", ""),
            "module_count": len(modules) if isinstance(modules, list) else 0,
            "kicd_citation_hash": hashlib.sha256(
                f"{notes_content.get('title', '')}{json.dumps(modules, default=str)}".encode("utf-8")
            ).hexdigest(),
            "parent_substrand_dna_id": parent_substrand_dna_id,
            "score_detail": scores.detail(),
            "weakest_metrics": scores.weakest(),
        }

        cert = DnaCertificate(
            dna_id=f"dna_notes_{notes_id[-10:]}",
            artifact_type="notes",
            artifact_id=notes_id,
            universal_slo_id=curriculum.get("slo_id", "SLO-GEN"),
            curriculum_link=curriculum,
            dna_payload=dna_payload,
            compliance_scores=scores.values_only(),
            provenance=provenance,
            parent_dna_id=parent_substrand_dna_id,
            status=_status_for(scores.mean()),
            created_at=now_iso(),
            score_set=scores,
        )
        self._persist_dna(cert)
        return cert

    def generate_diagram_dna(
        self,
        diagram_id: str,
        curriculum: dict[str, Any],
        diagram_data: dict[str, Any],
        provenance: dict[str, Any],
        parent_substrand_dna_id: str | None = None,
        concept: str = "",
    ) -> DnaCertificate:
        scores = dna_scoring.score_diagram(
            diagram_data,
            concept or curriculum.get("sub_strand", ""),
        )

        dna_payload = {
            "diagram_title": diagram_data.get("diagram_title", ""),
            "diagram_hash": hashlib.sha256(
                str(diagram_data.get("diagram_svg", "")).encode("utf-8")
            ).hexdigest(),
            "storage_url": diagram_data.get("storage_url", ""),
            "dedup_status": diagram_data.get("dedup_status", "new"),
            "has_scene_document": bool(diagram_data.get("scene_document")),
            "parent_substrand_dna_id": parent_substrand_dna_id,
            "score_detail": scores.detail(),
            "weakest_metrics": scores.weakest(),
        }

        cert = DnaCertificate(
            dna_id=f"dna_diag_{diagram_id[-10:]}",
            artifact_type="diagram",
            artifact_id=diagram_id,
            universal_slo_id=curriculum.get("slo_id", "SLO-GEN"),
            curriculum_link=curriculum,
            dna_payload=dna_payload,
            compliance_scores=scores.values_only(),
            provenance=provenance,
            parent_dna_id=parent_substrand_dna_id,
            status=_status_for(scores.mean()),
            created_at=now_iso(),
            score_set=scores,
        )
        self._persist_dna(cert)
        return cert

    def generate_activity_dna(
        self,
        activity_id: str,
        curriculum: dict[str, Any],
        activity_data: dict[str, Any],
        provenance: dict[str, Any],
        parent_substrand_dna_id: str | None = None,
        content_type: str = "generic",
    ) -> DnaCertificate:
        scores = dna_scoring.score_activity(activity_data, content_type)

        activities = activity_data.get("activities") or []
        experiments = activity_data.get("experiments") or []
        dna_payload = {
            "activity_count": len(activities) if isinstance(activities, list) else 0,
            "experiment_count": len(experiments) if isinstance(experiments, list) else 0,
            "content_type": content_type,
            "parent_substrand_dna_id": parent_substrand_dna_id,
            "score_detail": scores.detail(),
            "weakest_metrics": scores.weakest(),
        }

        cert = DnaCertificate(
            dna_id=f"dna_act_{activity_id[-10:]}",
            artifact_type="activity",
            artifact_id=activity_id,
            universal_slo_id=curriculum.get("slo_id", "SLO-GEN"),
            curriculum_link=curriculum,
            dna_payload=dna_payload,
            compliance_scores=scores.values_only(),
            provenance=provenance,
            parent_dna_id=parent_substrand_dna_id,
            status=_status_for(scores.mean()),
            created_at=now_iso(),
            score_set=scores,
        )
        self._persist_dna(cert)
        return cert

    def generate_question_dna(
        self,
        question_id: str,
        curriculum: dict[str, Any],
        question_item: dict[str, Any],
        provenance: dict[str, Any],
        parent_substrand_dna_id: str | None = None,
        notes_body: str = "",
    ) -> DnaCertificate:
        content = question_item.get("content", question_item) or {}
        pedagogy = question_item.get("pedagogical_dna", {}) or {}

        scores = dna_scoring.score_question(
            {**content, "rubric": question_item.get("rubric") or content.get("rubric") or {}},
            slo_text=str(curriculum.get("slo_text") or ""),
            notes_body=notes_body,
            grade_ordinal=grade_ordinal(curriculum.get("grade")),
        )

        dna_payload = {
            "universal_id": question_item.get("universal_id", curriculum.get("slo_id", "")),
            "question_type": content.get("question_type", "multiple_choice"),
            "bloom_taxonomy": pedagogy.get("bloom_level", "Applying"),
            "difficulty_index": pedagogy.get("difficulty_index", 0.5),
            "max_marks": pedagogy.get("max_marks", 1),
            "rubric_aligned": bool(question_item.get("rubric") or content.get("rubric")),
            "parent_substrand_dna_id": parent_substrand_dna_id,
            "score_detail": scores.detail(),
            "weakest_metrics": scores.weakest(),
        }

        cert = DnaCertificate(
            dna_id=f"dna_q_{question_id[-10:]}",
            artifact_type="question",
            artifact_id=question_id,
            universal_slo_id=curriculum.get("slo_id", "SLO-GEN"),
            curriculum_link=curriculum,
            dna_payload=dna_payload,
            compliance_scores=scores.values_only(),
            provenance=provenance,
            parent_dna_id=parent_substrand_dna_id,
            status=_status_for(scores.mean()),
            created_at=now_iso(),
            score_set=scores,
        )
        self._persist_dna(cert)
        return cert

    def generate_bundle_dna(
        self,
        bundle_id: str,
        curriculum: dict[str, Any],
        stage_dnas: list[DnaCertificate],
        provenance: dict[str, Any],
        parent_substrand_dna_id: str | None = None,
    ) -> DnaCertificate:
        merkle_root = hashlib.sha256(
            "".join(d.dna_id + json.dumps(d.compliance_scores, sort_keys=True, default=str) for d in stage_dnas).encode("utf-8")
        ).hexdigest()

        scores = dna_scoring.score_bundle([d.score_set for d in stage_dnas if d.score_set])

        failing = [d.dna_id for d in stage_dnas if d.status in {"needs_review", "rejected"}]

        dna_payload = {
            "bundle_merkle_root": merkle_root,
            "verified_artifact_stages": [d.artifact_type for d in stage_dnas],
            "stage_dna_ids": [d.dna_id for d in stage_dnas],
            "total_artifacts": len(stage_dnas),
            "stages_needing_attention": failing,
            "parent_substrand_dna_id": parent_substrand_dna_id,
            "score_detail": scores.detail(),
        }

        # A bundle is only as publishable as its weakest layer, so a failing stage
        # blocks the bundle regardless of what the average says.
        mean = scores.mean()
        status = "needs_review" if failing else _status_for(mean)

        cert = DnaCertificate(
            dna_id=f"dna_bundle_{bundle_id[-10:]}",
            artifact_type="bundle",
            artifact_id=bundle_id,
            universal_slo_id=curriculum.get("slo_id", "SLO-GEN"),
            curriculum_link=curriculum,
            dna_payload=dna_payload,
            compliance_scores=scores.values_only(),
            provenance=provenance,
            parent_dna_id=parent_substrand_dna_id,
            status=status,
            created_at=now_iso(),
            score_set=scores,
        )
        self._persist_dna(cert)
        return cert

    # ── 3. DNA RETRIEVAL & LINEAGE TRACING ──────────────────────────────────

    def get_dna_certificate(self, artifact_id: str) -> dict[str, Any] | None:
        return fetch_one(
            "SELECT * FROM artifact_dna WHERE artifact_id = :aid OR dna_id = :aid ORDER BY created_at DESC",
            {"aid": artifact_id},
        )

    def get_complete_lineage(self, dna_id: str) -> list[dict[str, Any]]:
        """Walks the chain of custody from an artifact back to its source dataset."""
        lineage: list[dict[str, Any]] = []
        curr_id: str | None = dna_id
        visited: set[str] = set()

        while curr_id and curr_id not in visited:
            visited.add(curr_id)
            node = fetch_one(
                """
                SELECT dna_id, artifact_type, artifact_id, parent_dna_id, universal_slo_id,
                       compliance_scores, status, created_at
                FROM artifact_dna WHERE dna_id = :did OR artifact_id = :did
                """,
                {"did": curr_id},
            )
            if not node:
                break
            lineage.append(node)
            curr_id = node.get("parent_dna_id")

        return lineage

    def list_dnas_for_slo(self, slo_id: str) -> list[dict[str, Any]]:
        return fetch_all(
            "SELECT * FROM artifact_dna WHERE universal_slo_id = :slo ORDER BY created_at DESC",
            {"slo": slo_id},
        )

    def _persist_dna(self, cert: DnaCertificate) -> None:
        try:
            from ..infra.storage import object_storage

            object_storage.save_dna_certificate(cert.dna_id, cert.to_dict())
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not mirror DNA certificate %s to object storage: %s", cert.dna_id, exc)

        try:
            execute(
                """
                INSERT INTO artifact_dna (
                    dna_id, artifact_type, artifact_id, universal_slo_id, curriculum_link,
                    dna_payload, compliance_scores, provenance, parent_dna_id, status, updated_at
                )
                VALUES (
                    :dna_id, :artifact_type, :artifact_id, :universal_slo_id,
                    CAST(:curriculum_link AS jsonb), CAST(:dna_payload AS jsonb),
                    CAST(:compliance_scores AS jsonb), CAST(:provenance AS jsonb),
                    :parent_dna_id, :status, NOW()
                )
                ON CONFLICT (dna_id) DO UPDATE SET
                    curriculum_link = EXCLUDED.curriculum_link,
                    dna_payload = EXCLUDED.dna_payload,
                    compliance_scores = EXCLUDED.compliance_scores,
                    provenance = EXCLUDED.provenance,
                    parent_dna_id = EXCLUDED.parent_dna_id,
                    status = EXCLUDED.status,
                    updated_at = NOW()
                """,
                {
                    "dna_id": cert.dna_id,
                    "artifact_type": cert.artifact_type,
                    "artifact_id": cert.artifact_id,
                    "universal_slo_id": cert.universal_slo_id,
                    "curriculum_link": to_json(cert.curriculum_link),
                    "dna_payload": to_json(cert.dna_payload),
                    "compliance_scores": to_json(cert.compliance_scores),
                    "provenance": to_json(cert.provenance),
                    "parent_dna_id": cert.parent_dna_id,
                    "status": cert.status,
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not persist Artifact DNA %s: %s", cert.dna_id, exc)


artifact_dna_service = UniversalArtifactDnaService()
