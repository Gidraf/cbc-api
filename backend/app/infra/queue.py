from __future__ import annotations

import json
import uuid

import redis

from ..models import GenerateRequest
from ..settings import settings


class JobQueue:
    def __init__(self) -> None:
        self._redis = redis.Redis.from_url(settings.redis_url, decode_responses=True)

    def ping(self) -> bool:
        return bool(self._redis.ping())

    def enqueue_generation(self, payload: GenerateRequest) -> str:
        job_id = f"job_{uuid.uuid4().hex}"
        meta_key = self._job_meta_key(job_id)

        self._redis.hset(
            meta_key,
            mapping={
                "status": "queued",
                "request_id": payload.request_id,
                "trace_id": payload.trace_id,
                "payload": payload.model_dump_json(),
            },
        )
        self._redis.expire(meta_key, settings.result_ttl_seconds)
        self._redis.lpush(settings.queue_name, job_id)
        return job_id

    def pop_job(self, timeout_seconds: int = 5) -> str | None:
        result = self._redis.brpop(settings.queue_name, timeout=timeout_seconds)
        if not result:
            return None
        _, job_id = result
        return job_id

    def get_payload(self, job_id: str) -> GenerateRequest:
        raw = self._redis.hget(self._job_meta_key(job_id), "payload")
        if not raw:
            raise KeyError(f"Job payload not found for {job_id}")
        data = json.loads(raw)
        return GenerateRequest.model_validate(data)

    def mark_running(self, job_id: str) -> None:
        self._redis.hset(self._job_meta_key(job_id), mapping={"status": "running"})

    def mark_done(self, job_id: str, result: dict) -> None:
        self._redis.hset(
            self._job_meta_key(job_id),
            mapping={"status": "done", "result": json.dumps(result)},
        )

    def mark_failed(self, job_id: str, error: str) -> None:
        self._redis.hset(
            self._job_meta_key(job_id),
            mapping={"status": "failed", "error": error},
        )

    def get_job(self, job_id: str) -> dict:
        data = self._redis.hgetall(self._job_meta_key(job_id))
        if not data:
            return {"job_id": job_id, "status": "not_found"}

        result = {
            "job_id": job_id,
            "status": data.get("status", "unknown"),
            "request_id": data.get("request_id"),
            "trace_id": data.get("trace_id"),
        }
        if "result" in data:
            result["result"] = json.loads(data["result"])
        if "error" in data:
            result["error"] = data["error"]
        return result

    @staticmethod
    def _job_meta_key(job_id: str) -> str:
        return f"generation_job:{job_id}"


job_queue = JobQueue()
