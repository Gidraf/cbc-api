from __future__ import annotations

import json
import logging
from io import BytesIO
from typing import Any

from minio import Minio

from ..settings import settings

logger = logging.getLogger("cbc-storage")


class ObjectStorage:
    def __init__(self) -> None:
        self._client: Minio | None = None
        self._bucket_ensured = False

    def _get_client(self) -> Minio:
        if self._client is None:
            self._client = Minio(
                endpoint=settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=settings.minio_secure,
            )
        return self._client

    def ensure_bucket(self) -> bool:
        if self._bucket_ensured:
            return True
        try:
            client = self._get_client()
            found = client.bucket_exists(settings.minio_bucket)
            if not found:
                client.make_bucket(settings.minio_bucket)
            self._bucket_ensured = True
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("MinIO bucket '%s' check/creation failed: %s", settings.minio_bucket, exc)
            return False

    def save_svg(self, object_name: str, svg: str) -> str:
        """Stores standalone vector SVG to MinIO bucket."""
        try:
            self.ensure_bucket()
            payload = svg.encode("utf-8")
            self._get_client().put_object(
                bucket_name=settings.minio_bucket,
                object_name=object_name,
                data=BytesIO(payload),
                length=len(payload),
                content_type="image/svg+xml",
            )
            return public_object_url(object_name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("MinIO save_svg failed for '%s': %s", object_name, exc)
            return f"local://{settings.minio_bucket}/{object_name}"

    def object_name_of(self, url: str) -> str:
        """The object a stored URL points at.

        A saved URL is `{public_base}/{bucket}/{object}`, and a save that could
        not reach MinIO returns `local://{bucket}/{object}` instead — both end
        with the bucket followed by the object path, so both are read the same
        way rather than one of them being an unhandled shape later.
        """
        if not url:
            return ""
        marker = f"/{settings.minio_bucket}/"
        index = url.find(marker)
        if index != -1:
            return url[index + len(marker):]
        # A video moved to Google Drive is linked there; its object is the
        # one the move recorded.
        from ..services import drive_store

        return drive_store.object_name_of(url)

    def read_text(self, object_name: str) -> str:
        """One stored object, as text. Empty when it is not there.

        Returns "" rather than raising: the caller is usually rendering a page
        that has other diagrams on it, and one missing object should leave a
        gap rather than fail the whole render.
        """
        if not object_name:
            return ""
        response = None
        try:
            response = self._get_client().get_object(settings.minio_bucket, object_name)
            return response.read().decode("utf-8")
        except Exception as exc:  # noqa: BLE001
            logger.warning("MinIO read failed for '%s': %s", object_name, exc)
            return ""
        finally:
            if response is not None:
                response.close()
                response.release_conn()

    def read_bytes(self, object_name: str) -> bytes:
        """One stored object as it was saved. Empty when it is not there —
        unless it was moved to Google Drive, when it is fetched from there."""
        if not object_name:
            return b""
        response = None
        try:
            response = self._get_client().get_object(settings.minio_bucket, object_name)
            return response.read()
        except Exception as exc:  # noqa: BLE001
            moved = self._from_drive(object_name)
            if moved:
                return moved
            logger.warning("MinIO read failed for '%s': %s", object_name, exc)
            return b""
        finally:
            if response is not None:
                response.close()
                response.release_conn()

    @staticmethod
    def _from_drive(object_name: str) -> bytes:
        from ..services import drive_store

        row = drive_store.record(object_name)
        if not row or not drive_store.configured():
            return b""
        try:
            return drive_store.Drive().download(str(row["file_id"]))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Drive read failed for '%s': %s", object_name, exc)
            return b""

    def save_bytes(self, object_name: str, payload: bytes, content_type: str) -> str:
        """Store an uploaded photograph or video exactly as it arrived.

        Unlike an SVG, a photo or a video is opaque to us: it is not generated
        as code and cannot be re-derived, so it is stored byte-for-byte and the
        caller keeps the URL.
        """
        try:
            self.ensure_bucket()
            self._get_client().put_object(
                bucket_name=settings.minio_bucket,
                object_name=object_name,
                data=BytesIO(payload),
                length=len(payload),
                content_type=content_type or "application/octet-stream",
            )
            return public_object_url(object_name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("MinIO save_bytes failed for '%s': %s", object_name, exc)
            return f"local://{settings.minio_bucket}/{object_name}"

    def save_json(self, object_name: str, data: Any) -> str:
        """Stores structured JSON payload to MinIO bucket."""
        try:
            self.ensure_bucket()
            payload = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
            self._get_client().put_object(
                bucket_name=settings.minio_bucket,
                object_name=object_name,
                data=BytesIO(payload),
                length=len(payload),
                content_type="application/json; charset=utf-8",
            )
            return public_object_url(object_name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("MinIO save_json failed for '%s': %s", object_name, exc)
            return f"local://{settings.minio_bucket}/{object_name}"

    def save_text(self, object_name: str, text: str, content_type: str = "text/plain; charset=utf-8") -> str:
        """Stores arbitrary text / markdown to MinIO bucket."""
        try:
            self.ensure_bucket()
            payload = text.encode("utf-8")
            self._get_client().put_object(
                bucket_name=settings.minio_bucket,
                object_name=object_name,
                data=BytesIO(payload),
                length=len(payload),
                content_type=content_type,
            )
            return public_object_url(object_name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("MinIO save_text failed for '%s': %s", object_name, exc)
            return f"local://{settings.minio_bucket}/{object_name}"

    def save_notes_bundle(self, bundle_id: str, notes_data: dict[str, Any]) -> str:
        return self.save_json(f"notes/{bundle_id}_notes.json", notes_data)

    def save_activities_bundle(self, bundle_id: str, activities_data: Any) -> str:
        return self.save_json(f"activities/{bundle_id}_activities.json", activities_data)

    def save_questions_bundle(self, bundle_id: str, questions_data: list[Any]) -> str:
        return self.save_json(f"questions/{bundle_id}_questions.json", questions_data)

    def save_full_bundle(self, bundle_id: str, bundle_payload: dict[str, Any]) -> str:
        return self.save_json(f"bundles/{bundle_id}_published.json", bundle_payload)

    def save_dna_certificate(self, dna_id: str, cert_payload: dict[str, Any]) -> str:
        return self.save_json(f"dna/{dna_id}.json", cert_payload)

    def remove_object(self, object_name: str) -> bool:
        """Delete one stored object.

        Deleting a drawing removed its row and left the SVG in the bucket, so
        the storage filled with drawings nothing referred to and a redraw of
        the same figure could not reuse its object name cleanly.

        A missing object counts as removed: the caller wants it gone, and it
        is gone.
        """
        if not object_name:
            return False
        try:
            self._get_client().remove_object(settings.minio_bucket, object_name)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("MinIO remove failed for '%s': %s", object_name, exc)
            return False

    def object_exists(self, object_name: str) -> bool:
        try:
            self.ensure_bucket()
            self._get_client().stat_object(settings.minio_bucket, object_name)
            return True
        except Exception:  # noqa: BLE001
            # Moved to Google Drive is still made: a video whose server copy
            # was removed must not be rendered again.
            from ..services import drive_store

            return drive_store.record(object_name) is not None


def legacy_asset_base() -> str:
    """Where stored links used to point: MinIO's own address."""
    return f"{settings.minio_public_base_url.rstrip('/')}/{settings.minio_bucket}"


def asset_base() -> str:
    """Where a stored file is linked: the platform's public address, through
    /api/v1/assets — not MinIO's IP and port. Falls back to MinIO's address
    only while no public address is set."""
    try:
        from ..services.platform_settings import get

        public = str(get("public_base_url") or "").rstrip("/")
    except Exception:  # noqa: BLE001
        public = ""
    if public:
        return f"{public}/api/v1/assets/{settings.minio_bucket}"
    return legacy_asset_base()


def public_object_url(object_name: str) -> str:
    # A video moved to Google Drive is linked there.
    from ..services import drive_store

    moved = drive_store.record(object_name)
    if moved and moved.get("url"):
        return str(moved["url"])
    return f"{asset_base()}/{object_name}"


object_storage = ObjectStorage()

