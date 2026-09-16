"""Publicación: multiplataforma, estados, idempotencia, scheduling y reintentos."""

from __future__ import annotations

import io
from datetime import timedelta

import pytest

from app.models import Platform, PostStatus, utcnow
from tests.conftest import make_video_bytes


@pytest.fixture
def media_id(api_client) -> str:
    client, _record, _key = api_client
    response = client.post(
        "/v1/media", files={"file": ("reel.mp4", io.BytesIO(make_video_bytes()), "video/mp4")}
    )
    assert response.status_code == 201
    return response.json()["id"]


class TestCreacionYValidacion:
    def test_publicacion_inmediata_en_una_plataforma(
        self, api_client, connected_accounts, fake_providers, media_id
    ) -> None:
        client, _record, _key = api_client
        response = client.post(
            "/v1/posts",
            json={"media_id": media_id, "platforms": ["instagram"], "caption": "hola"},
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["status"] == "published"
        assert len(body["posts"]) == 1
        post = body["posts"][0]
        assert post["platform"] == "instagram"
        assert post["status"] == "published"
        assert post["external_post_id"] == "ext-post-instagram"
        assert post["external_url"] == "https://fake.test/instagram/post"
        assert post["published_at"] is not None

    def test_publicacion_en_las_tres_plataformas(
        self, api_client, connected_accounts, fake_providers, media_id
    ) -> None:
        client, _record, _key = api_client
        response = client.post(
            "/v1/posts",
            json={
                "media_id": media_id,
                "platforms": ["instagram", "tiktok", "youtube"],
                "caption": "multi",
                "title": "Mi video",
                "tags": ["a", "#b"],
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["status"] == "published"
        assert {p["platform"] for p in body["posts"]} == {"instagram", "tiktok", "youtube"}
        assert all(p["status"] == "published" for p in body["posts"])
        # Las almohadillas de los tags se normalizan.
        assert body["tags"] == ["a", "b"]

    def test_exige_media_id_o_video_url_pero_no_ambos(self, api_client) -> None:
        client, _record, _key = api_client
        sin_nada = client.post("/v1/posts", json={"platforms": ["instagram"]})
        assert sin_nada.status_code == 422
        con_ambos = client.post(
            "/v1/posts",
            json={"media_id": "x", "video_url": "https://a/b.mp4", "platforms": ["instagram"]},
        )
        assert con_ambos.status_code == 422

    def test_rechaza_lista_de_plataformas_vacia(self, api_client, media_id) -> None:
        client, _record, _key = api_client
        response = client.post("/v1/posts", json={"media_id": media_id, "platforms": []})
        assert response.status_code == 422

    def test_rechaza_plataforma_desconocida(self, api_client, media_id) -> None:
        client, _record, _key = api_client
        response = client.post("/v1/posts", json={"media_id": media_id, "platforms": ["myspace"]})
        assert response.status_code == 422

    def test_deduplica_plataformas_repetidas(
        self, api_client, connected_accounts, fake_providers, media_id
    ) -> None:
        client, _record, _key = api_client
        body = client.post(
            "/v1/posts",
            json={"media_id": media_id, "platforms": ["instagram", "instagram"]},
        ).json()
        assert len(body["posts"]) == 1

    def test_media_inexistente_devuelve_404(
        self, api_client, connected_accounts, fake_providers
    ) -> None:
        client, _record, _key = api_client
        response = client.post(
            "/v1/posts", json={"media_id": "no-existe", "platforms": ["instagram"]}
        )
        assert response.status_code == 404

    def test_sin_cuentas_conectadas_devuelve_409(
        self, api_client, fake_providers, media_id
    ) -> None:
        client, _record, _key = api_client
        response = client.post("/v1/posts", json={"media_id": media_id, "platforms": ["instagram"]})
        assert response.status_code == 409
        body = response.json()
        assert body["error"] == "no_connected_accounts"
        assert "instagram" in body["details"]

    def test_una_plataforma_sin_cuenta_no_bloquea_las_demas(
        self, db, api_client, fake_providers, media_id
    ) -> None:
        """Requisito 11.6: un fallo en una plataforma no bloquea al resto."""
        from app.providers.base import OAuthCredentials
        from app.services import accounts as accounts_service

        client, record, _key = api_client
        accounts_service.upsert_account(
            db,
            client_id=record.id,
            platform=Platform.INSTAGRAM,
            external_account_id="ext-instagram",
            account_name="solo-instagram",
            credentials=OAuthCredentials(access_token="t"),
        )

        body = client.post(
            "/v1/posts",
            json={"media_id": media_id, "platforms": ["instagram", "tiktok", "youtube"]},
        ).json()
        assert len(body["posts"]) == 1
        assert body["posts"][0]["platform"] == "instagram"
        assert body["posts"][0]["status"] == "published"
        assert set(body["skipped_platforms"]) == {"tiktok", "youtube"}

    def test_un_fallo_de_provider_no_afecta_a_las_otras_plataformas(
        self, api_client, connected_accounts, fake_providers, media_id
    ) -> None:
        from app.providers.errors import PermanentProviderError

        fake_providers[Platform.TIKTOK].publish_error = PermanentProviderError(
            "TikTok rechazó el video"
        )

        client, _record, _key = api_client
        body = client.post(
            "/v1/posts",
            json={"media_id": media_id, "platforms": ["instagram", "tiktok", "youtube"]},
        ).json()

        por_plataforma = {p["platform"]: p for p in body["posts"]}
        assert por_plataforma["instagram"]["status"] == "published"
        assert por_plataforma["youtube"]["status"] == "published"
        assert por_plataforma["tiktok"]["status"] == "failed"
        assert "rechazó" in por_plataforma["tiktok"]["error_message"]
        # El grupo se reporta como publicado parcial (hubo éxitos).
        assert body["status"] == "published"

    def test_opciones_por_plataforma_llegan_al_provider(
        self, api_client, connected_accounts, fake_providers, media_id
    ) -> None:
        client, _record, _key = api_client
        client.post(
            "/v1/posts",
            json={
                "media_id": media_id,
                "platforms": ["youtube"],
                "platform_options": {"youtube": {"privacy_status": "public"}},
            },
        )
        request = fake_providers[Platform.YOUTUBE].publish_calls[0]
        assert request.options["privacy_status"] == "public"

    def test_subida_y_publicacion_en_una_sola_peticion(
        self, api_client, connected_accounts, fake_providers
    ) -> None:
        client, _record, _key = api_client
        response = client.post(
            "/v1/posts/upload",
            files={"file": ("x.mp4", io.BytesIO(make_video_bytes()), "video/mp4")},
            data={"platforms": "instagram,tiktok", "caption": "desde multipart", "tags": "a,b"},
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert len(body["posts"]) == 2
        assert body["caption"] == "desde multipart"
        assert body["tags"] == ["a", "b"]


class TestEstados:
    def test_consulta_por_id_de_grupo_y_de_post(
        self, api_client, connected_accounts, fake_providers, media_id
    ) -> None:
        client, _record, _key = api_client
        created = client.post(
            "/v1/posts", json={"media_id": media_id, "platforms": ["instagram"]}
        ).json()

        por_grupo = client.get(f"/v1/posts/{created['id']}")
        assert por_grupo.status_code == 200
        assert por_grupo.json()["id"] == created["id"]

        # También acepta el id de un post individual.
        por_post = client.get(f"/v1/posts/{created['posts'][0]['id']}")
        assert por_post.status_code == 200
        assert por_post.json()["id"] == created["id"]

    def test_post_inexistente_devuelve_404(self, api_client) -> None:
        client, _record, _key = api_client
        assert client.get("/v1/posts/no-existe").status_code == 404

    def test_todos_los_estados_estan_definidos(self) -> None:
        """Requisito 13: los nueve estados del ciclo de vida."""
        assert {s.value for s in PostStatus} == {
            "draft",
            "queued",
            "uploading",
            "processing",
            "scheduled",
            "publishing",
            "published",
            "failed",
            "cancelled",
        }

    def test_estados_terminales_y_activos(self) -> None:
        assert PostStatus.PUBLISHED.is_terminal
        assert PostStatus.FAILED.is_terminal
        assert PostStatus.CANCELLED.is_terminal
        assert not PostStatus.QUEUED.is_terminal
        assert PostStatus.PROCESSING.is_active
        assert not PostStatus.PUBLISHED.is_active

    def test_historico_y_filtros(
        self, api_client, connected_accounts, fake_providers, media_id
    ) -> None:
        client, _record, _key = api_client
        client.post("/v1/posts", json={"media_id": media_id, "platforms": ["instagram"]})
        client.post("/v1/posts", json={"media_id": media_id, "platforms": ["tiktok"]})

        todos = client.get("/v1/posts").json()
        assert todos["total"] == 2

        solo_ig = client.get("/v1/posts?platform=instagram").json()
        assert solo_ig["total"] == 1
        assert solo_ig["items"][0]["posts"][0]["platform"] == "instagram"

        publicados = client.get("/v1/posts?status=published").json()
        assert publicados["total"] == 2

        fallidos = client.get("/v1/posts?status=failed").json()
        assert fallidos["total"] == 0

    def test_paginacion(self, api_client, connected_accounts, fake_providers, media_id) -> None:
        client, _record, _key = api_client
        for _ in range(3):
            client.post("/v1/posts", json={"media_id": media_id, "platforms": ["instagram"]})

        page = client.get("/v1/posts?limit=2&offset=0").json()
        assert page["total"] == 3
        assert len(page["items"]) == 2
        assert page["limit"] == 2

        assert client.get("/v1/posts?limit=0").status_code == 422
        assert client.get("/v1/posts?limit=500").status_code == 422
        assert client.get("/v1/posts?offset=-1").status_code == 422

    def test_detalle_de_intentos(
        self, api_client, connected_accounts, fake_providers, media_id
    ) -> None:
        client, _record, _key = api_client
        created = client.post(
            "/v1/posts", json={"media_id": media_id, "platforms": ["instagram"]}
        ).json()
        intentos = client.get(f"/v1/posts/{created['id']}/attempts").json()
        assert len(intentos) == 1
        assert intentos[0]["attempt_count"] == 1
        assert intentos[0]["attempts"][0]["status"] == "succeeded"
        assert intentos[0]["attempts"][0]["duration_ms"] is not None

    def test_politica_de_reintentos_publicada(self, anon_client) -> None:
        body = anon_client.get("/v1/posts/config/retries").json()
        assert body["max_attempts"] == 3
        assert "transient" in body["retryable_categories"]
        assert "auth" in body["non_retryable_categories"]


class TestIdempotencia:
    def test_la_misma_clave_no_publica_dos_veces(
        self, api_client, connected_accounts, fake_providers, media_id
    ) -> None:
        """Requisito 14: dos peticiones idénticas = una sola publicación."""
        client, _record, _key = api_client
        payload = {"media_id": media_id, "platforms": ["instagram"], "caption": "único"}
        headers = {"Idempotency-Key": "clave-abc-123"}

        primera = client.post("/v1/posts", json=payload, headers=headers)
        segunda = client.post("/v1/posts", json=payload, headers=headers)

        assert primera.status_code == 201
        assert segunda.status_code == 201
        assert primera.json()["id"] == segunda.json()["id"]
        # El provider sólo se llamó UNA vez.
        assert len(fake_providers[Platform.INSTAGRAM].publish_calls) == 1
        assert client.get("/v1/posts").json()["total"] == 1

    def test_misma_clave_con_cuerpo_distinto_devuelve_409(
        self, api_client, connected_accounts, fake_providers, media_id
    ) -> None:
        client, _record, _key = api_client
        headers = {"Idempotency-Key": "clave-conflicto"}
        client.post(
            "/v1/posts",
            json={"media_id": media_id, "platforms": ["instagram"], "caption": "a"},
            headers=headers,
        )
        conflicto = client.post(
            "/v1/posts",
            json={"media_id": media_id, "platforms": ["instagram"], "caption": "b"},
            headers=headers,
        )
        assert conflicto.status_code == 409
        assert "diferente" in conflicto.json()["message"]

    def test_claves_distintas_publican_dos_veces(
        self, api_client, connected_accounts, fake_providers, media_id
    ) -> None:
        client, _record, _key = api_client
        payload = {"media_id": media_id, "platforms": ["instagram"]}
        client.post("/v1/posts", json=payload, headers={"Idempotency-Key": "k1"})
        client.post("/v1/posts", json=payload, headers={"Idempotency-Key": "k2"})
        assert len(fake_providers[Platform.INSTAGRAM].publish_calls) == 2

    def test_la_clave_se_aisla_por_cliente(
        self, db, api_client, anon_client, connected_accounts, fake_providers, media_id
    ) -> None:
        """La misma clave usada por otro cliente no colisiona."""
        from app.providers.base import OAuthCredentials
        from app.services import accounts as accounts_service
        from app.services import clients as clients_service
        from app.services import media as media_service

        client, _record, _key = api_client
        client.post(
            "/v1/posts",
            json={"media_id": media_id, "platforms": ["instagram"]},
            headers={"Idempotency-Key": "compartida"},
        )

        otro = clients_service.create_client(db, name="otro")
        otra_key = clients_service.issue_api_key(db, otro).api_key
        accounts_service.upsert_account(
            db,
            client_id=otro.id,
            platform=Platform.INSTAGRAM,
            external_account_id="ext-instagram",
            account_name="otra-cuenta",
            credentials=OAuthCredentials(access_token="t"),
        )
        otro_media = media_service.create_asset_from_upload(
            db,
            client_id=otro.id,
            filename="o.mp4",
            content_type="video/mp4",
            stream=io.BytesIO(make_video_bytes()),
        )

        response = anon_client.post(
            "/v1/posts",
            json={"media_id": otro_media.id, "platforms": ["instagram"]},
            headers={
                "Authorization": f"Bearer {otra_key}",
                "Idempotency-Key": "compartida",
            },
        )
        assert response.status_code == 201
        assert len(fake_providers[Platform.INSTAGRAM].publish_calls) == 2

    def test_la_clave_se_libera_si_la_peticion_falla(
        self, api_client, fake_providers, media_id
    ) -> None:
        """Tras un 409 por falta de cuentas, la clave se puede reutilizar."""
        client, _record, _key = api_client
        headers = {"Idempotency-Key": "liberable"}
        payload = {"media_id": media_id, "platforms": ["instagram"]}

        primera = client.post("/v1/posts", json=payload, headers=headers)
        assert primera.status_code == 409

        # Al no haber quedado la clave bloqueada, el reintento vuelve a evaluarse.
        segunda = client.post("/v1/posts", json=payload, headers=headers)
        assert segunda.status_code == 409

    def test_clave_demasiado_larga_devuelve_422(self, api_client, media_id) -> None:
        client, _record, _key = api_client
        response = client.post(
            "/v1/posts",
            json={"media_id": media_id, "platforms": ["instagram"]},
            headers={"Idempotency-Key": "x" * 256},
        )
        assert response.status_code == 422

    def test_hash_de_peticion_ignora_el_orden_de_las_claves(self) -> None:
        from app.services.idempotency import hash_request

        assert hash_request({"a": 1, "b": 2}) == hash_request({"b": 2, "a": 1})
        assert hash_request({"a": 1}) != hash_request({"a": 2})


class TestProgramacion:
    def test_crea_una_publicacion_programada(
        self, api_client, connected_accounts, fake_providers, media_id
    ) -> None:
        client, _record, _key = api_client
        cuando = (utcnow() + timedelta(hours=2)).isoformat()
        response = client.post(
            "/v1/posts",
            json={
                "media_id": media_id,
                "platforms": ["instagram", "tiktok"],
                "scheduled_at": cuando,
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["status"] == "scheduled"
        assert all(p["status"] == "scheduled" for p in body["posts"])
        # NO se ha publicado nada todavía.
        assert fake_providers[Platform.INSTAGRAM].publish_calls == []

    def test_rechaza_fecha_en_el_pasado(
        self, api_client, connected_accounts, fake_providers, media_id
    ) -> None:
        client, _record, _key = api_client
        response = client.post(
            "/v1/posts",
            json={
                "media_id": media_id,
                "platforms": ["instagram"],
                "scheduled_at": (utcnow() - timedelta(hours=1)).isoformat(),
            },
        )
        assert response.status_code == 422
        assert "futura" in response.json()["message"]

    def test_listado_de_programadas_pendientes(
        self, api_client, connected_accounts, fake_providers, media_id
    ) -> None:
        client, _record, _key = api_client
        client.post(
            "/v1/posts",
            json={
                "media_id": media_id,
                "platforms": ["instagram"],
                "scheduled_at": (utcnow() + timedelta(days=1)).isoformat(),
            },
        )
        pendientes = client.get("/v1/posts/scheduled/upcoming").json()
        assert len(pendientes) == 1
        assert pendientes[0]["status"] == "scheduled"

    def test_el_barredor_publica_cuando_llega_la_hora(
        self, db, api_client, connected_accounts, fake_providers, media_id
    ) -> None:
        """El barredor lee de la BD: sobrevive a reinicios del worker."""
        from sqlalchemy import select

        from app.models import Post, ScheduledPost
        from app.workers.tasks import sweep_scheduled_posts

        client, _record, _key = api_client
        created = client.post(
            "/v1/posts",
            json={
                "media_id": media_id,
                "platforms": ["instagram"],
                "scheduled_at": (utcnow() + timedelta(hours=1)).isoformat(),
            },
        ).json()

        # Nada vencido todavía.
        assert sweep_scheduled_posts()["dispatched"] == 0

        # Simulamos que ya pasó la hora.
        post_id = created["posts"][0]["id"]
        schedule = db.scalars(select(ScheduledPost).where(ScheduledPost.post_id == post_id)).one()
        schedule.run_at = utcnow() - timedelta(minutes=1)
        db.add(schedule)
        db.commit()

        assert sweep_scheduled_posts()["dispatched"] == 1
        db.expire_all()
        post = db.get(Post, post_id)
        assert post.status == PostStatus.PUBLISHED
        assert post.external_post_id == "ext-post-instagram"

    def test_cancelar_una_publicacion_programada(
        self, api_client, connected_accounts, fake_providers, media_id
    ) -> None:
        client, _record, _key = api_client
        created = client.post(
            "/v1/posts",
            json={
                "media_id": media_id,
                "platforms": ["instagram", "tiktok"],
                "scheduled_at": (utcnow() + timedelta(hours=3)).isoformat(),
            },
        ).json()

        cancelada = client.post(f"/v1/posts/{created['id']}/cancel")
        assert cancelada.status_code == 200
        assert len(cancelada.json()["cancelled"]) == 2

        estado = client.get(f"/v1/posts/{created['id']}").json()
        assert estado["status"] == "cancelled"

        # El barredor ya no la despacha.
        from app.workers.tasks import sweep_scheduled_posts

        assert sweep_scheduled_posts()["dispatched"] == 0
        assert fake_providers[Platform.INSTAGRAM].publish_calls == []

    def test_no_se_puede_cancelar_una_publicacion_ya_publicada(
        self, api_client, connected_accounts, fake_providers, media_id
    ) -> None:
        client, _record, _key = api_client
        created = client.post(
            "/v1/posts", json={"media_id": media_id, "platforms": ["instagram"]}
        ).json()
        response = client.post(f"/v1/posts/{created['id']}/cancel")
        assert response.status_code == 409
        assert response.json()["error"] == "not_cancellable"
