"""InstagramProvider contra respuestas HTTP simuladas (respx).

Verifica que se llaman los endpoints OFICIALES con los parámetros correctos.
Ninguna petición sale a Internet.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.config import settings
from app.providers.base import OAuthCredentials, PublishRequest, VideoSource
from app.providers.errors import (
    AuthenticationError,
    InvalidVideoError,
    PermanentProviderError,
    ProcessingTimeoutError,
    RateLimitError,
    TransientProviderError,
)
from app.providers.instagram import InstagramProvider

GRAPH = "https://graph.instagram.com"
VERSION = settings.instagram_graph_version
BASE = f"{GRAPH}/{VERSION}"
RUPLOAD = f"https://rupload.facebook.com/ig-api-upload/{VERSION}"

IG_USER = "17841400000000000"
CONTAINER = "18000000000000000"
MEDIA_ID = "17999000000000000"


@pytest.fixture
def provider() -> InstagramProvider:
    return InstagramProvider()


@pytest.fixture
def credentials() -> OAuthCredentials:
    return OAuthCredentials(access_token="IGQ-token", metadata={"external_account_id": IG_USER})


def _publish_request(**kwargs) -> PublishRequest:
    video = VideoSource(
        filename="reel.mp4",
        content_type="video/mp4",
        size_bytes=1024,
        open_stream=lambda: iter([b"x" * 1024]),
        **kwargs.pop("video_kwargs", {}),
    )
    return PublishRequest(
        video=video, caption="Mi reel #test", options={"ig_user_id": IG_USER}, **kwargs
    )


class TestConfiguracion:
    def test_esta_configurado_con_credenciales(self, provider: InstagramProvider) -> None:
        assert provider.is_configured()

    def test_sin_credenciales_lanza_configuration_error(
        self, provider: InstagramProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.providers.errors import ConfigurationError

        monkeypatch.setattr(settings, "instagram_app_id", "")
        with pytest.raises(ConfigurationError, match="INSTAGRAM_APP_ID"):
            provider.build_authorization_request(state="s", redirect_uri="https://x/cb")

    def test_url_de_autorizacion_usa_el_endpoint_oficial(self, provider: InstagramProvider) -> None:
        request = provider.build_authorization_request(
            state="estado123", redirect_uri="https://api.test/cb"
        )
        assert request.url.startswith("https://www.instagram.com/oauth/authorize?")
        assert "client_id=test-ig-app" in request.url
        assert "response_type=code" in request.url
        assert "instagram_business_basic" in request.url
        assert "instagram_business_content_publish" in request.url
        assert "state=estado123" in request.url


class TestOAuth:
    @respx.mock
    def test_canjea_code_por_token_de_larga_duracion(self, provider: InstagramProvider) -> None:
        respx.post("https://api.instagram.com/oauth/access_token").mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "token-corto",
                    "user_id": 17841400000000000,
                    "permissions": "instagram_business_basic,instagram_business_content_publish",
                },
            )
        )
        respx.get(f"{GRAPH}/access_token").mock(
            return_value=httpx.Response(
                200, json={"access_token": "token-largo-60-dias", "expires_in": 5184000}
            )
        )

        credentials = provider.exchange_code(code="abc", redirect_uri="https://api.test/cb")
        assert credentials.access_token == "token-largo-60-dias"
        assert credentials.expires_at is not None
        assert "instagram_business_content_publish" in credentials.scopes
        assert credentials.metadata["login_mode"] == "instagram"

    @respx.mock
    def test_refresh_usa_ig_refresh_token(
        self, provider: InstagramProvider, credentials: OAuthCredentials
    ) -> None:
        ruta = respx.get(f"{GRAPH}/refresh_access_token").mock(
            return_value=httpx.Response(
                200, json={"access_token": "token-renovado", "expires_in": 5184000}
            )
        )
        renovado = provider.refresh_token(credentials)
        assert renovado.access_token == "token-renovado"
        assert "grant_type=ig_refresh_token" in str(ruta.calls[0].request.url)

    @respx.mock
    def test_refresh_fallido_lanza_authentication_error(
        self, provider: InstagramProvider, credentials: OAuthCredentials
    ) -> None:
        respx.get(f"{GRAPH}/refresh_access_token").mock(
            return_value=httpx.Response(
                400,
                json={"error": {"message": "Sesión caducada", "code": 190}},
            )
        )
        with pytest.raises(AuthenticationError):
            provider.refresh_token(credentials)


class TestCuenta:
    @respx.mock
    def test_obtiene_cuenta_profesional(
        self, provider: InstagramProvider, credentials: OAuthCredentials
    ) -> None:
        respx.get(f"{BASE}/me").mock(
            return_value=httpx.Response(
                200,
                json={
                    "user_id": IG_USER,
                    "username": "mi_marca",
                    "account_type": "BUSINESS",
                    "media_count": 42,
                },
            )
        )
        info = provider.get_account(credentials)
        assert info.external_account_id == IG_USER
        assert info.account_name == "mi_marca"
        assert info.metadata["account_type"] == "BUSINESS"

    @respx.mock
    def test_rechaza_cuenta_personal(
        self, provider: InstagramProvider, credentials: OAuthCredentials
    ) -> None:
        """Requisito de la plataforma: sólo cuentas Professional publican."""
        respx.get(f"{BASE}/me").mock(
            return_value=httpx.Response(
                200,
                json={"user_id": IG_USER, "username": "personal", "account_type": "PERSONAL"},
            )
        )
        with pytest.raises(PermanentProviderError, match="Professional"):
            provider.get_account(credentials)

    @respx.mock
    def test_acepta_cuenta_creator(
        self, provider: InstagramProvider, credentials: OAuthCredentials
    ) -> None:
        respx.get(f"{BASE}/me").mock(
            return_value=httpx.Response(
                200,
                json={"user_id": IG_USER, "username": "creador", "account_type": "CREATOR"},
            )
        )
        assert provider.get_account(credentials).account_name == "creador"

    @respx.mock
    def test_consulta_el_limite_de_publicacion(
        self, provider: InstagramProvider, credentials: OAuthCredentials
    ) -> None:
        respx.get(f"{BASE}/{IG_USER}/content_publishing_limit").mock(
            return_value=httpx.Response(
                200, json={"data": [{"quota_usage": 7, "config": {"quota_total": 100}}]}
            )
        )
        limite = provider.get_publishing_limit(credentials, IG_USER)
        assert limite["quota_usage"] == 7
        assert limite["config"]["quota_total"] == 100


class TestPublicacion:
    @respx.mock
    def test_flujo_completo_con_video_url(
        self, provider: InstagramProvider, credentials: OAuthCredentials
    ) -> None:
        """Los 3 pasos oficiales: /media → status_code → /media_publish."""
        crear = respx.post(f"{BASE}/{IG_USER}/media").mock(
            return_value=httpx.Response(200, json={"id": CONTAINER})
        )
        respx.get(f"{BASE}/{CONTAINER}").mock(
            return_value=httpx.Response(200, json={"status_code": "FINISHED"})
        )
        publicar = respx.post(f"{BASE}/{IG_USER}/media_publish").mock(
            return_value=httpx.Response(200, json={"id": MEDIA_ID})
        )
        respx.get(f"{BASE}/{MEDIA_ID}").mock(
            return_value=httpx.Response(
                200, json={"permalink": "https://www.instagram.com/reel/ABC/"}
            )
        )

        request = _publish_request()
        request.video.public_url = "https://cdn.test/reel.mp4"
        resultado = provider.publish(credentials, request)

        assert resultado.external_post_id == MEDIA_ID
        assert resultado.external_url == "https://www.instagram.com/reel/ABC/"

        cuerpo_crear = dict(
            pair.split("=", 1) for pair in crear.calls[0].request.content.decode().split("&")
        )
        assert cuerpo_crear["media_type"] == "REELS"
        assert "video_url" in cuerpo_crear
        assert f"creation_id={CONTAINER}" in publicar.calls[0].request.content.decode()

    @respx.mock
    def test_flujo_con_upload_resumible(
        self, provider: InstagramProvider, credentials: OAuthCredentials
    ) -> None:
        """Sin URL pública se usa rupload.facebook.com con offset y file_size."""
        crear = respx.post(f"{BASE}/{IG_USER}/media").mock(
            return_value=httpx.Response(200, json={"id": CONTAINER})
        )
        subir = respx.post(f"{RUPLOAD}/{CONTAINER}").mock(
            return_value=httpx.Response(200, json={"success": True})
        )
        respx.get(f"{BASE}/{CONTAINER}").mock(
            return_value=httpx.Response(200, json={"status_code": "FINISHED"})
        )
        respx.post(f"{BASE}/{IG_USER}/media_publish").mock(
            return_value=httpx.Response(200, json={"id": MEDIA_ID})
        )
        respx.get(f"{BASE}/{MEDIA_ID}").mock(return_value=httpx.Response(200, json={}))

        resultado = provider.publish(credentials, _publish_request())
        assert resultado.external_post_id == MEDIA_ID

        assert "upload_type=resumable" in crear.calls[0].request.content.decode()
        cabeceras = subir.calls[0].request.headers
        assert cabeceras["authorization"] == "OAuth IGQ-token"
        assert cabeceras["offset"] == "0"
        assert cabeceras["file_size"] == "1024"

    @respx.mock
    def test_espera_mientras_esta_in_progress(
        self,
        provider: InstagramProvider,
        credentials: OAuthCredentials,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Plazo amplio para que quepan dos consultas con el intervalo mínimo.
        monkeypatch.setattr(settings, "processing_timeout_seconds", 20)
        respx.post(f"{BASE}/{IG_USER}/media").mock(
            return_value=httpx.Response(200, json={"id": CONTAINER})
        )
        respx.post(f"{RUPLOAD}/{CONTAINER}").mock(
            return_value=httpx.Response(200, json={"success": True})
        )
        estado = respx.get(f"{BASE}/{CONTAINER}").mock(
            side_effect=[
                httpx.Response(200, json={"status_code": "IN_PROGRESS"}),
                httpx.Response(200, json={"status_code": "FINISHED"}),
            ]
        )
        respx.post(f"{BASE}/{IG_USER}/media_publish").mock(
            return_value=httpx.Response(200, json={"id": MEDIA_ID})
        )
        respx.get(f"{BASE}/{MEDIA_ID}").mock(return_value=httpx.Response(200, json={}))

        provider.publish(credentials, _publish_request())
        assert estado.call_count == 2

    @respx.mock
    def test_status_code_error_es_video_invalido(
        self, provider: InstagramProvider, credentials: OAuthCredentials
    ) -> None:
        respx.post(f"{BASE}/{IG_USER}/media").mock(
            return_value=httpx.Response(200, json={"id": CONTAINER})
        )
        respx.post(f"{RUPLOAD}/{CONTAINER}").mock(
            return_value=httpx.Response(200, json={"success": True})
        )
        respx.get(f"{BASE}/{CONTAINER}").mock(
            return_value=httpx.Response(
                200, json={"status_code": "ERROR", "status": "El video es demasiado largo"}
            )
        )
        with pytest.raises(InvalidVideoError, match="demasiado largo"):
            provider.publish(credentials, _publish_request())

    @respx.mock
    def test_contenedor_expirado_es_error_permanente(
        self, provider: InstagramProvider, credentials: OAuthCredentials
    ) -> None:
        respx.get(f"{BASE}/{CONTAINER}").mock(
            return_value=httpx.Response(200, json={"status_code": "EXPIRED"})
        )
        with pytest.raises(PermanentProviderError, match="expiró"):
            provider.wait_for_container(credentials, CONTAINER)

    @respx.mock
    def test_timeout_de_procesado(
        self, provider: InstagramProvider, credentials: OAuthCredentials
    ) -> None:
        respx.get(f"{BASE}/{CONTAINER}").mock(
            return_value=httpx.Response(200, json={"status_code": "IN_PROGRESS"})
        )
        with pytest.raises(ProcessingTimeoutError):
            provider.wait_for_container(credentials, CONTAINER)

    @respx.mock
    def test_reanuda_con_el_container_id_guardado(
        self, provider: InstagramProvider, credentials: OAuthCredentials
    ) -> None:
        """En un reintento no se vuelve a crear el contenedor ni a subir."""
        crear = respx.post(f"{BASE}/{IG_USER}/media").mock(
            return_value=httpx.Response(200, json={"id": "OTRO"})
        )
        respx.get(f"{BASE}/{CONTAINER}").mock(
            return_value=httpx.Response(200, json={"status_code": "FINISHED"})
        )
        respx.post(f"{BASE}/{IG_USER}/media_publish").mock(
            return_value=httpx.Response(200, json={"id": MEDIA_ID})
        )
        respx.get(f"{BASE}/{MEDIA_ID}").mock(return_value=httpx.Response(200, json={}))

        request = _publish_request()
        request.state = {"container_id": CONTAINER, "uploaded": True}
        provider.publish(credentials, request)
        assert crear.call_count == 0


class TestErroresDeMeta:
    @pytest.mark.parametrize(
        ("payload", "tipo"),
        [
            ({"error": {"code": 190, "message": "Token inválido"}}, AuthenticationError),
            ({"error": {"code": 4, "message": "Demasiadas llamadas"}}, RateLimitError),
            ({"error": {"code": 32, "message": "Límite de página"}}, RateLimitError),
            (
                {"error": {"code": 100, "error_subcode": 2207026, "message": "Formato no válido"}},
                InvalidVideoError,
            ),
            ({"error": {"code": 1, "message": "API desconocida"}}, TransientProviderError),
            ({"error": {"code": 100, "message": "Parámetro inválido"}}, PermanentProviderError),
        ],
    )
    @respx.mock
    def test_clasifica_los_codigos_de_meta(
        self,
        provider: InstagramProvider,
        credentials: OAuthCredentials,
        payload: dict,
        tipo: type,
    ) -> None:
        respx.post(f"{BASE}/{IG_USER}/media").mock(return_value=httpx.Response(400, json=payload))
        with pytest.raises(tipo):
            provider.create_media_container(
                credentials, IG_USER, video_url="https://cdn.test/v.mp4"
            )

    @respx.mock
    def test_un_500_de_meta_es_temporal(
        self, provider: InstagramProvider, credentials: OAuthCredentials
    ) -> None:
        respx.post(f"{BASE}/{IG_USER}/media").mock(
            return_value=httpx.Response(500, json={"error": {"message": "Oops", "code": 2}})
        )
        with pytest.raises(TransientProviderError):
            provider.create_media_container(
                credentials, IG_USER, video_url="https://cdn.test/v.mp4"
            )

    @respx.mock
    def test_un_timeout_de_red_es_temporal(
        self, provider: InstagramProvider, credentials: OAuthCredentials
    ) -> None:
        respx.post(f"{BASE}/{IG_USER}/media").mock(side_effect=httpx.ConnectTimeout("timeout"))
        with pytest.raises(TransientProviderError, match="Timeout"):
            provider.create_media_container(
                credentials, IG_USER, video_url="https://cdn.test/v.mp4"
            )

    @respx.mock
    def test_el_error_de_permalink_no_rompe_la_publicacion(
        self, provider: InstagramProvider, credentials: OAuthCredentials
    ) -> None:
        respx.post(f"{BASE}/{IG_USER}/media").mock(
            return_value=httpx.Response(200, json={"id": CONTAINER})
        )
        respx.post(f"{RUPLOAD}/{CONTAINER}").mock(
            return_value=httpx.Response(200, json={"success": True})
        )
        respx.get(f"{BASE}/{CONTAINER}").mock(
            return_value=httpx.Response(200, json={"status_code": "FINISHED"})
        )
        respx.post(f"{BASE}/{IG_USER}/media_publish").mock(
            return_value=httpx.Response(200, json={"id": MEDIA_ID})
        )
        respx.get(f"{BASE}/{MEDIA_ID}").mock(
            return_value=httpx.Response(400, json={"error": {"code": 100, "message": "no"}})
        )
        resultado = provider.publish(credentials, _publish_request())
        assert resultado.external_post_id == MEDIA_ID
        assert resultado.external_url is None


class TestLoginConFacebook:
    @pytest.fixture(autouse=True)
    def _modo_facebook(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "instagram_login_mode", "facebook")

    def test_url_de_autorizacion_de_facebook(self, provider: InstagramProvider) -> None:
        request = provider.build_authorization_request(state="s", redirect_uri="https://x/cb")
        assert request.url.startswith(f"https://www.facebook.com/{VERSION}/dialog/oauth?")
        assert "instagram_content_publish" in request.url

    @respx.mock
    def test_localiza_la_cuenta_ig_por_la_pagina(self, provider: InstagramProvider) -> None:
        fb_base = f"https://graph.facebook.com/{VERSION}"
        respx.get(f"{fb_base}/me/accounts").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {"id": "page-sin-ig", "name": "Otra página"},
                        {
                            "id": "page-1",
                            "name": "Mi página",
                            "access_token": "token-de-pagina",
                            "instagram_business_account": {"id": IG_USER, "username": "mi_marca"},
                        },
                    ]
                },
            )
        )
        credentials = OAuthCredentials(access_token="fb-token", metadata={"login_mode": "facebook"})
        info = provider.get_account(credentials)
        assert info.external_account_id == IG_USER
        assert info.metadata["page_id"] == "page-1"
        assert info.metadata["page_access_token"] == "token-de-pagina"

    @respx.mock
    def test_error_si_ninguna_pagina_tiene_instagram(self, provider: InstagramProvider) -> None:
        fb_base = f"https://graph.facebook.com/{VERSION}"
        respx.get(f"{fb_base}/me/accounts").mock(
            return_value=httpx.Response(200, json={"data": [{"id": "p", "name": "Sin IG"}]})
        )
        credentials = OAuthCredentials(access_token="fb-token", metadata={"login_mode": "facebook"})
        with pytest.raises(PermanentProviderError, match="Professional"):
            provider.get_account(credentials)

    def test_publica_con_el_token_de_pagina(self, provider: InstagramProvider) -> None:
        credentials = OAuthCredentials(
            access_token="user-token",
            metadata={"login_mode": "facebook", "page_access_token": "page-token"},
        )
        assert provider._publishing_token(credentials) == "page-token"
