"""Clasificación de errores, backoff exponencial y reintentos."""

from __future__ import annotations

import io
import itertools
from datetime import timedelta

import pytest

from app.config import settings
from app.models import ErrorCategory, Platform, PostStatus, as_utc, utcnow
from app.providers.errors import (
    AuthenticationError,
    ConfigurationError,
    InvalidVideoError,
    PermanentProviderError,
    ProcessingTimeoutError,
    RateLimitError,
    TransientProviderError,
    error_for_status,
)
from app.services.retry import classify, compute_backoff, next_retry_at, should_retry
from tests.conftest import make_video_bytes


class TestClasificacionDeErrores:
    @pytest.mark.parametrize(
        ("excepcion", "categoria", "reintentable"),
        [
            (TransientProviderError("red caída"), ErrorCategory.TRANSIENT, True),
            (RateLimitError("demasiadas"), ErrorCategory.RATE_LIMIT, True),
            (ProcessingTimeoutError("lento"), ErrorCategory.PROCESSING_TIMEOUT, True),
            (AuthenticationError("token malo"), ErrorCategory.AUTH, False),
            (PermanentProviderError("rechazado"), ErrorCategory.PERMANENT, False),
            (ConfigurationError("falta secreto"), ErrorCategory.CONFIGURATION, False),
            (InvalidVideoError("formato malo"), ErrorCategory.INVALID_VIDEO, False),
        ],
    )
    def test_categorias_y_reintentabilidad(
        self, excepcion: Exception, categoria: ErrorCategory, reintentable: bool
    ) -> None:
        assert classify(excepcion) is categoria
        assert categoria.retryable is reintentable
        assert excepcion.retryable is reintentable  # type: ignore[attr-defined]

    def test_clasifica_excepciones_de_python(self) -> None:
        assert classify(TimeoutError()) is ErrorCategory.TRANSIENT
        assert classify(ConnectionError()) is ErrorCategory.TRANSIENT
        assert classify(ValueError("x")) is ErrorCategory.PERMANENT
        assert classify(RuntimeError("x")) is ErrorCategory.INTERNAL

    @pytest.mark.parametrize(
        ("status", "tipo"),
        [
            (429, RateLimitError),
            (401, AuthenticationError),
            (403, AuthenticationError),
            (400, PermanentProviderError),
            (404, PermanentProviderError),
            (500, TransientProviderError),
            (502, TransientProviderError),
            (503, TransientProviderError),
            (408, TransientProviderError),
        ],
    )
    def test_mapeo_de_codigos_http(self, status: int, tipo: type) -> None:
        assert isinstance(error_for_status(status, "x"), tipo)


class TestBackoff:
    def test_crece_exponencialmente(self) -> None:
        esperas = [
            compute_backoff(ErrorCategory.TRANSIENT, n).total_seconds() for n in (1, 2, 3, 4)
        ]
        # Con jitter de ±20 % el crecimiento sigue siendo claro.
        for anterior, siguiente in itertools.pairwise(esperas):
            assert siguiente > anterior

    def test_respeta_el_tope_maximo(self) -> None:
        espera = compute_backoff(ErrorCategory.TRANSIENT, 50).total_seconds()
        assert espera <= settings.retry_max_delay_seconds * 1.2

    def test_rate_limit_espera_mas_que_un_error_temporal(self) -> None:
        # El multiplicador de rate limit es 4x; el jitter no invierte el orden.
        transitorio = compute_backoff(ErrorCategory.TRANSIENT, 1).total_seconds()
        limite = compute_backoff(ErrorCategory.RATE_LIMIT, 1).total_seconds()
        assert limite > transitorio

    def test_retry_after_tiene_prioridad(self) -> None:
        espera = compute_backoff(ErrorCategory.RATE_LIMIT, 1, retry_after=42)
        assert espera.total_seconds() == 42

    def test_retry_after_se_limita_al_maximo(self) -> None:
        espera = compute_backoff(ErrorCategory.RATE_LIMIT, 1, retry_after=10**9)
        assert espera.total_seconds() == settings.retry_max_delay_seconds

    def test_el_jitter_produce_valores_distintos(self) -> None:
        valores = {compute_backoff(ErrorCategory.TRANSIENT, 3).total_seconds() for _ in range(20)}
        assert len(valores) > 1

    def test_siempre_al_menos_un_segundo(self) -> None:
        assert compute_backoff(ErrorCategory.TRANSIENT, 1).total_seconds() >= 1

    def test_next_retry_at_es_futuro(self) -> None:
        assert next_retry_at(ErrorCategory.TRANSIENT, 1) > utcnow()

    def test_should_retry_respeta_el_maximo_de_intentos(self) -> None:
        assert should_retry(ErrorCategory.TRANSIENT, 1)
        assert not should_retry(ErrorCategory.TRANSIENT, settings.max_publish_attempts)
        assert not should_retry(ErrorCategory.AUTH, 1)


