"""Creación de publicaciones: fan-out multiplataforma y programación."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models import (
    MediaAsset,
    Platform,
    Post,
    PostGroup,
    PostStatus,
    ScheduledPost,
    ScheduleStatus,
    SocialAccount,
    utcnow,
)
from app.models.base import as_utc
from app.services import accounts as accounts_service
from app.services.accounts import AccountNotFoundError

logger = get_logger(__name__)


class PostNotFoundError(LookupError):
    pass


class NoAccountsError(ValueError):
    """Ninguna de las plataformas pedidas tiene cuenta conectada."""

    def __init__(self, errors: dict[str, str]) -> None:
        super().__init__("No hay cuentas conectadas para ninguna de las plataformas solicitadas")
        self.errors = errors


class ScheduleInPastError(ValueError):
    def __init__(self) -> None:
        super().__init__("`scheduled_at` debe ser una fecha futura (en UTC o con offset)")


def resolve_accounts(
    db: Session,
    *,
    client_id: str,
    platforms: list[Platform],
    account_ids: dict[str, str] | None = None,
) -> tuple[dict[Platform, SocialAccount], dict[str, str]]:
    """Localiza la cuenta a usar en cada plataforma.

    Devuelve `(cuentas_encontradas, errores_por_plataforma)`. Las plataformas
    sin cuenta no bloquean a las demás.
    """
    account_ids = account_ids or {}
    found: dict[Platform, SocialAccount] = {}
    errors: dict[str, str] = {}
    for platform in platforms:
        try:
            found[platform] = accounts_service.find_active_account(
                db, client_id, platform, account_ids.get(platform.value)
            )
        except AccountNotFoundError as exc:
            errors[platform.value] = str(exc)
    return found, errors


def create_post_group(
    db: Session,
    *,
    client_id: str,
    asset: MediaAsset,
    platforms: list[Platform],
    caption: str | None = None,
    title: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
    scheduled_at: datetime | None = None,
    platform_options: dict[str, dict[str, Any]] | None = None,
    account_ids: dict[str, str] | None = None,
    idempotency_key: str | None = None,
) -> tuple[PostGroup, dict[str, str]]:
    """Crea el grupo y un `Post` por plataforma con cuenta conectada."""
    if scheduled_at is not None:
        scheduled_utc = as_utc(scheduled_at)
        if scheduled_utc is None or scheduled_utc <= utcnow():
            raise ScheduleInPastError()
        scheduled_at = scheduled_utc

    accounts, errors = resolve_accounts(
        db, client_id=client_id, platforms=platforms, account_ids=account_ids
    )
    if not accounts:
        raise NoAccountsError(errors)

    platform_options = platform_options or {}
    tags = tags or []

    group = PostGroup(
        client_id=client_id,
        media_asset_id=asset.id,
        caption=caption,
        title=title,
        description=description,
        tags=tags,
        scheduled_at=scheduled_at,
        idempotency_key=idempotency_key,
        options={"requested_platforms": [p.value for p in platforms], "skipped": errors},
    )
    db.add(group)
    db.flush()

    initial_status = PostStatus.SCHEDULED if scheduled_at else PostStatus.QUEUED

    for platform, account in accounts.items():
        post = Post(
            group_id=group.id,
            client_id=client_id,
            media_asset_id=asset.id,
            social_account_id=account.id,
            platform=platform,
            status=initial_status,
            caption=caption,
            title=title or caption,
            description=description or caption,
            tags=tags,
            platform_options=dict(platform_options.get(platform.value) or {}),
            scheduled_at=scheduled_at,
        )
        db.add(post)
        db.flush()

        if scheduled_at:
            db.add(
                ScheduledPost(
                    post_id=post.id,
                    client_id=client_id,
                    run_at=scheduled_at,
                    status=ScheduleStatus.PENDING,
                )
            )

    db.commit()
    db.refresh(group)
    logger.info(
        "posts: grupo creado group_id=%s plataformas=%s programado=%s omitidas=%s",
        group.id,
        [p.value for p in accounts],
        scheduled_at,
        list(errors),
    )
    return group, errors


def get_group(db: Session, client_id: str, group_id: str) -> PostGroup:
    group = db.scalars(
        select(PostGroup).where(PostGroup.id == group_id, PostGroup.client_id == client_id)
    ).first()
    if group is None:
        raise PostNotFoundError(f"No existe la publicación {group_id}")
    return group


def get_post(db: Session, client_id: str, post_id: str) -> Post:
    post = db.scalars(select(Post).where(Post.id == post_id, Post.client_id == client_id)).first()
    if post is None:
        raise PostNotFoundError(f"No existe el post {post_id}")
    return post


def find_group_or_post(db: Session, client_id: str, identifier: str) -> PostGroup:
    """`GET /v1/posts/{id}` acepta el id de grupo o de un post individual."""
    try:
        return get_group(db, client_id, identifier)
    except PostNotFoundError:
        post = get_post(db, client_id, identifier)
        return get_group(db, client_id, post.group_id)


def list_groups_query(
    *,
    client_id: str,
    platform: Platform | None = None,
    status: PostStatus | None = None,
) -> Select[tuple[PostGroup]]:
    """Consulta de histórico de publicaciones, filtrable."""
    query = select(PostGroup).where(PostGroup.client_id == client_id)
    if platform or status:
        conditions = [Post.group_id == PostGroup.id]
        if platform:
            conditions.append(Post.platform == platform)
        if status:
            conditions.append(Post.status == status)
        query = query.where(select(Post.id).where(*conditions).exists())
    return query.order_by(PostGroup.created_at.desc())


def count_groups(db: Session, query: Select[tuple[PostGroup]]) -> int:
    from sqlalchemy import func

    return int(db.scalar(select(func.count()).select_from(query.subquery())) or 0)


def pending_posts_for_dispatch(db: Session, *, limit: int = 50) -> list[Post]:
    """Posts encolados cuyo reintento ya vencío (recuperación tras caídas)."""
    now = utcnow()
    return list(
        db.scalars(
            select(Post)
            .where(
                Post.status == PostStatus.QUEUED,
                (Post.next_retry_at.is_(None)) | (Post.next_retry_at <= now),
            )
            .order_by(Post.created_at)
            .limit(limit)
        )
    )


def due_schedules(db: Session, *, limit: int = 50) -> list[ScheduledPost]:
    """Programaciones vencidas y aún no despachadas."""
    now = utcnow()
    return list(
        db.scalars(
            select(ScheduledPost)
            .where(
                ScheduledPost.status == ScheduleStatus.PENDING,
                ScheduledPost.run_at <= now,
            )
            .order_by(ScheduledPost.run_at)
            .limit(limit)
        )
    )


def mark_schedule_dispatched(db: Session, schedule: ScheduledPost, worker: str) -> None:
    schedule.status = ScheduleStatus.DISPATCHED
    schedule.dispatched_at = utcnow()
    schedule.locked_by = worker
    schedule.locked_at = utcnow()
    db.add(schedule)
    db.commit()


def stuck_posts(db: Session, *, older_than_minutes: int = 30, limit: int = 20) -> list[Post]:
    """Posts en `processing` desde hace demasiado: candidatos a sincronizar."""
    from datetime import timedelta

    threshold = utcnow() - timedelta(minutes=older_than_minutes)
    return list(
        db.scalars(
            select(Post)
            .where(
                Post.status.in_([PostStatus.PROCESSING, PostStatus.PUBLISHING]),
                Post.updated_at <= threshold,
            )
            .order_by(Post.updated_at)
            .limit(limit)
        )
    )
