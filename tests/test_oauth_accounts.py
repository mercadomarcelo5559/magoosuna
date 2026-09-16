"""Flujo OAuth, refresh de tokens y desconexión de cuentas."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import OAuthState, Platform, SocialAccount, utcnow


class TestAutorizacion:
    @pytest.mark.parametrize("platform", ["instagram", "tiktok", "youtube"])
    def test_devuelve_url_y_guarda_el_state(
        self, api_client, fake_providers, db, platform: str
    ) -> None:
        client, record, _key = api_client
        response = client.get(f"/v1/oauth/{platform}/authorize")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["platform"] == platform
        assert body["authorization_url"].startswith("https://")
        assert body["state"] in body["authorization_url"]

        guardado = db.scalars(select(OAuthState).where(OAuthState.state == body["state"])).one()
        assert guardado.platform == Platform(platform)
        assert guardado.client_id == record.id
        assert guardado.used_at is None

    def test_requiere_api_key(self, anon_client) -> None:
        assert anon_client.get("/v1/oauth/instagram/authorize").status_code == 401

    def test_plataforma_no_soportada(self, api_client, fake_providers) -> None:
        client, _record, _key = api_client
        assert client.get("/v1/oauth/myspace/authorize").status_code == 422

    def test_modo_redirect(self, api_client, fake_providers) -> None:
        client, _record, _key = api_client
        response = client.get("/v1/oauth/instagram/authorize?redirect=true", follow_redirects=False)
        assert response.status_code == 307
        assert response.headers["location"].startswith("https://fake.test/authorize")

    def test_plataforma_sin_credenciales_devuelve_501(
        self, api_client, fake_providers, monkeypatch
    ) -> None:
        from app.providers.errors import ConfigurationError

        provider = fake_providers[Platform.INSTAGRAM]

        def sin_config(*, state: str, redirect_uri: str):
            raise ConfigurationError("Instagram no está configurado")

        monkeypatch.setattr(provider, "build_authorization_request", sin_config)
        client, _record, _key = api_client
        response = client.get("/v1/oauth/instagram/authorize")
        assert response.status_code == 501


class TestCallback:
    def _state(self, client) -> str:
        return client.get("/v1/oauth/instagram/authorize").json()["state"]

    def test_callback_conecta_la_cuenta(self, api_client, anon_client, fake_providers, db) -> None:
        client, record, _key = api_client
        state = self._state(client)

        # El callback lo llama el navegador del usuario, sin API key.
        response = anon_client.get(
            f"/v1/oauth/instagram/callback?code=codigo-de-prueba&state={state}"
        )
        assert response.status_code == 200
        assert "Cuenta conectada" in response.text

        cuenta = db.scalars(select(SocialAccount).where(SocialAccount.client_id == record.id)).one()
        assert cuenta.platform == Platform.INSTAGRAM
        assert cuenta.account_name == "cuenta-instagram"
        assert cuenta.external_account_id == "ext-instagram"
        assert cuenta.is_active
        # El token está cifrado.
        assert cuenta.access_token_encrypted.startswith("fernet:")
        assert "access-codigo-de-prueba" not in cuenta.access_token_encrypted

    def test_el_state_es_de_un_solo_uso(self, api_client, anon_client, fake_providers) -> None:
        client, _record, _key = api_client
        state = self._state(client)
        url = f"/v1/oauth/instagram/callback?code=abc&state={state}"

        assert anon_client.get(url).status_code == 200
        segunda = anon_client.get(url)
        assert segunda.status_code == 400
        assert "caducado" in segunda.text

    def test_state_invalido(self, anon_client, fake_providers) -> None:
        response = anon_client.get("/v1/oauth/instagram/callback?code=abc&state=inventado")
        assert response.status_code == 400
        assert "Estado inválido" in response.text

    def test_state_de_otra_plataforma(self, api_client, anon_client, fake_providers) -> None:
        client, _record, _key = api_client
        state = self._state(client)  # state de instagram
        response = anon_client.get(f"/v1/oauth/tiktok/callback?code=abc&state={state}")
        assert response.status_code == 400

    def test_state_caducado(self, api_client, anon_client, fake_providers, db) -> None:
        client, _record, _key = api_client
        state = self._state(client)
        registro = db.scalars(select(OAuthState).where(OAuthState.state == state)).one()
        registro.expires_at = utcnow() - timedelta(minutes=1)
        db.add(registro)
        db.commit()

        response = anon_client.get(f"/v1/oauth/instagram/callback?code=abc&state={state}")
        assert response.status_code == 400

    def test_la_plataforma_devuelve_error(self, anon_client, fake_providers) -> None:
        response = anon_client.get(
            "/v1/oauth/instagram/callback?error=access_denied"
            "&error_description=El+usuario+canceló"
        )
        assert response.status_code == 400
        assert "canceló" in response.text

    def test_callback_sin_code(self, anon_client, fake_providers) -> None:
        response = anon_client.get("/v1/oauth/instagram/callback?state=x")
        assert response.status_code == 400
        assert "incompleto" in response.text

    def test_redirige_al_return_url(self, api_client, anon_client, fake_providers) -> None:
        client, _record, _key = api_client
        state = client.get(
            "/v1/oauth/instagram/authorize?return_url=https://mi-app.macaly.test/ok"
        ).json()["state"]

        response = anon_client.get(
            f"/v1/oauth/instagram/callback?code=abc&state={state}", follow_redirects=False
        )
        assert response.status_code == 303
        location = response.headers["location"]
        assert location.startswith("https://mi-app.macaly.test/ok?")
        assert "status=connected" in location
        assert "platform=instagram" in location

    def test_reconectar_actualiza_la_cuenta_existente(
        self, api_client, anon_client, fake_providers, db
    ) -> None:
        client, record, _key = api_client
        for _ in range(2):
            state = self._state(client)
            anon_client.get(f"/v1/oauth/instagram/callback?code=abc&state={state}")

        cuentas = list(
            db.scalars(select(SocialAccount).where(SocialAccount.client_id == record.id))
        )
        assert len(cuentas) == 1  # no se duplica


class TestConexionManual:
    def test_conecta_con_un_token_existente(self, api_client, fake_providers) -> None:
        client, _record, _key = api_client
        response = client.post(
            "/v1/oauth/connect",
            json={
                "platform": "youtube",
                "access_token": "token-largo-de-prueba",
                "refresh_token": "refresh-de-prueba",
                "expires_in_seconds": 3600,
                "scopes": ["https://www.googleapis.com/auth/youtube.upload"],
            },
        )
        assert response.status_code == 201, response.text
        cuenta = response.json()["account"]
        assert cuenta["platform"] == "youtube"
        assert cuenta["has_refresh_token"] is True
        assert "token-largo-de-prueba" not in response.text

    def test_rechaza_token_demasiado_corto(self, api_client, fake_providers) -> None:
        client, _record, _key = api_client
        response = client.post(
            "/v1/oauth/connect", json={"platform": "youtube", "access_token": "corto"}
        )
        assert response.status_code == 422


class TestGestionDeCuentas:
    def test_listar_y_filtrar(self, api_client, connected_accounts, fake_providers) -> None:
        client, _record, _key = api_client
        todas = client.get("/v1/accounts").json()
        assert todas["total"] == 3

        solo_tiktok = client.get("/v1/accounts?platform=tiktok").json()
        assert solo_tiktok["total"] == 1
        assert solo_tiktok["items"][0]["platform"] == "tiktok"

    def test_detalle_y_404(self, api_client, connected_accounts, fake_providers) -> None:
        client, _record, _key = api_client
        cuenta = connected_accounts[Platform.INSTAGRAM]
        assert client.get(f"/v1/accounts/{cuenta.id}").status_code == 200
        assert client.get("/v1/accounts/no-existe").status_code == 404

    def test_refresh_manual_renueva_el_token(
        self, db, api_client, connected_accounts, fake_providers
    ) -> None:
        client, _record, _key = api_client
        cuenta = connected_accounts[Platform.INSTAGRAM]
        response = client.post(f"/v1/accounts/{cuenta.id}/refresh")
        assert response.status_code == 200
        assert response.json()["refreshed"] is True
        assert fake_providers[Platform.INSTAGRAM].refresh_calls == 1

        db.expire_all()
        actualizada = db.get(SocialAccount, cuenta.id)
        from app.services.accounts import credentials_from_account

        assert credentials_from_account(actualizada).access_token.endswith("-refreshed")

    def test_refresh_automatico_antes_de_publicar(
        self, db, api_client, connected_accounts, fake_providers
    ) -> None:
        """Un token a punto de caducar se renueva solo."""
        from app.services.accounts import ensure_fresh_credentials

        cuenta = connected_accounts[Platform.INSTAGRAM]
        cuenta.token_expiration = utcnow() + timedelta(minutes=2)  # < margen de 10 min
        db.add(cuenta)
        db.commit()

        ensure_fresh_credentials(db, cuenta)
        assert fake_providers[Platform.INSTAGRAM].refresh_calls == 1

    def test_no_refresca_si_el_token_esta_lejos_de_caducar(
        self, db, api_client, connected_accounts, fake_providers
    ) -> None:
        from app.services.accounts import ensure_fresh_credentials

        ensure_fresh_credentials(db, connected_accounts[Platform.INSTAGRAM])
        assert fake_providers[Platform.INSTAGRAM].refresh_calls == 0

    def test_un_fallo_de_auth_al_refrescar_desactiva_la_cuenta(
        self, db, api_client, connected_accounts, fake_providers, monkeypatch
    ) -> None:
        from app.providers.errors import AuthenticationError
        from app.services.accounts import ensure_fresh_credentials

        provider = fake_providers[Platform.INSTAGRAM]
        monkeypatch.setattr(
            provider,
            "refresh_token",
            lambda credentials: (_ for _ in ()).throw(AuthenticationError("caducado")),
        )
        cuenta = connected_accounts[Platform.INSTAGRAM]
        with pytest.raises(AuthenticationError):
            ensure_fresh_credentials(db, cuenta, force=True)

        db.expire_all()
        actualizada = db.get(SocialAccount, cuenta.id)
        assert actualizada.is_active is False
        assert "Reconecta" in (actualizada.last_error or "")

    def test_un_fallo_temporal_al_refrescar_no_desactiva_la_cuenta(
        self, db, api_client, connected_accounts, fake_providers, monkeypatch
    ) -> None:
        from app.providers.errors import TransientProviderError
        from app.services.accounts import ensure_fresh_credentials

        provider = fake_providers[Platform.INSTAGRAM]
        monkeypatch.setattr(
            provider,
            "refresh_token",
            lambda credentials: (_ for _ in ()).throw(TransientProviderError("503")),
        )
        cuenta = connected_accounts[Platform.INSTAGRAM]
        credenciales = ensure_fresh_credentials(db, cuenta, force=True)
        assert credenciales.access_token == "token-instagram"
        db.expire_all()
        assert db.get(SocialAccount, cuenta.id).is_active is True

    def test_desconectar_borra_los_tokens(
        self, db, api_client, connected_accounts, fake_providers
    ) -> None:
        client, _record, _key = api_client
        cuenta = connected_accounts[Platform.TIKTOK]
        response = client.delete(f"/v1/accounts/{cuenta.id}")
        assert response.status_code == 200
        assert fake_providers[Platform.TIKTOK].revoke_calls == 1

        db.expire_all()
        actualizada = db.get(SocialAccount, cuenta.id)
        assert actualizada.is_active is False
        assert actualizada.disconnected_at is not None
        assert actualizada.refresh_token_encrypted is None
        from app.security.crypto import decrypt

        assert decrypt(actualizada.access_token_encrypted) == ""

    def test_desconectar_sin_revocar(self, api_client, connected_accounts, fake_providers) -> None:
        client, _record, _key = api_client
        cuenta = connected_accounts[Platform.TIKTOK]
        client.delete(f"/v1/accounts/{cuenta.id}?revoke=false")
        assert fake_providers[Platform.TIKTOK].revoke_calls == 0

    def test_no_se_puede_publicar_con_una_cuenta_desconectada(
        self, api_client, connected_accounts, fake_providers, db
    ) -> None:
        import io

        from tests.conftest import make_video_bytes

        client, _record, _key = api_client
        client.delete(f"/v1/accounts/{connected_accounts[Platform.INSTAGRAM].id}")

        media_id = client.post(
            "/v1/media", files={"file": ("x.mp4", io.BytesIO(make_video_bytes()), "video/mp4")}
        ).json()["id"]
        response = client.post("/v1/posts", json={"media_id": media_id, "platforms": ["instagram"]})
        assert response.status_code == 409
        assert response.json()["error"] == "no_connected_accounts"

    def test_tarea_de_refresco_proactivo_de_tokens(
        self, db, api_client, connected_accounts, fake_providers
    ) -> None:
        from app.workers.tasks import refresh_expiring_tokens

        # Ninguno caduca en 48 h.
        assert refresh_expiring_tokens()["refreshed"] == 0

        cuenta = connected_accounts[Platform.YOUTUBE]
        cuenta.token_expiration = utcnow() + timedelta(hours=1)
        db.add(cuenta)
        db.commit()

        assert refresh_expiring_tokens()["refreshed"] == 1
        assert fake_providers[Platform.YOUTUBE].refresh_calls == 1

    def test_creator_info_solo_para_tiktok(
        self, api_client, connected_accounts, fake_providers
    ) -> None:
        client, _record, _key = api_client
        response = client.get(
            f"/v1/accounts/{connected_accounts[Platform.INSTAGRAM].id}/creator-info"
        )
        assert response.status_code == 400

    def test_publishing_limit_solo_para_instagram(
        self, api_client, connected_accounts, fake_providers
    ) -> None:
        client, _record, _key = api_client
        response = client.get(
            f"/v1/accounts/{connected_accounts[Platform.TIKTOK].id}/publishing-limit"
        )
        assert response.status_code == 400


def test_la_purga_borra_los_states_caducados(db, api_client, fake_providers) -> None:
    from app.workers.tasks import purge_oauth_states

    client, _record, _key = api_client
    state = client.get("/v1/oauth/instagram/authorize").json()["state"]

    assert purge_oauth_states()["deleted"] == 0

    registro = db.scalars(select(OAuthState).where(OAuthState.state == state)).one()
    registro.expires_at = utcnow() - timedelta(minutes=1)
    db.add(registro)
    db.commit()

    assert purge_oauth_states()["deleted"] == 1
