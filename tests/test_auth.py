"""Autenticación de la API, rate limiting y endpoints de administración."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.services import clients as clients_service
from app.services import rate_limit


def test_health_no_requiere_api_key(anon_client: TestClient) -> None:
    response = anon_client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"ok", "degraded"}
    assert {c["name"] for c in body["components"]} >= {"database", "storage"}


def test_platforms_lista_las_tres_plataformas(anon_client: TestClient) -> None:
    response = anon_client.get("/v1/platforms")
    assert response.status_code == 200
    platforms = {row["platform"] for row in response.json()}
    assert {"instagram", "tiktok", "youtube"} <= platforms


def test_endpoint_protegido_sin_api_key_devuelve_401(anon_client: TestClient) -> None:
    response = anon_client.get("/v1/accounts")
    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"


def test_api_key_invalida_devuelve_401(anon_client: TestClient) -> None:
    response = anon_client.get("/v1/accounts", headers={"Authorization": "Bearer svk_no_existe"})
    assert response.status_code == 401


def test_api_key_valida_en_bearer(api_client) -> None:
    client, _record, _key = api_client
    assert client.get("/v1/accounts").status_code == 200


def test_api_key_valida_en_header_x_api_key(anon_client: TestClient, db) -> None:
    record = clients_service.create_client(db, name="via-header")
    issued = clients_service.issue_api_key(db, record)
    response = anon_client.get("/v1/accounts", headers={"X-API-Key": issued.api_key})
    assert response.status_code == 200


def test_api_key_revocada_devuelve_401(anon_client: TestClient, db) -> None:
    record = clients_service.create_client(db, name="revocado")
    issued = clients_service.issue_api_key(db, record)
    clients_service.revoke_api_key(db, issued.record)
    response = anon_client.get(
        "/v1/accounts", headers={"Authorization": f"Bearer {issued.api_key}"}
    )
    assert response.status_code == 401


def test_api_key_caducada_devuelve_401(anon_client: TestClient, db) -> None:
    from datetime import timedelta

    from app.models import utcnow

    record = clients_service.create_client(db, name="caducado")
    issued = clients_service.issue_api_key(db, record, expires_at=utcnow() - timedelta(minutes=1))
    response = anon_client.get(
        "/v1/accounts", headers={"Authorization": f"Bearer {issued.api_key}"}
    )
    assert response.status_code == 401


def test_la_api_key_no_se_guarda_en_claro(db) -> None:
    record = clients_service.create_client(db, name="hash")
    issued = clients_service.issue_api_key(db, record)
    assert issued.api_key not in issued.record.key_hash
    assert len(issued.record.key_hash) == 64  # SHA-256 hex
    assert issued.record.key_prefix == issued.api_key[:10]


def test_aislamiento_entre_clientes(anon_client: TestClient, db) -> None:
    """Un cliente no puede ver los recursos de otro."""
    from app.services import media as media_service

    a = clients_service.create_client(db, name="cliente-a")
    b = clients_service.create_client(db, name="cliente-b")
    key_b = clients_service.issue_api_key(db, b).api_key

    from io import BytesIO

    from tests.conftest import make_video_bytes

    asset = media_service.create_asset_from_upload(
        db,
        client_id=a.id,
        filename="a.mp4",
        content_type="video/mp4",
        stream=BytesIO(make_video_bytes()),
    )

    response = anon_client.get(
        f"/v1/media/{asset.id}", headers={"Authorization": f"Bearer {key_b}"}
    )
    assert response.status_code == 404


class TestRateLimit:
    @pytest.fixture(autouse=True)
    def _enable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.config import settings

        monkeypatch.setattr(settings, "rate_limit_enabled", True)
        monkeypatch.setattr(settings, "rate_limit_requests", 3)
        monkeypatch.setattr(settings, "rate_limit_window_seconds", 60)
        rate_limit.reset()
        yield
        rate_limit.reset()

    def test_supera_el_limite_devuelve_429(self, api_client) -> None:
        client, _record, _key = api_client
        codes = [client.get("/v1/accounts").status_code for _ in range(5)]
        assert codes[:3] == [200, 200, 200]
        assert 429 in codes
        last = client.get("/v1/accounts")
        assert last.status_code == 429
        assert "Retry-After" in last.headers

    def test_cabeceras_de_rate_limit(self, api_client) -> None:
        client, _record, _key = api_client
        response = client.get("/v1/accounts")
        assert response.headers["X-RateLimit-Limit"] == "3"
        assert response.headers["X-RateLimit-Remaining"] == "2"


class TestAdmin:
    def test_crear_cliente_y_usar_su_api_key(self, anon_client: TestClient) -> None:
        response = anon_client.post(
            "/v1/admin/clients",
            json={"name": "Macaly", "email": "macaly@ejemplo.com"},
            headers={"Authorization": "Bearer adm_test_key"},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["client"]["name"] == "Macaly"
        api_key = body["api_key"]
        assert api_key.startswith("svk_")

        # La key devuelta funciona de inmediato.
        assert (
            anon_client.get(
                "/v1/accounts", headers={"Authorization": f"Bearer {api_key}"}
            ).status_code
            == 200
        )

    def test_admin_requiere_key_de_admin(self, api_client) -> None:
        client, _record, _key = api_client  # key de cliente, no de admin
        response = client.post("/v1/admin/clients", json={"name": "x"})
        assert response.status_code == 401

    def test_rotacion_de_api_key(self, anon_client: TestClient) -> None:
        admin = {"Authorization": "Bearer adm_test_key"}
        created = anon_client.post(
            "/v1/admin/clients", json={"name": "rotar"}, headers=admin
        ).json()
        client_id = created["client"]["id"]
        old_key = created["api_key"]

        keys = anon_client.get(f"/v1/admin/clients/{client_id}/api-keys", headers=admin).json()
        old_id = keys[0]["id"]

        rotated = anon_client.post(
            f"/v1/admin/clients/{client_id}/api-keys/rotate",
            json={"revoke_key_id": old_id, "label": "nueva"},
            headers=admin,
        )
        assert rotated.status_code == 201
        new_key = rotated.json()["api_key"]
        assert new_key != old_key

        # La nueva funciona, la vieja ya no.
        assert (
            anon_client.get(
                "/v1/accounts", headers={"Authorization": f"Bearer {new_key}"}
            ).status_code
            == 200
        )
        assert (
            anon_client.get(
                "/v1/accounts", headers={"Authorization": f"Bearer {old_key}"}
            ).status_code
            == 401
        )
