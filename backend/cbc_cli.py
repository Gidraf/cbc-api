#!/usr/bin/env python3
from __future__ import annotations

import json
import secrets
import sys
from datetime import date
from pathlib import Path

import click

# Add parent directory to path so imports work seamlessly
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.infra.db import execute, fetch_one, run_migrations
from app.models import Actor, Controls, Curriculum, GenerateRequest
from app.services.auth import hash_password
from app.services.langfuse_context import langfuse_context_service
from app.services.pipeline import PipelineService
from app.services.provider_router import ProviderRouter
from app.services.targets import target_service
from app.services.validation import validate_grade_dataset
from app.state import runtime_state


@click.group()
def cli():
    """CBC API Platform Command Line Interface."""
    pass


@cli.command("reset-admin-password")
@click.option("--username", default="admin", help="Admin username to reset")
@click.option("--password", default=None, help="New password (generates random if omitted)")
def reset_admin_password(username: str, password: str | None):
    """Resets the password for an admin account directly in PostgreSQL."""
    run_migrations()
    new_pwd = password or secrets.token_urlsafe(12)
    pwd_hash = hash_password(new_pwd)

    execute(
        """
        INSERT INTO app_users (username, password_plain, password_hash, role, is_active, updated_at)
        VALUES (:uname, '', :phash, 'admin', TRUE, NOW())
        ON CONFLICT (username) DO UPDATE SET
            password_hash = EXCLUDED.password_hash,
            role = 'admin',
            is_active = TRUE,
            updated_at = NOW()
        """,
        {"uname": username, "phash": pwd_hash},
    )

    click.secho(f"✓ Password successfully reset for user '{username}':", fg="green", bold=True)
    click.secho(f"  Password: {new_pwd}", fg="yellow", bold=True)


@cli.group("langfuse")
def langfuse_group():
    """Manage Langfuse curriculum datasets and prompts."""
    pass


@langfuse_group.command("list-datasets")
def list_datasets():
    """Lists all grade datasets in Langfuse."""
    datasets = langfuse_context_service.list_datasets()
    click.secho("Available Grade Datasets:", fg="cyan", bold=True)
    for ds in datasets:
        click.echo(f" - {ds.get('name')}")


@langfuse_group.command("show-grade")
@click.option("--grade", required=True, help="Grade number or slug, e.g. 7 or pp1")
def show_grade(grade: str):
    """Shows all subject context items for a specific grade dataset."""
    grade_slug = validate_grade_dataset(grade)
    items = langfuse_context_service.get_grade_dataset(grade_slug)
    click.secho(f"Dataset items for {grade_slug}:", fg="cyan", bold=True)
    click.echo(json.dumps(items, indent=2))


@langfuse_group.command("show-subject")
@click.option("--grade", required=True, help="Grade number or slug")
@click.option("--subject", required=True, help="Subject name, e.g. 'Integrated Science'")
def show_subject(grade: str, subject: str):
    """Displays the full curriculum context for a subject."""
    grade_slug = validate_grade_dataset(grade)
    ctx = langfuse_context_service.get_subject_context(grade_slug, subject)
    click.secho(f"Context for {grade_slug} - {subject}:", fg="cyan", bold=True)
    click.echo(json.dumps(ctx, indent=2))


@langfuse_group.command("upload-context")
@click.option("--grade", required=True, help="Grade number or slug")
@click.option("--subject", required=True, help="Subject name")
@click.option("--file", "file_path", required=True, type=click.Path(exists=True), help="Path to JSON curriculum file")
def upload_context(grade: str, subject: str, file_path: str):
    """Uploads a subject curriculum context item into the grade dataset."""
    grade_slug = validate_grade_dataset(grade)
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    data["subject"] = subject
    res = langfuse_context_service.upload_dataset_item(grade_slug, data)
    click.secho(f"✓ Context uploaded for {grade_slug} - {subject}:", fg="green")
    click.echo(json.dumps(res, indent=2))


@cli.command("generate")
@click.option("--grade", required=True, help="Grade number or slug, e.g. 7")
@click.option("--subject", required=True, help="Subject name, e.g. 'Integrated Science'")
@click.option("--strand", required=True, help="Strand name, e.g. 'Matter'")
@click.option("--substrand", required=True, help="Sub-strand name, e.g. 'Classification of Matter'")
@click.option("--slo-id", default=None, help="Optional SLO ID")
def generate_content(grade: str, subject: str, strand: str, substrand: str, slo_id: str | None):
    """Triggers content generation for a specific sub-strand."""
    run_migrations()
    runtime_state.load_from_db()
    router = ProviderRouter(runtime_state)
    pipeline = PipelineService(router)

    actual_slo = slo_id or f"SLO-{grade}-{subject[:4].upper()}-{strand[:3].upper()}-01"
    request_payload = GenerateRequest(
        request_id=f"req_cli_{secrets.token_hex(4)}",
        trace_id=f"trc_cli_{secrets.token_hex(4)}",
        tenant_id="cbc_cli",
        actor=Actor(type="admin", id="usr_cli_admin"),
        curriculum=Curriculum(
            level="Middle School",
            grade=grade,
            subject=subject,
            subject_code=subject[:4].upper(),
            strand=strand,
            sub_strand=substrand,
            slo_id=actual_slo,
        ),
        controls=Controls(
            idempotency_key=f"idem_cli_{secrets.token_hex(4)}",
            deadline_ms=120000,
            max_regen_attempts=2,
            environment="prod",
        ),
    )

    click.secho(f"Starting generation for {grade} {subject} -> {strand} -> {substrand}...", fg="cyan")
    result = pipeline.run(request_payload)
    click.secho(f"✓ Generation complete! Run ID: {result.run_id}", fg="green", bold=True)
    click.echo(json.dumps(result.published_bundle, indent=2))


@cli.group("targets")
def targets_group():
    """View and configure daily production targets."""
    pass


@targets_group.command("status")
@click.option("--date", "target_date_str", default="today", help="Date in YYYY-MM-DD or 'today'")
def target_status(target_date_str: str):
    """Displays target progress and milestone achievements."""
    run_migrations()
    tdate = date.today() if target_date_str == "today" else date.fromisoformat(target_date_str)
    status = target_service.get_or_create_daily_target(tdate)

    target_cnt = status.get("target_count", 100)
    completed_cnt = status.get("completed_count", 0)
    pct = round((completed_cnt / target_cnt) * 100.0, 1) if target_cnt > 0 else 0.0

    click.secho(f"Generation Targets Status for {status.get('target_date')}:", fg="cyan", bold=True)
    click.echo(f"  Target Items:    {target_cnt}")
    click.echo(f"  Completed Items: {completed_cnt} ({pct}%)")
    click.echo(f"  Approved:        {status.get('approved_count', 0)}")
    click.echo(f"  Rejected:        {status.get('rejected_count', 0)}")


if __name__ == "__main__":
    cli()
