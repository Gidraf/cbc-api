from __future__ import annotations

import json
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from ..settings import settings


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
    )
]


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required for Postgres persistence")
    return create_engine(settings.database_url, pool_pre_ping=True)


def run_migrations() -> None:
    engine = get_engine()
    with engine.begin() as conn:
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

        rows = conn.execute(text("SELECT version FROM schema_migrations")).mappings().all()
        applied = {row["version"] for row in rows}

        for version, sql_script in MIGRATIONS:
            if version in applied:
                continue
            conn.execute(text(sql_script))
            conn.execute(text("INSERT INTO schema_migrations (version) VALUES (:version)"), {"version": version})


def fetch_all(query: str, params: dict | None = None) -> list[dict]:
    engine = get_engine()
    with engine.begin() as conn:
        rows = conn.execute(text(query), params or {}).mappings().all()
        return [dict(row) for row in rows]


def fetch_one(query: str, params: dict | None = None) -> dict | None:
    result = fetch_all(query, params)
    return result[0] if result else None


def execute(query: str, params: dict | None = None) -> None:
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text(query), params or {})


def to_json(value: dict | list) -> str:
    return json.dumps(value)