class TestReintentosEnPublicacion:
    @pytest.fixture
    def media_id(self, api_client) -> str:
        client, _record, _key = api_client
        return client.post(
            "/v1/media", files={"file": ("r.mp4", io.BytesIO(make_video_bytes()), "video/mp4")}
        ).json()["id"]

    def test_un_error_temporal_programa_reintento(
        self, api_client, connected_accounts, fake_providers, media_id
    ) -> None:
        fake_providers[Platform.INSTAGRAM].publish_error = TransientProviderError("502 de Meta")
        client, _record, _key = api_client
        body = client.post(
            "/v1/posts", json={"media_id": media_id, "platforms": ["instagram"]}
        ).json()

        post = body["posts"][0]
        assert post["status"] == "queued"
        assert post["error_category"] == "transient"
        assert post["next_retry_at"] is not None
        assert post["attempt_count"] == 1

    def test_un_error_permanente_no_reintenta(
        self, api_client, connected_accounts, fake_providers, media_id
    ) -> None:
        fake_providers[Platform.INSTAGRAM].publish_error = InvalidVideoError(
            "El video no cumple el formato de Reels"
        )
        client, _record, _key = api_client
        post = client.post(
            "/v1/posts", json={"media_id": media_id, "platforms": ["instagram"]}
        ).json()["posts"][0]

        assert post["status"] == "failed"
        assert post["error_category"] == "invalid_video"
        assert post["next_retry_at"] is None

    def test_un_error_de_auth_desactiva_el_reintento(
        self, api_client, connected_accounts, fake_providers, media_id
    ) -> None:
        fake_providers[Platform.INSTAGRAM].publish_error = AuthenticationError("token caducado")
        client, _record, _key = api_client
        post = client.post(
            "/v1/posts", json={"media_id": media_id, "platforms": ["instagram"]}
        ).json()["posts"][0]
        assert post["status"] == "failed"
        assert post["error_category"] == "auth"

    def test_agota_los_intentos_y_queda_failed(
        self, db, api_client, connected_accounts, fake_providers, media_id
    ) -> None:
        """Tras MAX_PUBLISH_ATTEMPTS el post pasa a `failed`."""
        from app.models import Post
        from app.services import publisher

        fake_providers[Platform.INSTAGRAM].publish_error = TransientProviderError("caída")
        client, _record, _key = api_client
        body = client.post(
            "/v1/posts", json={"media_id": media_id, "platforms": ["instagram"]}
        ).json()
        post_id = body["posts"][0]["id"]

        for _ in range(settings.max_publish_attempts):
            db.expire_all()
            post = db.get(Post, post_id)
            if PostStatus(post.status) == PostStatus.FAILED:
                break
            publisher.publish_post(db, post)

        db.expire_all()
        post = db.get(Post, post_id)
        assert post.status == PostStatus.FAILED
        assert post.attempt_count == settings.max_publish_attempts
        assert len(post.attempts) == settings.max_publish_attempts
        assert post.attempts[-1].status == "failed"
        assert post.attempts[0].status == "retry_scheduled"

    def test_el_estado_del_provider_se_conserva_entre_intentos(
        self, db, api_client, connected_accounts, fake_providers, media_id
    ) -> None:
        """Requisito de reanudación: no se re-sube el video en cada intento."""
        from app.models import Post
        from app.providers.base import PublishResult
        from app.services import publisher

        provider = fake_providers[Platform.INSTAGRAM]
        client, _record, _key = api_client
        body = client.post(
            "/v1/posts", json={"media_id": media_id, "platforms": ["instagram"]}
        ).json()
        assert body["posts"][0]["status"] == "published"

        # Un segundo post que falla tras guardar estado.
        def publish_con_estado(credentials, request):
            request.save_state(container_id="IG-123")
            if not getattr(publish_con_estado, "llamado", False):
                publish_con_estado.llamado = True
                raise TransientProviderError("cayó tras subir")
            assert request.state["container_id"] == "IG-123"
            return PublishResult(external_post_id="ok-reanudado")

        provider.publish = publish_con_estado  # type: ignore[method-assign]
        segundo = client.post(
            "/v1/posts", json={"media_id": media_id, "platforms": ["instagram"]}
        ).json()
        segundo_id = segundo["posts"][0]["id"]

        db.expire_all()
        post = db.get(Post, segundo_id)
        assert post.status == PostStatus.QUEUED
        assert post.provider_state["container_id"] == "IG-123"

        # El reintento reutiliza el container_id y publica.
        publisher.publish_post(db, post)
        db.expire_all()
        post = db.get(Post, segundo_id)
        assert post.status == PostStatus.PUBLISHED
        assert post.external_post_id == "ok-reanudado"

    def test_el_endpoint_de_retry_reencola_un_post_fallido(
        self, api_client, connected_accounts, fake_providers, media_id
    ) -> None:
        provider = fake_providers[Platform.INSTAGRAM]
        provider.publish_error = PermanentProviderError("fallo")
        client, _record, _key = api_client
        body = client.post(
            "/v1/posts", json={"media_id": media_id, "platforms": ["instagram"]}
        ).json()
        post_id = body["posts"][0]["id"]
        assert body["posts"][0]["status"] == "failed"

        # Arreglamos la causa y reintentamos.
        provider.publish_error = None
        response = client.post(f"/v1/posts/{post_id}/retry")
        assert response.status_code == 200
        assert response.json()["post"]["status"] == "published"

    def test_no_se_puede_reintentar_un_post_publicado(
        self, api_client, connected_accounts, fake_providers, media_id
    ) -> None:
        client, _record, _key = api_client
        body = client.post(
            "/v1/posts", json={"media_id": media_id, "platforms": ["instagram"]}
        ).json()
        response = client.post(f"/v1/posts/{body['posts'][0]['id']}/retry")
        assert response.status_code == 409

    def test_el_barredor_relanza_los_reintentos_vencidos(
        self, db, api_client, connected_accounts, fake_providers, media_id
    ) -> None:
        from app.models import Post
        from app.workers.tasks import retry_pending_posts

        provider = fake_providers[Platform.INSTAGRAM]
        provider.publish_error = TransientProviderError("temporal")
        client, _record, _key = api_client
        post_id = client.post(
            "/v1/posts", json={"media_id": media_id, "platforms": ["instagram"]}
        ).json()["posts"][0]["id"]

        # El backoff aún no venció: no se relanza.
        assert retry_pending_posts()["dispatched"] == 0

        db.expire_all()
        post = db.get(Post, post_id)
        post.next_retry_at = utcnow() - timedelta(seconds=1)
        db.add(post)
        db.commit()

        provider.publish_error = None
        assert retry_pending_posts()["dispatched"] == 1
        db.expire_all()
        assert db.get(Post, post_id).status == PostStatus.PUBLISHED

    def test_no_se_republica_un_post_ya_publicado(
        self, db, api_client, connected_accounts, fake_providers, media_id
    ) -> None:
        """Salvaguarda contra duplicados si una tarea se ejecuta dos veces."""
        from app.models import Post
        from app.services import publisher

        client, _record, _key = api_client
        post_id = client.post(
            "/v1/posts", json={"media_id": media_id, "platforms": ["instagram"]}
        ).json()["posts"][0]["id"]
        llamadas_antes = len(fake_providers[Platform.INSTAGRAM].publish_calls)

        db.expire_all()
        resultado = publisher.publish_post(db, db.get(Post, post_id))
        assert resultado.status == PostStatus.PUBLISHED
        assert len(fake_providers[Platform.INSTAGRAM].publish_calls) == llamadas_antes

    def test_is_retry_due(
        self, db, api_client, connected_accounts, fake_providers, media_id
    ) -> None:
        from app.models import Post
        from app.services import publisher

        fake_providers[Platform.INSTAGRAM].publish_error = TransientProviderError("x")
        client, _record, _key = api_client
        post_id = client.post(
            "/v1/posts", json={"media_id": media_id, "platforms": ["instagram"]}
        ).json()["posts"][0]["id"]

        db.expire_all()
        post = db.get(Post, post_id)
        assert not publisher.is_retry_due(post)
        assert publisher.retry_delay_seconds(post) > 0
        assert as_utc(post.next_retry_at) > utcnow()

        post.next_retry_at = utcnow() - timedelta(seconds=1)
        db.add(post)
        db.commit()
        db.expire_all()
        assert publisher.is_retry_due(db.get(Post, post_id))
