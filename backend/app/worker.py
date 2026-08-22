from __future__ import annotations

import logging

from .infra.db import run_migrations
from .infra.queue import job_queue
from .infra.storage import object_storage
from .services.pipeline import PipelineService
from .services.provider_router import ProviderRouter
from .state import runtime_state

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("cbc-worker")


def main() -> None:
    run_migrations()
    runtime_state.sync_users_from_env()
    runtime_state.load_from_db()
    object_storage.ensure_bucket()
    router = ProviderRouter(runtime_state)
    pipeline = PipelineService(router)

    logger.info("Worker started and waiting for jobs")
    while True:
        job_id = job_queue.pop_job(timeout_seconds=5)
        if not job_id:
            continue

        try:
            job_queue.mark_running(job_id)
            payload = job_queue.get_payload(job_id)
            result = pipeline.run(payload)
            runtime_state.save_pipeline_run(result.run_id, payload.model_dump(), result.model_dump())
            job_queue.mark_done(job_id, result.model_dump())
            logger.info("Job %s completed", job_id)
        except Exception as exc:  # noqa: BLE001
            job_queue.mark_failed(job_id, str(exc))
            logger.exception("Job %s failed", job_id)


if __name__ == "__main__":
    main()
