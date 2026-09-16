"""Publicaciones: grupo multiplataforma, post por plataforma e intentos."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import AttemptStatus, ErrorCategory, Platform, PostStatus, ScheduleStatus

if TYPE_CHECKING:
    from app.models.media import MediaAsset
    from app.models.social_account import SocialAccount


class PostGroup(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Una solicitud `POST /v1/posts`: un video hacia N plataformas."""

    __tablename__ = "post_groups"

    client_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    media_asset_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("media_assets.id", ondelete="RESTRICT"), nullable=False
    )

    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    options: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    posts: Mapped[list[Post]] = relationship(
        back_populates="group",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="Post.platform",
    )
    media_asset: Mapped[MediaAsset] = relationship(lazy="joined")

    @property
    def aggregate_status(self) -> PostStatus:
        """Estado resumido del grupo a partir de los posts individuales."""
        statuses = [PostStatus(post.status) for post in self.posts]
        if not statuses:
            return PostStatus.DRAFT
        if all(s == PostStatus.PUBLISHED for s in statuses):
            return PostStatus.PUBLISHED
        if all(s == PostStatus.CANCELLED for s in statuses):
            return PostStatus.CANCELLED
        if all(s.is_terminal for s in statuses):
            # Mezcla de published/failed/cancelled: si hay algún éxito lo
            # reportamos como published parcial; si no, failed.
            return (
                PostStatus.PUBLISHED
                if any(s == PostStatus.PUBLISHED for s in statuses)
                else PostStatus.FAILED
            )
        for candidate in (
            PostStatus.PUBLISHING,
            PostStatus.PROCESSING,
            PostStatus.UPLOADING,
            PostStatus.QUEUED,
            PostStatus.SCHEDULED,
        ):
            if candidate in statuses:
                return candidate
        return PostStatus.DRAFT

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PostGroup {self.id} posts={len(self.posts)}>"


class Post(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Publicación en UNA plataforma concreta."""

    __tablename__ = "posts"
    __table_args__ = (
        Index("ix_posts_status_scheduled", "status", "scheduled_at"),
        Index("ix_posts_client_created", "client_id", "created_at"),
    )

    group_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("post_groups.id", ondelete="CASCADE"), nullable=False, index=True
    )
    client_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    media_asset_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("media_assets.id", ondelete="RESTRICT"), nullable=False
    )
    social_account_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("social_accounts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    platform: Mapped[Platform] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[PostStatus] = mapped_column(
        String(16), default=PostStatus.DRAFT, nullable=False, index=True
    )

    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    #: Opciones específicas de la plataforma (privacy_level, disable_comment…).
    platform_options: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    external_post_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    external_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_category: Mapped[ErrorCategory | None] = mapped_column(String(32), nullable=True)

    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    #: Estado intermedio del provider (container_id, publish_id, upload_url…).
    provider_state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    group: Mapped[PostGroup] = relationship(back_populates="posts")
    social_account: Mapped[SocialAccount] = relationship(lazy="joined")
    media_asset: Mapped[MediaAsset] = relationship(lazy="joined")
    attempts: Mapped[list[PostAttempt]] = relationship(
        back_populates="post",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="PostAttempt.attempt_number",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Post {self.id} {self.platform} {self.status}>"


class PostAttempt(UUIDPrimaryKeyMixin, Base):
    """Registro de cada intento de publicación (auditoría y diagnóstico)."""

    __tablename__ = "post_attempts"
    __table_args__ = (UniqueConstraint("post_id", "attempt_number", name="uq_attempt_number"),)

    post_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("posts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[AttemptStatus] = mapped_column(String(24), nullable=False)
    stage: Mapped[str | None] = mapped_column(String(64), nullable=True)

    error_category: Mapped[ErrorCategory | None] = mapped_column(String(32), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    post: Mapped[Post] = relationship(back_populates="attempts")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PostAttempt {self.post_id} #{self.attempt_number} {self.status}>"


class ScheduledPost(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Libro de programación: fuente de verdad de las publicaciones futuras.

    El barredor (`app.workers.tasks.sweep_scheduled_posts`) lee esta tabla, así
    que una parada del worker no pierde trabajos: al arrancar recupera los
    vencidos. Esto es clave en Codespaces, donde el entorno se apaga.
    """

    __tablename__ = "scheduled_posts"
    __table_args__ = (Index("ix_scheduled_run", "status", "run_at"),)

    post_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("posts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    client_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[ScheduleStatus] = mapped_column(
        String(16), default=ScheduleStatus.PENDING, nullable=False
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(120), nullable=True)

    post: Mapped[Post] = relationship(lazy="joined")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ScheduledPost {self.post_id} at {self.run_at} {self.status}>"
