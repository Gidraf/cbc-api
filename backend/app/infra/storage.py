from __future__ import annotations

from minio import Minio
from minio.error import S3Error

from ..settings import settings


class ObjectStorage:
    def __init__(self) -> None:
        self._client = Minio(
            endpoint=settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )

    def ensure_bucket(self) -> None:
        found = self._client.bucket_exists(settings.minio_bucket)
        if not found:
            self._client.make_bucket(settings.minio_bucket)

    def save_svg(self, object_name: str, svg: str) -> str:
        from io import BytesIO

        payload = svg.encode("utf-8")
        self._client.put_object(
            bucket_name=settings.minio_bucket,
            object_name=object_name,
            data=BytesIO(payload),
            length=len(payload),
            content_type="image/svg+xml",
        )
        return f"{settings.minio_public_base_url}/{settings.minio_bucket}/{object_name}"


object_storage = ObjectStorage()
