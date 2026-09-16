"""Servicio de media: ingesta (upload / URL), URLs firmadas y limpieza."""

from __future__ import annotations

import hashlib
import tempfile
from collections.abc import Iterator
from datetime import timedelta
from typing import BinaryIO

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.logging_config import get_logger
from app.models import MediaAsset, MediaSource, MediaStatus, utcnow
from app.models.base import as_utc, new_uuid
from app.providers.base import VideoSource
from app.security.crypto import sign_payload, verify_signature
from app.storage import get_storage
from app.utils.video import VideoValidationError, validate_video

logger = get_logger(__name__)


class MediaNotFoundError(LookupError):
    pass


class MediaUnavailableError(RuntimeError):
    """El fichero ya se borró o no está accesible."""


def _storage_key(asset_id: str, filename: str) -> str:
    """Clave del objeto: prefijada por fecha para facilitar limpiezas masivas."""
    day = utcnow().strftime("%Y/%m/%d")
    return f"videos/{day}/{asset_id}/{filename}"


def _retention_expiry() -> object:
    return utcnow() + timedelta(hours=settings.media_retention_hours)


def create_asset_from_upload(
    db: Session,
    *,
    client_id: str,
    filename: str | None,
    content_type: str | None,
    stream: BinaryIO,
) -> MediaAsset:
    """Valida y guarda un video subido como multipart/form-data."""
    header = stream.read(32)
    stream.seek(0)
    validated = validate_video(
        filename=filename, declared_content_type=content_type, header_bytes=header
    )

    asset_id = new_uuid()
    key = _storage_key(asset_id, validated.filename)
    storage = get_storage()
    stored = storage.save(key, stream, content_type=validated.content_type)

    # El tamaño real sólo se conoce tras escribir: validamos aquí también.
    if stored.size_bytes > settings.max_video_size_bytes:
        storage.delete(key)
        raise VideoValidationError(
            f"El video pesa {stored.size_bytes / 1024 / 1024:.1f} MB y el máximo "
            f"es {settings.max_video_size_mb} MB"
        )
    if stored.size_bytes == 0:
        storage.delete(key)
        raise VideoValidationError("El video está vacío", field="file")

    asset = MediaAsset(
        id=asset_id,
        client_id=client_id,
        source=MediaSource.UPLOAD,
        status=MediaStatus.READY,
        filename=validated.filename,
        content_type=validated.content_type,
        size_bytes=stored.size_bytes,
        checksum_sha256=stored.checksum_sha256,
        storage_backend=storage.name,
        storage_key=key,
        expires_at=_retention_expiry(),
        asset_metadata={},
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    logger.info(
        "media: subida aceptada asset_id=%s bytes=%s type=%s",
        asset.id,
        asset.size_bytes,
        asset.content_type,
    )
    return asset


def create_asset_from_url(
    db: Session, *, client_id: str, url: str, download: bool = True
) -> MediaAsset:
    """Registra un video a partir de una URL pública.

    Si `download` es True (recomendado) se descarga y valida el fichero; así
    podemos subirlo a YouTube (que no acepta URLs) y verificar tamaño/MIME.
    """
    if not url.lower().startswith(("http://", "https://")):
        raise VideoValidationError("La URL del video debe ser http(s)", field="video_url")

    filename = url.split("?")[0].rstrip("/").split("/")[-1] or "video.mp4"

    if not download:
        validated = validate_video(filename=filename, declared_content_type=None)
        asset = MediaAsset(
            client_id=client_id,
            source=MediaSource.URL,
            status=MediaStatus.READY,
            filename=validated.filename,
            content_type=validated.content_type,
            size_bytes=0,
            source_url=url,
            expires_at=_retention_expiry(),
            asset_metadata={"downloaded": False},
        )
        db.add(asset)
        db.commit()
        db.refresh(asset)
        return asset

    with tempfile.NamedTemporaryFile(suffix=".download") as tmp:
        digest = hashlib.sha256()
        size = 0
        declared_type: str | None = None
        header = b""
        try:
            with (
                httpx.Client(
                    timeout=httpx.Timeout(settings.upload_timeout_seconds),
                    follow_redirects=True,
                ) as client,
                client.stream("GET", url) as response,
            ):
                if response.status_code >= 400:
                    raise VideoValidationError(
                        f"No se pudo descargar el video ({response.status_code})",
                        field="video_url",
                    )
                declared_type = response.headers.get("content-type")
                declared_length = response.headers.get("content-length")
                if declared_length and int(declared_length) > settings.max_video_size_bytes:
                    raise VideoValidationError(
                        f"El video remoto pesa más de {settings.max_video_size_mb} MB",
                        field="video_url",
                    )
                for chunk in response.iter_bytes(settings.stream_chunk_size):
                    if not header:
                        header = chunk[:32]
                    size += len(chunk)
                    if size > settings.max_video_size_bytes:
                        raise VideoValidationError(
                            f"El video remoto supera {settings.max_video_size_mb} MB",
                            field="video_url",
                        )
                    digest.update(chunk)
                    tmp.write(chunk)
        except httpx.HTTPError as exc:
            raise VideoValidationError(
                f"Error descargando el video: {exc}", field="video_url"
            ) from exc

        validated = validate_video(
            filename=filename,
            declared_content_type=declared_type,
            header_bytes=header,
            size_bytes=size,
        )
        tmp.flush()
        tmp.seek(0)

        asset_id = new_uuid()
        key = _storage_key(asset_id, validated.filename)
        storage = get_storage()
        stored = storage.save(key, tmp, content_type=validated.content_type)

    asset = MediaAsset(
        id=asset_id,
        client_id=client_id,
        source=MediaSource.URL,
        status=MediaStatus.READY,
        filename=validated.filename,
        content_type=validated.content_type,
        size_bytes=stored.size_bytes,
        checksum_sha256=stored.checksum_sha256,
        storage_backend=storage.name,
        storage_key=key,
        source_url=url,
        expires_at=_retention_expiry(),
        asset_metadata={"downloaded": True},
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    logger.info("media: URL descargada asset_id=%s bytes=%s", asset.id, asset.size_bytes)
    return asset


def get_asset(db: Session, client_id: str, asset_id: str) -> MediaAsset:
    asset = db.scalars(
        select(MediaAsset).where(MediaAsset.id == asset_id, MediaAsset.client_id == client_id)
    ).first()
    if asset is None:
        raise MediaNotFoundError(f"No existe el media asset {asset_id}")
    return asset


# ------------------------------------------------------------- URLs firmadas
def build_signed_download_url(asset: MediaAsset) -> str | None:
    """URL temporal firmada para que la plataforma descargue el video.

    Necesaria porque Instagram exige `video_url` pública. Requiere que
    `PUBLIC_BASE_URL` sea alcanzable desde Internet (en Codespaces: puerto
    8000 en modo *public*, o un Cloudflare Tunnel).
    """
    if not asset.storage_key:
        return asset.source_url

    storage = get_storage()
    # Si el bucket ya es público (R2/S3 con dominio), usamos esa URL directa.
    public = storage.public_url(asset.storage_key)
    if public:
        return public
    if storage.name == "s3":
        from app.storage.s3 import S3Storage

        if isinstance(storage, S3Storage):
            return storage.presigned_url(
                asset.storage_key, expires_in=settings.media_url_ttl_minutes * 60
            )

    if not settings.public_base_url:
        return None
    token = sign_payload(f"media:{asset.id}", settings.media_url_ttl_minutes * 60)
    return (
        f"{settings.public_base_url}{settings.api_prefix}/media/{asset.id}/download?token={token}"
    )


def verify_download_token(asset_id: str, token: str) -> bool:
    return verify_signature(f"media:{asset_id}", token)


def public_url_is_reachable() -> bool:
    """True si `PUBLIC_BASE_URL` parece accesible desde Internet."""
    base = settings.public_base_url.lower()
    if not base.startswith("https://"):
        return False
    loopback = ("localhost", "127.0.0.1", "0.0.0.0")  # noqa: S104 - sólo se comparan
    return not any(host in base for host in loopback)


# ------------------------------------------------------- fuente para provider
def build_video_source(asset: MediaAsset, *, require_public_url: bool = False) -> VideoSource:
    """Convierte un `MediaAsset` en el `VideoSource` que consume el provider."""
    storage = get_storage()
    public_url: str | None = None

    if asset.storage_key:
        if require_public_url or public_url_is_reachable() or storage.name == "s3":
            public_url = build_signed_download_url(asset)
    elif asset.source_url:
        public_url = asset.source_url

    local_path: str | None = None
    open_stream = None
    if asset.storage_key:
        if not storage.exists(asset.storage_key):
            raise MediaUnavailableError(
                f"El fichero del media asset {asset.id} ya no está disponible "
                "(pudo borrarse por retención). Vuelve a subirlo."
            )
        local_path = storage.local_path(asset.storage_key)
        if local_path is None:
            key = asset.storage_key

            def open_stream() -> Iterator[bytes]:  # type: ignore[misc]
                return storage.open_stream(key, chunk_size=settings.stream_chunk_size)

    size = asset.size_bytes
    if not size and asset.storage_key:
        size = storage.size(asset.storage_key)

    return VideoSource(
        filename=asset.filename,
        content_type=asset.content_type,
        size_bytes=size,
        public_url=public_url,
        open_stream=open_stream,
        local_path=local_path,
    )


# --------------------------------------------------------------- retención
def delete_asset_file(db: Session, asset: MediaAsset) -> None:
    """Borra el fichero del almacenamiento y marca el asset como eliminado."""
    if asset.storage_key:
        try:
            get_storage().delete(asset.storage_key)
        except Exception as exc:
            logger.warning("media: no se pudo borrar %s: %s", asset.storage_key, exc)
    asset.status = MediaStatus.DELETED
    asset.deleted_at = utcnow()
    db.add(asset)
    db.commit()


def purge_expired_assets(db: Session, *, limit: int = 100) -> int:
    """Borra los videos caducados que no tengan publicaciones en curso.

    Se ejecuta periódicamente (Celery beat o el scheduler en proceso) para no
    almacenar videos permanentemente en el servidor.
    """
    from app.models import Post, PostStatus

    now = utcnow()
    candidates = list(
        db.scalars(
            select(MediaAsset)
            .where(
                MediaAsset.status == MediaStatus.READY,
                MediaAsset.expires_at.is_not(None),
                MediaAsset.expires_at <= now,
            )
            .limit(limit)
        )
    )
    deleted = 0
    for asset in candidates:
        active = db.scalars(
            select(Post.id).where(
                Post.media_asset_id == asset.id,
                Post.status.in_(
                    [
                        PostStatus.DRAFT,
                        PostStatus.QUEUED,
                        PostStatus.SCHEDULED,
                        PostStatus.UPLOADING,
                        PostStatus.PROCESSING,
                        PostStatus.PUBLISHING,
                    ]
                ),
            )
        ).first()
        if active:
            # Aún se necesita: posponemos la expiración.
            asset.expires_at = now + timedelta(hours=settings.media_retention_hours)
            db.add(asset)
            continue
        delete_asset_file(db, asset)
        deleted += 1
    db.commit()
    if deleted:
        logger.info("media: %s ficheros caducados eliminados", deleted)
    return deleted


def asset_is_expired(asset: MediaAsset) -> bool:
    expires = as_utc(asset.expires_at)
    return bool(expires and expires <= utcnow())
