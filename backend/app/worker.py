from __future__ import annotations

import logging
import time

from .infra.db import run_migrations
from .infra.queue import job_queue
from .infra.storage import object_storage
from .services.pipeline import PipelineService
from .services.provider_router import ProviderRouter
from .services.targets import target_service
from .state import runtime_state

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("cbc-worker")


def main() -> None:
    try:
        run_migrations()
        runtime_state.sync_users_from_env()
        runtime_state.load_from_db()
    except Exception as exc:
        logger.warning("Worker database sync warning at startup: %s", exc)

    try:
        object_storage.ensure_bucket()
    except Exception as exc:  # noqa: BLE001
        logger.warning("MinIO bootstrap skipped at startup: %s", exc)

    router = ProviderRouter(runtime_state)
    pipeline = PipelineService(router)

    logger.info("CBC Worker started and listening for generation and regeneration jobs...")

    while True:
        job_id = job_queue.pop_job(timeout_seconds=5)
        if not job_id:
            continue

        try:
            job_queue.mark_running(job_id)
            payload = job_queue.get_payload(job_id)
            logger.info("Processing job %s for %s %s", job_id, payload.curriculum.grade, payload.curriculum.subject)

            result = pipeline.run(payload)
            runtime_state.save_pipeline_run(result.run_id, payload.model_dump(), result.model_dump())
            job_queue.mark_done(job_id, result.model_dump())

            # Update daily target tracker
            is_approved = result.published_bundle.get("status") == "published"
            target_service.record_generation(payload.curriculum.grade, is_approved=is_approved)

            logger.info("✓ Job %s completed successfully (Run ID: %s)", job_id, result.run_id)
        except Exception as exc:  # noqa: BLE001
            job_queue.mark_failed(job_id, str(exc))
            logger.exception("✗ Job %s failed with exception: %s", job_id, exc)


if __name__ == "__main__":
    main()
