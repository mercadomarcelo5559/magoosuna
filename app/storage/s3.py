"""Backend S3 / Cloudflare R2 (producción).

Funciona con cualquier servicio compatible con S3:
  * Amazon S3      → S3_REGION=us-east-1, sin S3_ENDPOINT_URL
  * Cloudflare R2  → S3_ENDPOINT_URL=https://<account>.r2.cloudflarestorage.com
                     S3_REGION=auto
  * MinIO / Backblaze → S3_ENDPOINT_URL correspondiente
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from typing import IO, TYPE_CHECKING, Any

from app.config import settings
from app.storage.base import StorageBackend, StoredObject

if TYPE_CHECKING:  # pragma: no cover
    from mypy_boto3_s3.client import S3Client


class S3Storage(StorageBackend):
    name = "s3"

    def __init__(self) -> None:
        if not settings.s3_bucket:
            raise RuntimeError("STORAGE_BACKEND=s3 requiere S3_BUCKET")
        self.bucket = settings.s3_bucket
        self._client: Any = None

    @property
    def client(self) -> S3Client:
        if self._client is None:
            import boto3
            from botocore.config import Config

            self._client = boto3.client(
                "s3",
                region_name=settings.s3_region or None,
                endpoint_url=settings.s3_endpoint_url or None,
                aws_access_key_id=settings.s3_access_key_id or None,
                aws_secret_access_key=settings.s3_secret_access_key or None,
                config=Config(
                    s3={"addressing_style": settings.s3_addressing_style},
                    retries={"max_attempts": 3, "mode": "standard"},
                ),
            )
        return self._client

    def save(self, key: str, stream: IO[bytes], *, content_type: str) -> StoredObject:
        """Sube con multipart automático y calcula el SHA-256 al vuelo."""
        digest = hashlib.sha256()
        size = 0

        class _Counting:
            """Envuelve el stream para hashear/medir sin cargarlo en memoria."""

            def read(self, amount: int = -1) -> bytes:
                nonlocal size
                chunk = stream.read(amount)
                if chunk:
                    digest.update(chunk)
                    size += len(chunk)
                return chunk

        from boto3.s3.transfer import TransferConfig

        self.client.upload_fileobj(
            _Counting(),
            self.bucket,
            key,
            ExtraArgs={"ContentType": content_type},
            Config=TransferConfig(multipart_threshold=16 * 1024 * 1024),
        )
        return StoredObject(
            key=key, size_bytes=size, checksum_sha256=digest.hexdigest(), content_type=content_type
        )

    def open_stream(self, key: str, *, chunk_size: int) -> Iterator[bytes]:
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        body = response["Body"]
        try:
            while True:
                chunk = body.read(chunk_size)
                if not chunk:
                    return
                yield chunk
        finally:
            body.close()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False

    def size(self, key: str) -> int:
        return int(self.client.head_object(Bucket=self.bucket, Key=key)["ContentLength"])

    def public_url(self, key: str) -> str | None:
        """URL pública si el bucket tiene dominio público configurado."""
        if settings.s3_public_base_url:
            return f"{settings.s3_public_base_url}/{key}"
        return None

    def presigned_url(self, key: str, *, expires_in: int = 3600) -> str:
        """URL firmada temporal — útil para pasar el video a Instagram/TikTok."""
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_in,
        )
