"""Publicación de videos: inmediata, programada y multiplataforma."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import select

from app.config import settings
from app.deps import CurrentAuth, DbSession, IdempotencyKeyDep, PaginationDep
from app.logging_config import get_logger
from app.models import MediaAsset, MediaStatus, Platform, Post, PostGroup, PostStatus
from app.schemas import (
    CancelPostResponse,
    CreatePostRequest,
    PaginatedResponse,
    PostGroupResponse,
    PostResponse,
    RetryPostResponse,
)
from app.services import dispatch, publisher
from app.services import idempotency as idempotency_service
from app.services import media as media_service
from app.services import posts as posts_service
from app.services.idempotency import (
    IdempotencyConflictError,
    IdempotencyInProgressError,
)
from app.services.media import MediaNotFoundError
from app.services.posts import NoAccountsError, PostNotFoundError, ScheduleInPastError
from app.utils.video import VideoValidationError

logger = get_logger(__name__)
router = APIRouter(prefix="/posts", tags=["publicaciones"])

IDEMPOTENCY_ENDPOINT = "POST /v1/posts"


def _resolve_asset(db, client_id: str, payload: CreatePostRequest) -> MediaAsset:
    """Obtiene el `MediaAsset` desde `media_id` o descargándolo de `video_url`."""
    if payload.media_id:
        try:
            asset = media_service.get_asset(db, client_id, payload.media_id)
        except MediaNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        if asset.status != MediaStatus.READY:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"El video {asset.id} está en estado '{asset.status}' y no se puede publicar",
            )
        return asset

    try:
        return media_service.create_asset_from_url(
            db, client_id=client_id, url=str(payload.video_url), download=True
        )
    except VideoValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message
        ) from exc


def _dispatch(group: PostGroup) -> None:
    """Encola la publicación inmediata de cada post del grupo.

    Cada plataforma va en su propia tarea: un fallo en una no bloquea las otras.
    """
    for post in group.posts:
        if PostStatus(post.status) == PostStatus.QUEUED:
            try:
                dispatch.enqueue_post(post.id)
            except Exception as exc:
                logger.error(
                    "posts: no se pudo encolar post_id=%s (%s). "
                    "El barredor de reintentos lo recogerá.",
                    post.id,
                    exc,
                )


def _create(
    db,
    client_id: str,
    payload: CreatePostRequest,
    idempotency_key: str | None,
) -> PostGroupResponse:
    """Lógica compartida por `POST /posts` y `POST /posts/upload`."""
    replay: Any = None
    if idempotency_key:
        try:
            replay = idempotency_service.begin(
                db,
                client_id=client_id,
                key=idempotency_key,
                endpoint=IDEMPOTENCY_ENDPOINT,
                payload=payload.model_dump(mode="json"),
            )
        except IdempotencyConflictError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        except IdempotencyInProgressError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
                headers={"Retry-After": "5"},
            ) from exc
        if replay is not None:
            return PostGroupResponse.model_validate(replay.response_body)

    try:
        asset = _resolve_asset(db, client_id, payload)
        group, skipped = posts_service.create_post_group(
            db,
            client_id=client_id,
            asset=asset,
            platforms=payload.platforms,
            caption=payload.caption,
            title=payload.title,
            description=payload.description,
            tags=payload.tags,
            scheduled_at=payload.scheduled_at,
            platform_options=payload.platform_options,
            account_ids=payload.account_ids,
            idempotency_key=idempotency_key,
        )
    except ScheduleInPastError as exc:
        if idempotency_key:
            idempotency_service.release(db, client_id=client_id, key=idempotency_key)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except NoAccountsError as exc:
        if idempotency_key:
            idempotency_service.release(db, client_id=client_id, key=idempotency_key)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "no_connected_accounts",
                "message": str(exc),
                "details": exc.errors,
            },
        ) from exc
    except HTTPException:
        if idempotency_key:
            idempotency_service.release(db, client_id=client_id, key=idempotency_key)
        raise

    if not payload.scheduled_at:
        _dispatch(group)

    db.refresh(group)
    response = PostGroupResponse.from_group(group)

    if idempotency_key:
        idempotency_service.complete(
            db,
            client_id=client_id,
            key=idempotency_key,
            response_body=response.model_dump(mode="json"),
            resource_id=group.id,
        )

    logger.info(
        "posts: publicación creada group_id=%s plataformas=%s programada=%s omitidas=%s",
        group.id,
        [p.platform for p in group.posts],
        payload.scheduled_at,
        list(skipped),
    )
    return response


@router.post(
    "",
    response_model=PostGroupResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear una publicación (inmediata o programada)",
)
def create_post(
    payload: CreatePostRequest,
    auth: CurrentAuth,
    db: DbSession,
    idempotency_key: IdempotencyKeyDep = None,
) -> PostGroupResponse:
    """Publica un video en una o varias plataformas.

    * `media_id` o `video_url`: origen del video (exactamente uno).
    * `platforms`: `["instagram", "tiktok", "youtube"]`.
    * `scheduled_at`: null para publicar ya; fecha futura para programar.
    * Cabecera `Idempotency-Key`: evita duplicados si la petición se repite.

    Las plataformas sin cuenta conectada se omiten y se listan en
    `skipped_platforms`, sin bloquear al resto.
    """
    return _create(db, auth.client_id, payload, idempotency_key)


@router.post(
    "/upload",
    response_model=PostGroupResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Subir el video y publicar en una sola petición",
)
def create_post_with_upload(
    auth: CurrentAuth,
    db: DbSession,
    file: UploadFile = File(description="Fichero de video (mp4, mov o webm)"),
    platforms: str = Form(description="Plataformas separadas por coma: instagram,tiktok,youtube"),
    caption: str | None = Form(default=None),
    title: str | None = Form(default=None),
    description: str | None = Form(default=None),
    tags: str | None = Form(default=None, description="Etiquetas separadas por coma"),
    scheduled_at: datetime | None = Form(
        default=None, description="ISO-8601 futuro; vacío = publicar ya"
    ),
    idempotency_key: IdempotencyKeyDep = None,
) -> PostGroupResponse:
    """Atajo para clientes que prefieren una sola llamada multipart."""
    try:
        platform_list = [Platform(p.strip()) for p in platforms.split(",") if p.strip()]
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Plataforma desconocida en `platforms`: {exc}",
        ) from exc
    if not platform_list:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="`platforms` no puede estar vacío",
        )

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
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message
        ) from exc
    finally:
        file.file.close()

    payload = CreatePostRequest(
        media_id=asset.id,
        platforms=platform_list,
        caption=caption,
        title=title,
        description=description,
        tags=[t.strip() for t in (tags or "").split(",") if t.strip()],
        scheduled_at=scheduled_at,
    )
    return _create(db, auth.client_id, payload, idempotency_key)


@router.get(
    "",
    response_model=PaginatedResponse[PostGroupResponse],
    summary="Histórico de publicaciones",
)
def list_posts(
    auth: CurrentAuth,
    db: DbSession,
    page: PaginationDep,
    platform: Platform | None = Query(default=None),
    post_status: PostStatus | None = Query(
        default=None, alias="status", description="Filtra por estado de alguna plataforma"
    ),
) -> PaginatedResponse[PostGroupResponse]:
    """Devuelve las publicaciones anteriores, de la más reciente a la más antigua."""
    query = posts_service.list_groups_query(
        client_id=auth.client_id, platform=platform, status=post_status
    )
    total = posts_service.count_groups(db, query)
    rows = list(db.scalars(query.limit(page.limit).offset(page.offset)))
    return PaginatedResponse[PostGroupResponse](
        items=[PostGroupResponse.from_group(row) for row in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/{post_id}",
    response_model=PostGroupResponse,
    summary="Consultar el estado de una publicación",
)
def get_post(
    post_id: str,
    auth: CurrentAuth,
    db: DbSession,
    sync: bool = Query(
        default=False,
        description="Si es true consulta la plataforma para refrescar el estado",
    ),
) -> PostGroupResponse:
    """Estado de la publicación. Acepta el id de grupo o de un post individual.

    Estados posibles: `draft`, `queued`, `uploading`, `processing`, `scheduled`,
    `publishing`, `published`, `failed`, `cancelled`.
    """
    try:
        group = posts_service.find_group_or_post(db, auth.client_id, post_id)
    except PostNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    if sync:
        for post in group.posts:
            if not PostStatus(post.status).is_terminal or not post.external_url:
                publisher.sync_post_status(db, post)
        db.refresh(group)

    return PostGroupResponse.from_group(group)


@router.get(
    "/{post_id}/attempts",
    response_model=list[PostResponse],
    summary="Detalle de intentos por plataforma",
)
def get_attempts(post_id: str, auth: CurrentAuth, db: DbSession) -> list[PostResponse]:
    """Historial completo de intentos: útil para diagnosticar fallos."""
    try:
        group = posts_service.find_group_or_post(db, auth.client_id, post_id)
    except PostNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return [PostResponse.model_validate(post) for post in group.posts]


@router.post(
    "/{post_id}/retry",
    response_model=RetryPostResponse,
    summary="Reintentar un post fallido",
)
def retry_post(post_id: str, auth: CurrentAuth, db: DbSession) -> RetryPostResponse:
    """Reencola un post en estado `failed` (reinicia el contador de intentos)."""
    try:
        post = posts_service.get_post(db, auth.client_id, post_id)
    except PostNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    current = PostStatus(post.status)
    if current == PostStatus.PUBLISHED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="El post ya está publicado"
        )
    if current not in {PostStatus.FAILED, PostStatus.CANCELLED, PostStatus.QUEUED}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"No se puede reintentar un post en estado '{current}'",
        )

    if post.media_asset.status != MediaStatus.READY:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "El video ya no está disponible (se borró por retención). "
                "Súbelo de nuevo y crea una publicación nueva."
            ),
        )

    post.status = PostStatus.QUEUED
    post.attempt_count = 0
    post.next_retry_at = None
    post.error_message = None
    post.error_category = None
    db.add(post)
    db.commit()
    db.refresh(post)

    dispatch.enqueue_post(post.id)
    # La tarea corre en su propia sesión: recargamos para devolver el estado real
    # (en modo eager ya estará publicado; con Celery seguirá en `queued`).
    db.expire(post)
    db.refresh(post)
    return RetryPostResponse(post=PostResponse.model_validate(post), message="Post reencolado")


@router.post(
    "/{post_id}/cancel",
    response_model=CancelPostResponse,
    summary="Cancelar una publicación pendiente o programada",
)
def cancel_post(post_id: str, auth: CurrentAuth, db: DbSession) -> CancelPostResponse:
    """Cancela los posts que aún no se enviaron a la plataforma."""
    try:
        group = posts_service.find_group_or_post(db, auth.client_id, post_id)
    except PostNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    # Si pidieron un post concreto, cancelamos sólo ese.
    single = db.scalars(
        select(Post).where(Post.id == post_id, Post.client_id == auth.client_id)
    ).first()
    targets = [single] if single else list(group.posts)

    cancelled: list[str] = []
    not_cancelled: dict[str, str] = {}
    for post in targets:
        if publisher.cancel_post(db, post):
            cancelled.append(post.id)
        else:
            not_cancelled[post.id] = f"No se puede cancelar: el post está en estado '{post.status}'"

    if not cancelled and not_cancelled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "not_cancellable",
                "message": "Ningún post se pudo cancelar",
                "details": not_cancelled,
            },
        )
    return CancelPostResponse(id=group.id, cancelled=cancelled, not_cancelled=not_cancelled)


@router.get(
    "/{post_id}/status",
    response_model=PostGroupResponse,
    summary="Alias de GET /posts/{id} con sincronización forzada",
)
def post_status(post_id: str, auth: CurrentAuth, db: DbSession) -> PostGroupResponse:
    """Consulta el estado forzando la sincronización con la plataforma."""
    return get_post(post_id, auth, db, sync=True)


@router.get(
    "/scheduled/upcoming",
    response_model=list[PostResponse],
    summary="Publicaciones programadas pendientes",
)
def upcoming(
    auth: CurrentAuth,
    db: DbSession,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[PostResponse]:
    """Lista las publicaciones programadas que aún no se han ejecutado.

    Nota: en Codespaces sólo se publican mientras el entorno esté encendido.
    """
    rows = list(
        db.scalars(
            select(Post)
            .where(
                Post.client_id == auth.client_id,
                Post.status == PostStatus.SCHEDULED,
            )
            .order_by(Post.scheduled_at)
            .limit(limit)
        )
    )
    return [PostResponse.model_validate(row) for row in rows]


@router.get(
    "/config/retries",
    summary="Política de reintentos vigente",
)
def retry_policy() -> dict[str, Any]:
    """Expone la configuración de reintentos para que el cliente la entienda."""
    return {
        "max_attempts": settings.max_publish_attempts,
        "base_delay_seconds": settings.retry_base_delay_seconds,
        "max_delay_seconds": settings.retry_max_delay_seconds,
        "strategy": "exponential backoff con jitter ±20%",
        "retryable_categories": ["transient", "rate_limit", "processing_timeout", "internal"],
        "non_retryable_categories": ["auth", "permanent", "configuration", "invalid_video"],
        "processing_timeout_seconds": settings.processing_timeout_seconds,
        "processing_poll_interval_seconds": settings.processing_poll_interval_seconds,
    }
