"""Modo `solo`: publicación en hilos del propio proceso, sin Redis ni Celery."""

from __future__ import annotations

import io
import threading

import pytest

from app.config import settings
from app.models import Platform, Post, PostStatus
from app.services import dispatch, publisher
from tests.conftest import make_video_bytes


@pytest.fixture
def media_id(api_client) -> str:
    client, _record, _key = api_client
    return client.post(
        "/v1/media", files={"file": ("r.mp4", io.BytesIO(make_video_bytes()), "video/mp4")}
    ).json()["id"]


class TestReclamacionAtomica:
    """`claim_post` es lo que impide publicar dos veces el mismo post."""

    def test_solo_un_reclamante_gana(
        self, db, api_client, connected_accounts, fake_providers, media_id
    ) -> None:
        from app.models import PostGroup
        from app.services import media as media_service
        from app.services import posts as posts_service

        _client, record, _key = api_client
        asset = media_service.get_asset(db, record.id, media_id)
        group, _ = posts_service.create_post_group(
            db,
            client_id=record.id,
            asset=asset,
            platforms=[Platform.INSTAGRAM],
        )
        post_id = group.posts[0].id
        assert db.get(Post, post_id).status == PostStatus.QUEUED

        # Dos intentos de reclamar el mismo post: sólo uno puede ganar.
        assert publisher.claim_post(db, post_id) is True
        assert publisher.claim_post(db, post_id) is False
        assert db.get(PostGroup, group.id) is not None

    def test_no_se_reclama_un_post_ya_publicado(
        self, db, api_client, connected_accounts, fake_providers, media_id
    ) -> None:
        client, _record, _key = api_client
        post_id = client.post(
            "/v1/posts", json={"media_id": media_id, "platforms": ["instagram"]}
        ).json()["posts"][0]["id"]
        db.expire_all()
        assert db.get(Post, post_id).status == PostStatus.PUBLISHED
        assert publisher.claim_post(db, post_id) is False

    def test_la_reclamacion_concurrente_solo_deja_pasar_a_uno(
        self, db, api_client, connected_accounts, fake_providers, media_id
    ) -> None:
        """Varios hilos compitiendo: exactamente uno debe reclamar el post."""
        from app.database import session_scope
        from app.services import media as media_service
        from app.services import posts as posts_service

        _client, record, _key = api_client
        asset = media_service.get_asset(db, record.id, media_id)
        group, _ = posts_service.create_post_group(
            db, client_id=record.id, asset=asset, platforms=[Platform.INSTAGRAM]
        )
        post_id = group.posts[0].id

        ganadores: list[bool] = []
        barrera = threading.Barrier(4)

        def intentar() -> None:
            barrera.wait()
            with session_scope() as sesion:
                ganadores.append(publisher.claim_post(sesion, post_id))

        hilos = [threading.Thread(target=intentar) for _ in range(4)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join(timeout=10)

        assert sum(ganadores) == 1, f"esperado 1 ganador, hubo {sum(ganadores)}"


class TestModoSolo:
    def test_publica_en_segundo_plano(
        self,
        db,
        api_client,
        connected_accounts,
        fake_providers,
        media_id,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Con PUBLISH_MODE=solo la petición responde ya y el hilo publica."""
        from app.services import runner as runner_module

        monkeypatch.setattr(settings, "publish_mode", "solo")
        runner_module.shutdown_runner()

        client, _record, _key = api_client
        cuerpo = client.post(
            "/v1/posts", json={"media_id": media_id, "platforms": ["instagram"]}
        ).json()
        post_id = cuerpo["posts"][0]["id"]

        # Esperamos a que el hilo termine (el pool es del propio proceso).
        runner_module.get_runner()._pool.shutdown(wait=True)
        runner_module.shutdown_runner()

        db.expire_all()
        post = db.get(Post, post_id)
        assert post.status == PostStatus.PUBLISHED
        assert post.external_post_id == "ext-post-instagram"
        assert len(fake_providers[Platform.INSTAGRAM].publish_calls) == 1

    def test_el_modo_inline_publica_durante_la_peticion(
        self, api_client, connected_accounts, fake_providers, media_id
    ) -> None:
        assert settings.publish_mode == "inline"
        client, _record, _key = api_client
        cuerpo = client.post(
            "/v1/posts", json={"media_id": media_id, "platforms": ["instagram"]}
        ).json()
        assert cuerpo["posts"][0]["status"] == "published"

    def test_redis_no_hace_falta_salvo_con_celery(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for modo, necesita in (("solo", False), ("inline", False), ("celery", True)):
            monkeypatch.setattr(settings, "publish_mode", modo)
            assert settings.needs_redis is necesita

    def test_health_informa_del_modo(self, api_client) -> None:
        client, _record, _key = api_client
        componentes = {c["name"]: c for c in client.get("/health").json()["components"]}
        assert componentes["publisher"]["detail"].startswith("inline")
        # Sin Celery, Redis no penaliza la salud del servicio.
        assert componentes["redis"]["healthy"] is True
        assert "no se usa" in componentes["redis"]["detail"]


class TestRecuperacionAlArrancar:
    def test_devuelve_a_la_cola_los_posts_interrumpidos(
        self, db, api_client, connected_accounts, fake_providers, media_id
    ) -> None:
        """Si el servicio muere publicando, al arrancar se reencola."""
        from app.services import jobs
        from app.services import media as media_service
        from app.services import posts as posts_service

        _client, record, _key = api_client
        asset = media_service.get_asset(db, record.id, media_id)
        group, _ = posts_service.create_post_group(
            db, client_id=record.id, asset=asset, platforms=[Platform.INSTAGRAM]
        )
        post = group.posts[0]
        # Simulamos la muerte del proceso a mitad de la subida.
        post.status = PostStatus.UPLOADING
        post.provider_state = {"container_id": "IG-INTERRUMPIDO"}
        db.add(post)
        db.commit()

        resultado = jobs.recover_interrupted_posts()
        assert resultado["recovered"] == 1

        db.expire_all()
        recuperado = db.get(Post, post.id)
        assert recuperado.status == PostStatus.PUBLISHED
        # El estado del provider se conserva: no se re-sube el video.
        assert (
            fake_providers[Platform.INSTAGRAM].publish_calls[0].state["container_id"]
            == "IG-INTERRUMPIDO"
        )

    def test_no_toca_los_posts_sanos(
        self, db, api_client, connected_accounts, fake_providers, media_id
    ) -> None:
        from app.services import jobs

        client, _record, _key = api_client
        client.post("/v1/posts", json={"media_id": media_id, "platforms": ["instagram"]})
        assert jobs.recover_interrupted_posts()["recovered"] == 0


class TestDispatch:
    def test_describe_los_tres_modos(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for modo in ("solo", "celery", "inline"):
            monkeypatch.setattr(settings, "publish_mode", modo)
            assert dispatch.describe_mode()
            assert dispatch.describe_mode() != modo  # es una descripción, no el id
