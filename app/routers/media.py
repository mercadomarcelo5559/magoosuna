"""Subida y gestión de videos."""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from app.config import settings
from app.deps import CurrentAuth, DbSession, PaginationDep
from app.logging_config import get_logger
from app.models import MediaAsset, MediaStatus
from app.schemas import (
    MediaAssetResponse,
    MediaFromUrlRequest,
    MediaLimitsResponse,
    MessageResponse,
    PaginatedResponse,
)
from app.services import media as media_service
from app.services.media import MediaNotFoundError
from app.storage import get_storage
from app.utils.video import VideoValidationError

logger = get_logger(__name__)
router = APIRouter(prefix="/media", tags=["media"])


def _to_response(asset: MediaAsset, *, with_url: bool = True) -> MediaAssetResponse:
    response = MediaAssetResponse.model_validate(asset)
    if with_url and asset.status == MediaStatus.READY:
        response.download_url = media_service.build_signed_download_url(asset)
    return response


@router.get("/limits", response_model=MediaLimitsResponse, summary="Límites de subida")
def limits() -> MediaLimitsResponse:
    """Límites vigentes, para validar en el cliente antes de subir."""
    return MediaLimitsResponse(
        max_size_mb=settings.max_video_size_mb,
        allowed_mime_types=sorted(settings.allowed_mime_types),
        allowed_extensions=sorted(settings.allowed_extensions),
        retention_hours=settings.media_retention_hours,
        storage_backend=get_storage().name,
        public_url_reachable=media_service.public_url_is_reachable(),
    )


@router.post(
    "",
    response_model=MediaAssetResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Subir un video (multipart/form-data)",
)
def upload_media(
    auth: CurrentAuth,
    db: DbSession,
    file: UploadFile = File(description="Fichero de video (mp4, mov o webm)"),
) -> MediaAssetResponse:
    """Sube un video y lo deja listo para publicar.

    Valida extensión, MIME real (por los bytes del fichero) y tamaño. El
    fichero se guarda temporalmente y se borra pasadas `MEDIA_RETENTION_HOURS`.
    """
    try:
        asset = media_service.create_asset_from_upload(
            db,
            client_id=auth.client_id,
            filename=file.filename,
            content_type=file.content_type,
            stream=file.file,
        )
    except VideoValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.message,
        ) from exc
    finally:
        file.file.close()
    return _to_response(asset)


@router.post(
    "/from-url",
    response_model=MediaAssetResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar un video desde una URL pública",
)
def media_from_url(
    payload: MediaFromUrlRequest, auth: CurrentAuth, db: DbSession
) -> MediaAssetResponse:
    """Descarga (opcionalmente) y valida un video accesible por URL."""
    try:
        asset = media_service.create_asset_from_url(
            db, client_id=auth.client_id, url=payload.video_url, download=payload.download
        )
    except VideoValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message
        ) from exc
    return _to_response(asset)


@router.get(
    "",
    response_model=PaginatedResponse[MediaAssetResponse],
    summary="Listar videos",
)
def list_media(
    auth: CurrentAuth,
    db: DbSession,
    page: PaginationDep,
    include_deleted: bool = Query(default=False),
) -> PaginatedResponse[MediaAssetResponse]:
    query = select(MediaAsset).where(MediaAsset.client_id == auth.client_id)
    if not include_deleted:
        query = query.where(MediaAsset.status != MediaStatus.DELETED)
    total = int(db.scalar(select(func.count()).select_from(query.subquery())) or 0)
    rows = list(
        db.scalars(
            query.order_by(MediaAsset.created_at.desc()).limit(page.limit).offset(page.offset)
        )
    )
    return PaginatedResponse[MediaAssetResponse](
        items=[_to_response(row, with_url=False) for row in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{media_id}", response_model=MediaAssetResponse, summary="Detalle de un video")
def get_media(media_id: str, auth: CurrentAuth, db: DbSession) -> MediaAssetResponse:
    try:
        asset = media_service.get_asset(db, auth.client_id, media_id)
    except MediaNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _to_response(asset)


@router.get(
    "/{media_id}/download",
    summary="Descarga firmada (la usan las plataformas, no requiere API key)",
    response_model=None,
)
def download_media(
    media_id: str,
    db: DbSession,
    token: str = Query(description="Token de la URL firmada"),
) -> StreamingResponse:
    """Sirve el video con una URL firmada y temporal.

    Instagram y TikTok (PULL_FROM_URL) descargan el video desde aquí, por lo
    que este endpoint NO usa API key: se autentica con la firma HMAC del token.
    """
    if not media_service.verify_download_token(media_id, token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Token de descarga inválido o caducado"
        )

    asset = db.get(MediaAsset, media_id)
    if asset is None or asset.status != MediaStatus.READY or not asset.storage_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="El video no está disponible"
        )

    storage = get_storage()
    if not storage.exists(asset.storage_key):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="El fichero ya no existe")

    key = asset.storage_key
    return StreamingResponse(
        storage.open_stream(key, chunk_size=settings.stream_chunk_size),
        media_type=asset.content_type,
        headers={
            "Content-Length": str(asset.size_bytes or storage.size(key)),
            "Content-Disposition": f'inline; filename="{asset.filename}"',
            "Cache-Control": "private, max-age=600",
            "Accept-Ranges": "none",
        },
    )


@router.delete("/{media_id}", response_model=MessageResponse, summary="Borrar un video")
def delete_media(media_id: str, auth: CurrentAuth, db: DbSession) -> MessageResponse:
    """Borra el fichero del almacenamiento inmediatamente."""
    try:
        asset = media_service.get_asset(db, auth.client_id, media_id)
    except MediaNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    media_service.delete_asset_file(db, asset)
    return MessageResponse(message=f"Video {media_id} eliminado")
