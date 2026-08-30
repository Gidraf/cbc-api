from __future__ import annotations

import dataclasses
import datetime
import decimal
import json
import logging
import uuid
from functools import lru_cache
from typing import Any

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
            parent_dna_id TEXT NULL,
            status TEXT NOT NULL DEFAULT 'verified',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS idx_curriculum_substrands_lookup ON curriculum_substrands(grade, subject);
        CREATE INDEX IF NOT EXISTS idx_artifact_dna_artifact ON artifact_dna(artifact_type, artifact_id);
        CREATE INDEX IF NOT EXISTS idx_artifact_dna_slo ON artifact_dna(universal_slo_id);
        CREATE INDEX IF NOT EXISTS idx_artifact_dna_parent ON artifact_dna(parent_dna_id);
        """,
    ),
    (
        "006_blueprint_review_status",
        """
        ALTER TABLE curriculum_designs ADD COLUMN IF NOT EXISTS review_status TEXT NOT NULL DEFAULT 'accepted_active';
        ALTER TABLE curriculum_designs ADD COLUMN IF NOT EXISTS human_review_notes TEXT NULL;
        """,
    ),
    (
        "007_subject_profiles",
        """
        CREATE TABLE IF NOT EXISTS subject_profiles (
            id SERIAL PRIMARY KEY,
            subject TEXT NOT NULL,
            grade TEXT NOT NULL DEFAULT 'all',
            content_type TEXT NOT NULL DEFAULT 'generic',
            persona TEXT NOT NULL,
            note_style TEXT NOT NULL,
            diagram_type TEXT NOT NULL,
            activity_type TEXT NOT NULL,
            question_type TEXT NOT NULL,
            safety_focus TEXT NOT NULL,
            grade_appropriate_tone TEXT NOT NULL DEFAULT 'formal academic',
            special_directives JSONB NOT NULL DEFAULT '[]'::jsonb,
            empirical_insights JSONB NOT NULL DEFAULT '[]'::jsonb,
            case_studies JSONB NOT NULL DEFAULT '[]'::jsonb,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_subject_grade UNIQUE (subject, grade)
        );
        CREATE INDEX IF NOT EXISTS idx_subject_profiles_lookup ON subject_profiles(subject, grade);
        """,
    ),
    (
        "008_curriculum_designs_status_compat",
        """
        ALTER TABLE curriculum_designs ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'accepted_active';
        ALTER TABLE curriculum_designs ADD COLUMN IF NOT EXISTS review_status TEXT NOT NULL DEFAULT 'accepted_active';
        ALTER TABLE curriculum_designs ADD COLUMN IF NOT EXISTS human_review_notes TEXT NULL;
        """,
    ),
    (
        "009_artifact_dna_parent_col",
        """
        ALTER TABLE artifact_dna ADD COLUMN IF NOT EXISTS parent_dna_id TEXT NULL;
        CREATE INDEX IF NOT EXISTS idx_artifact_dna_parent ON artifact_dna(parent_dna_id);
        """,
    ),
    (
        "010_question_identity_and_ordering",
        """
        -- Questions were keyed on the model's positional label ("Q1"), so every
        -- approved batch overwrote the previous one. Give surviving rows unique
        -- IDs, then add the columns that make ordering and versioning possible.

        ALTER TABLE question_dna ADD COLUMN IF NOT EXISTS grade_ordinal INT NOT NULL DEFAULT 999;
        ALTER TABLE question_dna ADD COLUMN IF NOT EXISTS version INT NOT NULL DEFAULT 1;
        ALTER TABLE question_dna ADD COLUMN IF NOT EXISTS display_label TEXT NOT NULL DEFAULT '';
        ALTER TABLE question_dna ADD COLUMN IF NOT EXISTS superseded_by TEXT NULL;

        -- Rescue legacy positional IDs so they can never collide again.
        UPDATE question_dna
        SET display_label = CASE WHEN display_label = '' THEN question_id ELSE display_label END,
            question_id = 'q-legacy-'
                || lower(regexp_replace(question_id, '[^A-Za-z0-9]+', '-', 'g'))
                || '-'
                || substr(md5(random()::text || clock_timestamp()::text), 1, 10)
        WHERE question_id NOT LIKE 'q-%' AND length(question_id) < 40;

        -- Backfill the CBC progression ordinal from the stored grade slug.
        UPDATE question_dna SET grade_ordinal = CASE lower(curriculum_link->>'grade')
            WHEN 'grade-pp1' THEN 1  WHEN 'pp1' THEN 1
            WHEN 'grade-pp2' THEN 2  WHEN 'pp2' THEN 2
            WHEN 'grade-1'  THEN 3   WHEN '1'  THEN 3
            WHEN 'grade-2'  THEN 4   WHEN '2'  THEN 4
            WHEN 'grade-3'  THEN 5   WHEN '3'  THEN 5
            WHEN 'grade-4'  THEN 6   WHEN '4'  THEN 6
            WHEN 'grade-5'  THEN 7   WHEN '5'  THEN 7
            WHEN 'grade-6'  THEN 8   WHEN '6'  THEN 8
            WHEN 'grade-7'  THEN 9   WHEN '7'  THEN 9
            WHEN 'grade-8'  THEN 10  WHEN '8'  THEN 10
            WHEN 'grade-9'  THEN 11  WHEN '9'  THEN 11
            WHEN 'grade-10' THEN 12  WHEN '10' THEN 12
            WHEN 'grade-11' THEN 13  WHEN '11' THEN 13
            WHEN 'grade-12' THEN 14  WHEN '12' THEN 14
            WHEN 'grade-dte' THEN 15 WHEN 'dte' THEN 15
            ELSE 999 END;

        CREATE INDEX IF NOT EXISTS idx_question_dna_curriculum
            ON question_dna(grade_ordinal, (curriculum_link->>'subject'), (curriculum_link->>'sub_strand'));
        CREATE INDEX IF NOT EXISTS idx_question_dna_status ON question_dna(status);
        CREATE INDEX IF NOT EXISTS idx_question_dna_superseded ON question_dna(superseded_by);
        CREATE INDEX IF NOT EXISTS idx_question_dna_slo ON question_dna((curriculum_link->>'slo_id'));
        """,
    ),
    (
        "011_diagram_scene_documents",
        """
        -- A diagram was an opaque SVG string: no addressable parts, no layers, so
        -- "ask about part of this diagram" was not expressible. The scene document
        -- is the structured source of truth; SVG becomes a render target.

        ALTER TABLE diagram_registry ADD COLUMN IF NOT EXISTS scene_document JSONB NOT NULL DEFAULT '{}'::jsonb;
        ALTER TABLE diagram_registry ADD COLUMN IF NOT EXISTS semantic_key TEXT NULL;
        ALTER TABLE diagram_registry ADD COLUMN IF NOT EXISTS title TEXT NOT NULL DEFAULT '';
        ALTER TABLE diagram_registry ADD COLUMN IF NOT EXISTS grade TEXT NOT NULL DEFAULT '';
        ALTER TABLE diagram_registry ADD COLUMN IF NOT EXISTS subject TEXT NOT NULL DEFAULT '';
        ALTER TABLE diagram_registry ADD COLUMN IF NOT EXISTS svg_markup TEXT NOT NULL DEFAULT '';
        ALTER TABLE diagram_registry ADD COLUMN IF NOT EXISTS reuse_count INT NOT NULL DEFAULT 1;

        CREATE INDEX IF NOT EXISTS idx_diagram_registry_semantic ON diagram_registry(semantic_key);
        CREATE INDEX IF NOT EXISTS idx_diagram_registry_lookup ON diagram_registry(grade, subject);
        """,
    ),
    (
        "012_exam_composition",
        """
        -- Composed papers are frozen: an exam records the exact question versions
        -- it contains, so reprinting it next term yields the same paper.

        CREATE TABLE IF NOT EXISTS exams (
            exam_id TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT '',
            grade TEXT NOT NULL DEFAULT '',
            grade_ordinal INT NOT NULL DEFAULT 999,
            subject TEXT NOT NULL DEFAULT '',
            strand TEXT NOT NULL DEFAULT '',
            sub_strand TEXT NOT NULL DEFAULT '',
            time_allowed TEXT NOT NULL DEFAULT '',
            total_marks INT NOT NULL DEFAULT 0,
            instructions JSONB NOT NULL DEFAULT '[]'::jsonb,
            question_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
            snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_by TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS idx_exams_curriculum ON exams(grade_ordinal, subject);
        """,
    ),
    (
        "013_dataset_ingest_status",
        """
        -- Tracks each Langfuse dataset item from arrival to ingested design, so
        -- the same document is not processed twice and every screen agrees on
        -- what has been done.

        CREATE TABLE IF NOT EXISTS dataset_ingest_status (
            item_id TEXT PRIMARY KEY,
            grade TEXT NOT NULL,
            file_id TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            declared_subject TEXT NOT NULL DEFAULT '',
            resolved_subject TEXT NOT NULL DEFAULT '',
            design_id TEXT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            char_count INT NOT NULL DEFAULT 0,
            error TEXT NOT NULL DEFAULT '',
            selected_at TIMESTAMPTZ NULL,
            started_at TIMESTAMPTZ NULL,
            finished_at TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS idx_dataset_ingest_grade ON dataset_ingest_status(grade);
        CREATE INDEX IF NOT EXISTS idx_dataset_ingest_status ON dataset_ingest_status(status);
        CREATE INDEX IF NOT EXISTS idx_dataset_ingest_design ON dataset_ingest_status(design_id);
        """,
    ),
    (
        "014_dataset_ingest_grade_scoped",
        """
        -- One document can belong to several grades: KICD publishes a single
        -- Lower Primary design covering Grades 1-3. Tracking keyed on the
        -- Langfuse item id alone allowed only one row, so whichever grade
        -- synced first claimed the document and the others stayed empty.
        --
        -- item_id becomes a grade-scoped tracking id ("grade-2__<item>"), and
        -- source_item_id keeps the Langfuse id used to fetch the document.

        ALTER TABLE dataset_ingest_status
            ADD COLUMN IF NOT EXISTS source_item_id TEXT NOT NULL DEFAULT '';

        UPDATE dataset_ingest_status
            SET source_item_id = item_id
            WHERE source_item_id = '';

        CREATE INDEX IF NOT EXISTS idx_dataset_ingest_source
            ON dataset_ingest_status(source_item_id);
        """,
    ),
    (
        "015_substrand_theme_and_provenance",
        """
        -- Pre-Primary and Lower Primary organise the syllabus as
        -- THEME x STRAND -> SUB-STRAND: "1.1.1 Greetings and farewell" sits
        -- under strand "1.1 Listening and Speaking" AND theme "1.0 Greetings
        -- and Farewell". With only two levels to store, the generator collapsed
        -- themes into the sub-strand slot and reported six themes as four
        -- sub-strands, losing thirty-two of the thirty-six real ones.

        ALTER TABLE curriculum_substrands
            ADD COLUMN IF NOT EXISTS theme TEXT NOT NULL DEFAULT '';

        -- The design states these per sub-strand and they were being discarded,
        -- so every later stage had to re-read the PDF to recover them.
        ALTER TABLE curriculum_substrands
            ADD COLUMN IF NOT EXISTS pertinent_contemporary_issues JSONB NOT NULL DEFAULT '[]'::jsonb;

        ALTER TABLE curriculum_substrands
            ADD COLUMN IF NOT EXISTS link_to_other_learning_areas TEXT NOT NULL DEFAULT '';

        -- The BECF core principle requires every item to be traceable to its
        -- source. The pages a sub-strand was read from are that trace.
        ALTER TABLE curriculum_substrands
            ADD COLUMN IF NOT EXISTS source_pages JSONB NOT NULL DEFAULT '[]'::jsonb;

        CREATE INDEX IF NOT EXISTS idx_curriculum_substrands_theme
            ON curriculum_substrands(grade, subject, theme);
        """,
    ),
    (
        "016_grade_scope",
        """
        -- What a grade's design actually bounds: "letter sounds only", "nothing
        -- beyond 10", "30-minute lessons". PP1's was written by hand; the other
        -- fourteen grades are derived from their own designs by reading them in
        -- page-aligned chunks and reconciling the result.
        --
        -- Stored rather than recomputed: it is read on EVERY generation and
        -- derived once per design.

        CREATE TABLE IF NOT EXISTS grade_scope (
            id SERIAL PRIMARY KEY,
            grade TEXT NOT NULL,
            subject TEXT NOT NULL,
            design_id TEXT NOT NULL DEFAULT '',
            facts JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_grade_scope UNIQUE (grade, subject)
        );

        CREATE INDEX IF NOT EXISTS idx_grade_scope_lookup ON grade_scope(grade, subject);
        """,
    ),
    (
        "017_dataset_ingest_multi_design",
        """
        -- One Pre-Primary document now produces SEVEN designs, one per learning
        -- area. Tracking recorded a single design_id — the first area that
        -- succeeded — so re-processing with force discarded that one design and
        -- left the other six orphaned, then re-ingested all seven on top.
        --
        -- design_id is kept as the primary for every existing reader; design_ids
        -- records the full set the item produced.

        ALTER TABLE dataset_ingest_status
            ADD COLUMN IF NOT EXISTS design_ids JSONB NOT NULL DEFAULT '[]'::jsonb;

        -- An ingest that produced only some of a grade's learning areas is not
        -- the same as one that produced them all, and was being recorded as if
        -- it were.
        ALTER TABLE dataset_ingest_status
            ADD COLUMN IF NOT EXISTS learning_areas_missing JSONB NOT NULL DEFAULT '[]'::jsonb;

        UPDATE dataset_ingest_status
            SET design_ids = to_jsonb(ARRAY[design_id])
            WHERE design_id IS NOT NULL AND design_id <> ''
              AND design_ids = '[]'::jsonb;
        """,
    ),
    (
        "018_prompt_sync_and_repairs",
        """
        -- Prompt text is deployed code, and it drifted from the database the
        -- same way a schema does: a prompt gained {{ design_extract }} and
        -- {{ time_allocation }}, and every generation ran with those slots
        -- stripped until somebody remembered to press Seed. Recording the hash
        -- of what was pushed makes re-seeding a startup step, not a memory.
        CREATE TABLE IF NOT EXISTS prompt_versions (
            name TEXT PRIMARY KEY,
            content_hash TEXT NOT NULL,
            remote_version INTEGER,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        -- Schema migrations run once. A data repair is different: content keeps
        -- arriving, so a sweep that removes raw page debris has to keep running
        -- until every grade and subject is clean. This records each sweep's
        -- outcome so a repair that keeps finding rows is visible rather than
        -- quietly effective forever.
        CREATE TABLE IF NOT EXISTS data_repairs (
            repair_id TEXT PRIMARY KEY,
            runs INTEGER NOT NULL DEFAULT 0,
            rows_affected_total INTEGER NOT NULL DEFAULT 0,
            rows_affected_last INTEGER NOT NULL DEFAULT 0,
            last_detail JSONB NOT NULL DEFAULT '[]'::jsonb,
            first_run_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_run_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """,
    ),
    (
        "019_substrand_media",
        """
        -- Diagrams are SVG: generated as code, deterministic, editable. A photo
        -- and a video are neither. What the factory can author for them is the
        -- PROMPT and the shot list; the asset itself is produced elsewhere and
        -- uploaded back. Both live here so a sub-strand's visual plan is one
        -- list rather than three.
        CREATE TABLE IF NOT EXISTS substrand_media (
            media_id TEXT PRIMARY KEY,
            grade TEXT NOT NULL,
            subject TEXT NOT NULL,
            strand_name TEXT NOT NULL DEFAULT '',
            sub_strand_name TEXT NOT NULL DEFAULT '',
            kind TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            purpose TEXT NOT NULL DEFAULT '',
            generation_prompt TEXT NOT NULL DEFAULT '',
            negative_prompt TEXT NOT NULL DEFAULT '',
            shot_list JSONB NOT NULL DEFAULT '[]'::jsonb,
            spec JSONB NOT NULL DEFAULT '{}'::jsonb,
            alt_text TEXT NOT NULL DEFAULT '',
            narration TEXT NOT NULL DEFAULT '',
            storage_url TEXT NOT NULL DEFAULT '',
            content_type TEXT NOT NULL DEFAULT '',
            source_pages JSONB NOT NULL DEFAULT '[]'::jsonb,
            status TEXT NOT NULL DEFAULT 'planned',
            provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS idx_substrand_media_lookup
            ON substrand_media(grade, subject, sub_strand_name);
        CREATE INDEX IF NOT EXISTS idx_substrand_media_kind
            ON substrand_media(kind, status);
        """,
    ),
    (
        "020_artifact_registry",
        """
        -- Every generated thing — a strand, a set of notes, an hour module, a
        -- diagram, a photo prompt, a question — was overwritten in place by the
        -- next generation. There was no way to compare two attempts, to say
        -- which one is live, or to keep a good version while trying a better
        -- one. Prompts already work this way in Langfuse; content did not.
        --
        -- artifact_key is the natural identity (this sub-strand's notes);
        -- artifact_id is one version of it. A label points at exactly one
        -- version, so "approved" is unambiguous.
        CREATE TABLE IF NOT EXISTS artifacts (
            artifact_id TEXT PRIMARY KEY,
            artifact_key TEXT NOT NULL,
            kind TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            grade TEXT NOT NULL DEFAULT '',
            subject TEXT NOT NULL DEFAULT '',
            strand_name TEXT NOT NULL DEFAULT '',
            sub_strand_name TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            content JSONB NOT NULL DEFAULT '{}'::jsonb,
            content_hash TEXT NOT NULL DEFAULT '',
            parent_artifact_id TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'draft',
            provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_by TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_artifact_version UNIQUE (artifact_key, version)
        );

        CREATE INDEX IF NOT EXISTS idx_artifacts_key ON artifacts(artifact_key, version DESC);
        CREATE INDEX IF NOT EXISTS idx_artifacts_scope
            ON artifacts(grade, subject, kind);
        CREATE INDEX IF NOT EXISTS idx_artifacts_parent ON artifacts(parent_artifact_id);

        -- One label, one version. Moving a label is how a version goes live.
        CREATE TABLE IF NOT EXISTS artifact_labels (
            artifact_key TEXT NOT NULL,
            label TEXT NOT NULL,
            artifact_id TEXT NOT NULL,
            moved_by TEXT NOT NULL DEFAULT '',
            moved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (artifact_key, label)
        );

        CREATE INDEX IF NOT EXISTS idx_artifact_labels_id ON artifact_labels(artifact_id);
        """,
    ),
    (
        "021_artifact_reviews",
        """
        -- A single 90% told a reviewer nothing about WHAT was 90%. Content can
        -- be beautifully written and misaligned with the design, or exactly
        -- aligned and pitched at the wrong age. Each dimension is scored and
        -- evidenced separately, and the overall figure is derived from them
        -- rather than asserted.
        --
        -- Reviews are layered: the generator's own check, an independent model
        -- from a DIFFERENT vendor, then an approver. Storing the vendor and
        -- model on the row is what makes "reviewed by a second opinion"
        -- verifiable rather than claimed.
        CREATE TABLE IF NOT EXISTS artifact_reviews (
            review_id TEXT PRIMARY KEY,
            artifact_id TEXT NOT NULL,
            artifact_key TEXT NOT NULL,
            layer INTEGER NOT NULL,
            layer_name TEXT NOT NULL DEFAULT '',
            provider TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            verdict TEXT NOT NULL DEFAULT 'revise',
            overall_confidence INTEGER NOT NULL DEFAULT 0,
            dimensions JSONB NOT NULL DEFAULT '{}'::jsonb,
            issues JSONB NOT NULL DEFAULT '[]'::jsonb,
            comments JSONB NOT NULL DEFAULT '[]'::jsonb,
            compared_with TEXT NOT NULL DEFAULT '',
            diff_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
            reviewer TEXT NOT NULL DEFAULT '',
            usage JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS idx_artifact_reviews_artifact
            ON artifact_reviews(artifact_id, layer);
        CREATE INDEX IF NOT EXISTS idx_artifact_reviews_key
            ON artifact_reviews(artifact_key, created_at DESC);

        -- Free-text comments a person leaves on a version, independent of a
        -- model's review. A reviewer disagreeing with a 94% needs somewhere to
        -- say so that the next approver will actually read.
        CREATE TABLE IF NOT EXISTS artifact_comments (
            comment_id TEXT PRIMARY KEY,
            artifact_id TEXT NOT NULL,
            artifact_key TEXT NOT NULL,
            author TEXT NOT NULL DEFAULT '',
            body TEXT NOT NULL DEFAULT '',
            dimension TEXT NOT NULL DEFAULT '',
            resolved BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS idx_artifact_comments_artifact
            ON artifact_comments(artifact_id, created_at DESC);
        """,
    ),
    (
        "022_job_queue",
        """
        -- Generating a sub-strand's notes takes a minute; a grade's worth takes
        -- an afternoon. Held open on an HTTP request, each one blocks a browser
        -- tab, times out at the proxy, and loses everything on a refresh — so
        -- the work was done one item at a time with somebody watching.
        --
        -- Queued instead: the request records what to do and returns, a worker
        -- runs the jobs one at a time, and the console reads progress from this
        -- table. Sequential by design — these calls cost money and hit provider
        -- rate limits, and ten at once is how a run fails halfway with no way to
        -- tell which half.
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL DEFAULT '',
            kind TEXT NOT NULL,
            grade TEXT NOT NULL DEFAULT '',
            subject TEXT NOT NULL DEFAULT '',
            strand TEXT NOT NULL DEFAULT '',
            sub_strand TEXT NOT NULL DEFAULT '',
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            status TEXT NOT NULL DEFAULT 'queued',
            attempts INTEGER NOT NULL DEFAULT 0,
            result JSONB NOT NULL DEFAULT '{}'::jsonb,
            error TEXT NOT NULL DEFAULT '',
            queued_by TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ
        );

        CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, created_at);
        CREATE INDEX IF NOT EXISTS idx_jobs_batch ON jobs(batch_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_jobs_scope ON jobs(grade, subject, status);
        """,
    ),
    (
        "023_job_drafts",
        """
        -- Sub-strand generation is queued like everything else, but its result
        -- is a DRAFT: the operator reads it, then saves it, and saving one
        -- strand must not disturb the others. So the queue has to hold the
        -- generated sub-strands until somebody accepts or discards them.
        --
        -- Held in browser state instead, they were lost the moment the console
        -- re-rendered: generate all five strands, save the first, and the other
        -- four disappeared with no record they had ever existed.
        ALTER TABLE jobs ADD COLUMN IF NOT EXISTS consumed_at TIMESTAMPTZ;

        -- The drafts view reads exactly this: finished work nobody has accepted.
        CREATE INDEX IF NOT EXISTS idx_jobs_unconsumed
            ON jobs(grade, subject, kind, status)
            WHERE consumed_at IS NULL;
        """,
    ),
    (
        "024_auto_runs",
        """
        -- Unattended generation, with a floor it stops at.
        --
        -- Running a whole grade without watching is only safe if something is
        -- watching. Every item is scored against what its own validators
        -- checked, and the run halts when the recent average falls through the
        -- floor the operator set — so a pipeline that starts producing
        -- ungrounded content stops after a few sub-strands rather than after a
        -- grade.
        CREATE TABLE IF NOT EXISTS auto_runs (
            run_id TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL DEFAULT '',
            grade TEXT NOT NULL DEFAULT '',
            subjects JSONB NOT NULL DEFAULT '[]'::jsonb,
            floor NUMERIC NOT NULL DEFAULT 95,
            window_size INTEGER NOT NULL DEFAULT 5,
            status TEXT NOT NULL DEFAULT 'running',
            items_scored INTEGER NOT NULL DEFAULT 0,
            average NUMERIC NOT NULL DEFAULT 0,
            recent_average NUMERIC NOT NULL DEFAULT 0,
            mean_confidence NUMERIC NOT NULL DEFAULT 0,
            halted_reason TEXT NOT NULL DEFAULT '',
            -- Every item's score, so the operator can see WHICH sub-strand
            -- dragged the average down rather than only that it fell.
            items JSONB NOT NULL DEFAULT '[]'::jsonb,
            started_by TEXT NOT NULL DEFAULT '',
            started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            finished_at TIMESTAMPTZ
        );

        CREATE INDEX IF NOT EXISTS idx_auto_runs_batch ON auto_runs(batch_id);
        CREATE INDEX IF NOT EXISTS idx_auto_runs_status ON auto_runs(status, started_at DESC);
        """,
    ),
    (
        "025_job_cost",
        """
        -- What each job actually spent. Every model call already returned its
        -- token usage and the pricing table already existed; nothing was
        -- joining them to the job that made the call, so the only way to see
        -- the bill was to wait for it.
        ALTER TABLE jobs ADD COLUMN IF NOT EXISTS llm_calls INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE jobs ADD COLUMN IF NOT EXISTS total_tokens INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE jobs ADD COLUMN IF NOT EXISTS cost_usd NUMERIC(12,6) NOT NULL DEFAULT 0;
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


def _jsonable(value: Any) -> Any:
    """Convert one value json.dumps could not encode into something it can.

    Every JSONB write goes through to_json, and a plain json.dumps raises on
    anything that is not a primitive — so a single stray object aborts the
    request AFTER the expensive work is done. A three-layer review failed
    exactly this way: the model was called, the tokens were spent, the verdict
    was computed, and it was lost at the INSERT because `usage` held a
    TokenUsage dataclass rather than a dict.

    Known shapes are converted structurally; only a genuinely unknown type
    falls back to its string form, so nothing is silently flattened that could
    have been kept.
    """
    for attr in ("model_dump", "to_dict", "dict"):
        method = getattr(value, attr, None)
        if callable(method):
            try:
                return method()
            except Exception:  # noqa: BLE001, S112
                continue
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    if isinstance(value, (set, frozenset, tuple)):
        return list(value)
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", "replace")
    logger.debug("to_json fell back to str() for %s", type(value).__name__)
    return str(value)


def to_json(value: Any) -> str:
    return json.dumps(value, default=_jsonable)
