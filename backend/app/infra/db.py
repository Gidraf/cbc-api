from __future__ import annotations

import json
import logging
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from ..settings import settings

logger = logging.getLogger("cbc-db")

MIGRATIONS: list[tuple[str, str]] = [
    (
        "001_initial_schema",
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS provider_configs (
            provider TEXT PRIMARY KEY,
            base_url TEXT NULL,
            encrypted_api_key TEXT NULL,
            credential_ref_id TEXT NULL,
            ollama_models JSONB NOT NULL DEFAULT '[]'::jsonb,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS stage_bindings (
            pipeline_stage TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            base_url TEXT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS pipeline_runs (
            run_id TEXT PRIMARY KEY,
            request_id TEXT NOT NULL,
            trace_id TEXT NOT NULL,
            workflow_state TEXT NOT NULL,
            result JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS app_users (
            username TEXT PRIMARY KEY,
            password_plain TEXT NOT NULL,
            role TEXT NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """,
    ),
    (
        "002_full_schema",
        """
        CREATE TABLE IF NOT EXISTS curriculum_nodes (
            id SERIAL PRIMARY KEY,
            universal_id TEXT UNIQUE NOT NULL,
            level TEXT NOT NULL,
            grade TEXT NOT NULL,
            subject TEXT NOT NULL,
            strand TEXT NOT NULL,
            sub_strand TEXT NOT NULL,
            slo_id TEXT NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS diagram_registry (
            diagram_id TEXT PRIMARY KEY,
            content_hash TEXT UNIQUE NOT NULL,
            storage_url TEXT NOT NULL,
            alt_text TEXT NOT NULL DEFAULT '',
            tactile_description TEXT NOT NULL DEFAULT '',
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS question_dna (
            question_id TEXT PRIMARY KEY,
            universal_id TEXT NOT NULL,
            curriculum_link JSONB NOT NULL DEFAULT '{}'::jsonb,
            pedagogical_dna JSONB NOT NULL DEFAULT '{}'::jsonb,
            content JSONB NOT NULL DEFAULT '{}'::jsonb,
            provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
            review_audit JSONB NOT NULL DEFAULT '{}'::jsonb,
            status TEXT NOT NULL DEFAULT 'approved',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS substrand_resources (
            bundle_id TEXT PRIMARY KEY,
            curriculum JSONB NOT NULL DEFAULT '{}'::jsonb,
            notes JSONB NOT NULL DEFAULT '{}'::jsonb,
            diagrams JSONB NOT NULL DEFAULT '[]'::jsonb,
            activities JSONB NOT NULL DEFAULT '[]'::jsonb,
            questions JSONB NOT NULL DEFAULT '[]'::jsonb,
            review_audit JSONB NOT NULL DEFAULT '{}'::jsonb,
            status TEXT NOT NULL DEFAULT 'published',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS generation_targets (
            id SERIAL PRIMARY KEY,
            target_date DATE UNIQUE NOT NULL,
            target_count INT NOT NULL DEFAULT 100,
            completed_count INT NOT NULL DEFAULT 0,
            approved_count INT NOT NULL DEFAULT 0,
            rejected_count INT NOT NULL DEFAULT 0,
            grade_breakdown JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS milestone_events (
            id SERIAL PRIMARY KEY,
            target_date DATE NOT NULL,
            tier TEXT NOT NULL,
            event_data JSONB NOT NULL DEFAULT '{}'::jsonb,
            sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_date_tier UNIQUE (target_date, tier)
        );

        CREATE TABLE IF NOT EXISTS audit_events (
            id SERIAL PRIMARY KEY,
            event_type TEXT NOT NULL,
            actor TEXT NOT NULL,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS idempotency_cache (
            idempotency_key TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            result JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMPTZ NOT NULL
        );
        """,
    ),
    (
        "003_auth_upgrade",
        """
        ALTER TABLE app_users ADD COLUMN IF NOT EXISTS password_hash TEXT NULL;
        ALTER TABLE app_users ADD COLUMN IF NOT EXISTS email TEXT NULL;
        ALTER TABLE app_users ADD COLUMN IF NOT EXISTS is_approved BOOLEAN NOT NULL DEFAULT TRUE;

        CREATE TABLE IF NOT EXISTS api_keys (
            key_id TEXT PRIMARY KEY,
            key_hash TEXT NOT NULL,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'developer',
            label TEXT NOT NULL DEFAULT 'Default API Key',
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            last_used_at TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS refresh_tokens (
            token_hash TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """,
    ),
    (
        "004_cost_tracking",
        """
        CREATE TABLE IF NOT EXISTS generation_costs (
            id SERIAL PRIMARY KEY,
            run_id TEXT NOT NULL,
            pipeline_stage TEXT NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            prompt_tokens INT DEFAULT 0,
            completion_tokens INT DEFAULT 0,
            total_tokens INT DEFAULT 0,
            input_cost_usd NUMERIC(10,6) DEFAULT 0,
            output_cost_usd NUMERIC(10,6) DEFAULT 0,
            total_cost_usd NUMERIC(10,6) DEFAULT 0,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        ALTER TABLE substrand_resources ADD COLUMN IF NOT EXISTS total_tokens INT DEFAULT 0;
        ALTER TABLE substrand_resources ADD COLUMN IF NOT EXISTS total_cost_usd NUMERIC(10,6) DEFAULT 0;
        """,
    ),
    (
        "005_curriculum_intelligence_and_universal_dna",
        """
        CREATE TABLE IF NOT EXISTS curriculum_designs (
            design_id TEXT PRIMARY KEY,
            subject TEXT NOT NULL,
            subject_code TEXT NOT NULL DEFAULT '',
            grade TEXT NOT NULL,
            level TEXT NOT NULL DEFAULT '',
            essence_statement TEXT NOT NULL DEFAULT '',
            general_learning_outcomes JSONB NOT NULL DEFAULT '[]'::jsonb,
            raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS curriculum_substrands (
            id SERIAL PRIMARY KEY,
            design_id TEXT NOT NULL REFERENCES curriculum_designs(design_id) ON DELETE CASCADE,
            grade TEXT NOT NULL,
            subject TEXT NOT NULL,
            strand_id TEXT NOT NULL,
            strand_name TEXT NOT NULL,
            sub_strand_id TEXT NOT NULL,
            sub_strand_name TEXT NOT NULL,
            allocated_hours TEXT NOT NULL DEFAULT '',
            slos JSONB NOT NULL DEFAULT '[]'::jsonb,
            learning_experiences JSONB NOT NULL DEFAULT '[]'::jsonb,
            key_inquiry_questions JSONB NOT NULL DEFAULT '[]'::jsonb,
            core_competencies JSONB NOT NULL DEFAULT '[]'::jsonb,
            values JSONB NOT NULL DEFAULT '[]'::jsonb,
            assessment_rubrics JSONB NOT NULL DEFAULT '[]'::jsonb,
            required_diagrams JSONB NOT NULL DEFAULT '[]'::jsonb,
            experiments JSONB NOT NULL DEFAULT '[]'::jsonb,
            pedagogical_guidance JSONB NOT NULL DEFAULT '{}'::jsonb,
            prompt_context JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_grade_subject_substrand UNIQUE (grade, subject, strand_name, sub_strand_name)
        );

        CREATE TABLE IF NOT EXISTS artifact_dna (
            dna_id TEXT PRIMARY KEY,
            artifact_type TEXT NOT NULL, -- 'notes', 'diagram', 'activity', 'question', 'bundle'
            artifact_id TEXT NOT NULL,
            universal_slo_id TEXT NOT NULL DEFAULT '',
            curriculum_link JSONB NOT NULL DEFAULT '{}'::jsonb,
            dna_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            compliance_scores JSONB NOT NULL DEFAULT '{}'::jsonb,
            provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
            status TEXT NOT NULL DEFAULT 'verified',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS idx_curriculum_substrands_lookup ON curriculum_substrands(grade, subject);
        CREATE INDEX IF NOT EXISTS idx_artifact_dna_artifact ON artifact_dna(artifact_type, artifact_id);
        CREATE INDEX IF NOT EXISTS idx_artifact_dna_slo ON artifact_dna(universal_slo_id);
        """,
    ),
    (
        "006_blueprint_review_status",
        """
        ALTER TABLE curriculum_designs ADD COLUMN IF NOT EXISTS review_status TEXT NOT NULL DEFAULT 'accepted_active';
        ALTER TABLE curriculum_designs ADD COLUMN IF NOT EXISTS human_review_notes TEXT NULL;
        """,
    ),
]


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required for Postgres persistence")
    return create_engine(settings.database_url, pool_pre_ping=True)


def run_migrations() -> None:
    engine = get_engine()
    with engine.begin() as conn:
        # 1. Acquire transactional advisory lock to prevent race conditions across concurrent container startups (api vs worker)
        try:
            conn.execute(text("SELECT pg_advisory_xact_lock(748392019);"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not acquire advisory lock: %s", exc)

        # 2. Ensure migrations tracking table exists
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
        )

        # 3. Read applied migrations inside the locked transaction
        rows = conn.execute(text("SELECT version FROM schema_migrations")).mappings().all()
        applied = {row["version"] for row in rows}

        for version, sql_script in MIGRATIONS:
            if version in applied:
                continue

            logger.info("Applying database migration: %s", version)
            try:
                conn.execute(text(sql_script))
                conn.execute(
                    text(
                        """
                        INSERT INTO schema_migrations (version, applied_at)
                        VALUES (:version, NOW())
                        ON CONFLICT (version) DO NOTHING
                        """
                    ),
                    {"version": version},
                )
                logger.info("✓ Migration %s applied successfully", version)
            except Exception as exc:  # noqa: BLE001
                # If unique violation occurs on pg_type / existing tables from prior runs, mark migration applied
                if "already exists" in str(exc) or "UniqueViolation" in str(exc):
                    logger.warning("Migration %s objects already exist: %s. Marking as applied.", version, exc)
                    conn.execute(
                        text(
                            """
                            INSERT INTO schema_migrations (version, applied_at)
                            VALUES (:version, NOW())
                            ON CONFLICT (version) DO NOTHING
                            """
                        ),
                        {"version": version},
                    )
                else:
                    raise


def fetch_all(query: str, params: dict | None = None) -> list[dict]:
    engine = get_engine()
    with engine.begin() as conn:
        rows = conn.execute(text(query), params or {}).mappings().all()
        return [dict(row) for row in rows]


def fetch_one(query: str, params: dict | None = None) -> dict | None:
    result = fetch_all(query, params)
    return result[0] if result else None


query_one = fetch_one
query_all = fetch_all


def execute(query: str, params: dict | None = None) -> None:
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text(query), params or {})


def to_json(value: dict | list | str | int | float | bool | None) -> str:
    return json.dumps(value)
