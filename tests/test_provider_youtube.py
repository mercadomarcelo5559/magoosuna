"""YouTubeProvider contra respuestas HTTP simuladas (respx)."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.config import settings
from app.providers.base import OAuthCredentials, PublishRequest, VideoSource
from app.providers.errors import (
    AuthenticationError,
    ConfigurationError,
    InvalidVideoError,
    PermanentProviderError,
    ProcessingTimeoutError,
    RateLimitError,
    TransientProviderError,
)
from app.providers.youtube import YouTubeProvider

API = "https://www.googleapis.com/youtube/v3"
UPLOAD = "https://www.googleapis.com/upload/youtube/v3"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SESSION_URL = "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=xyz"
VIDEO_ID = "dQw4w9WgXcQ"
CHANNEL_ID = "UC1234567890"


@pytest.fixture
def provider() -> YouTubeProvider:
    return YouTubeProvider()


@pytest.fixture
def credentials() -> OAuthCredentials:
    return OAuthCredentials(access_token="ya29.token", refresh_token="1//refresh")


def _request(size: int = 4096, **kwargs) -> PublishRequest:
    video = VideoSource(
        filename="v.mp4",
        content_type="video/mp4",
        size_bytes=size,
        open_stream=lambda: iter([b"z" * size]),
    )
    return PublishRequest(
        video=video,
        title="Mi título",
        description="Mi descripción",
        tags=["tag1", "tag2"],
        **kwargs,
    )


class TestOAuth:
    def test_url_de_consentimiento_pide_offline_y_consent(self, provider: YouTubeProvider) -> None:
        """Sin `access_type=offline` Google no devuelve refresh token."""
        request = provider.build_authorization_request(
            state="st", redirect_uri="https://api.test/cb"
        )
        assert request.url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
        assert "access_type=offline" in request.url
        assert "prompt=consent" in request.url
        assert "youtube.upload" in request.url
        assert "client_id=test-yt-id" in request.url

    def test_sin_credenciales_lanza_configuration_error(
        self, provider: YouTubeProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "youtube_client_id", "")
        with pytest.raises(ConfigurationError, match="YOUTUBE_CLIENT_ID"):
            provider.build_authorization_request(state="s", redirect_uri="https://x/cb")

    @respx.mock
    def test_canjea_code(self, provider: YouTubeProvider) -> None:
        respx.post(TOKEN_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "ya29.nuevo",
                    "refresh_token": "1//nuevo",
                    "expires_in": 3599,
                    "scope": "https://www.googleapis.com/auth/youtube.upload",
                    "token_type": "Bearer",
                },
            )
        )
        credentials = provider.exchange_code(code="c", redirect_uri="https://api.test/cb")
        assert credentials.access_token == "ya29.nuevo"
        assert credentials.refresh_token == "1//nuevo"
        assert credentials.expires_at is not None

    @respx.mock
    def test_sin_refresh_token_avisa_como_reautorizar(self, provider: YouTubeProvider) -> None:
        respx.post(TOKEN_URL).mock(
            return_value=httpx.Response(200, json={"access_token": "ya29.solo", "expires_in": 3599})
        )
        with pytest.raises(AuthenticationError, match="myaccount.google.com/permissions"):
            provider.exchange_code(code="c", redirect_uri="https://api.test/cb")

    @respx.mock
    def test_refresh_conserva_el_refresh_token(
        self, provider: YouTubeProvider, credentials: OAuthCredentials
    ) -> None:
        """Google no rota el refresh token en cada renovación."""
        ruta = respx.post(TOKEN_URL).mock(
            return_value=httpx.Response(
                200, json={"access_token": "ya29.renovado", "expires_in": 3599}
            )
        )
        renovado = provider.refresh_token(credentials)
        assert renovado.access_token == "ya29.renovado"
        assert renovado.refresh_token == "1//refresh"
        assert "grant_type=refresh_token" in ruta.calls[0].request.content.decode()

    @respx.mock
    def test_invalid_grant_pide_reconectar(
        self, provider: YouTubeProvider, credentials: OAuthCredentials
    ) -> None:
        respx.post(TOKEN_URL).mock(
            return_value=httpx.Response(
                400, json={"error": "invalid_grant", "error_description": "Token revocado"}
            )
        )
        with pytest.raises(AuthenticationError, match="reconecta"):
            provider.refresh_token(credentials)

    def test_sin_refresh_token_almacenado(self, provider: YouTubeProvider) -> None:
        with pytest.raises(AuthenticationError, match="reconéctalo"):
            provider.refresh_token(OAuthCredentials(access_token="a"))


class TestCanal:
    @respx.mock
    def test_obtiene_el_canal(
        self, provider: YouTubeProvider, credentials: OAuthCredentials
    ) -> None:
        respx.get(f"{API}/channels").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": CHANNEL_ID,
                            "snippet": {"title": "Mi Canal", "customUrl": "@micanal"},
                            "contentDetails": {"relatedPlaylists": {"uploads": "UU123"}},
                            "statistics": {"subscriberCount": "1234"},
                        }
                    ]
                },
            )
        )
        info = provider.get_account(credentials)
        assert info.external_account_id == CHANNEL_ID
        assert info.account_name == "Mi Canal"
        assert info.metadata["uploads_playlist"] == "UU123"

    @respx.mock
    def test_sin_canal_avisa_como_crearlo(
        self, provider: YouTubeProvider, credentials: OAuthCredentials
    ) -> None:
        respx.get(f"{API}/channels").mock(return_value=httpx.Response(200, json={"items": []}))
        with pytest.raises(PermanentProviderError, match="create_channel"):
            provider.get_account(credentials)


class TestSubida:
    @respx.mock
    def test_flujo_resumible_completo(
        self, provider: YouTubeProvider, credentials: OAuthCredentials
    ) -> None:
        sesion = respx.post(f"{UPLOAD}/videos").mock(
            return_value=httpx.Response(200, headers={"Location": SESSION_URL})
        )
        subida = respx.put(SESSION_URL).mock(
            return_value=httpx.Response(200, json={"id": VIDEO_ID})
        )
        respx.get(f"{API}/videos").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "status": {"uploadStatus": "processed", "privacyStatus": "private"},
                            "processingDetails": {"processingStatus": "succeeded"},
                        }
                    ]
                },
            )
        )

        resultado = provider.publish(credentials, _request())
        assert resultado.external_post_id == VIDEO_ID
        assert resultado.external_url == f"https://www.youtube.com/watch?v={VIDEO_ID}"
        assert resultado.metadata["short_url"] == f"https://youtu.be/{VIDEO_ID}"

        peticion = sesion.calls[0].request
        assert "uploadType=resumable" in str(peticion.url)
        assert "part=snippet%2Cstatus" in str(peticion.url)
        assert peticion.headers["x-upload-content-length"] == "4096"

        cuerpo = json.loads(peticion.content)
        assert cuerpo["snippet"]["title"] == "Mi título"
        assert cuerpo["snippet"]["description"] == "Mi descripción"
        assert cuerpo["snippet"]["tags"] == ["tag1", "tag2"]
        assert cuerpo["status"]["privacyStatus"] == "private"  # valor por defecto

        assert subida.calls[0].request.headers["content-range"] == "bytes 0-4095/4096"

    @respx.mock
    def test_privacidad_configurable(
        self, provider: YouTubeProvider, credentials: OAuthCredentials
    ) -> None:
        sesion = respx.post(f"{UPLOAD}/videos").mock(
            return_value=httpx.Response(200, headers={"Location": SESSION_URL})
        )
        respx.put(SESSION_URL).mock(return_value=httpx.Response(200, json={"id": VIDEO_ID}))
        respx.get(f"{API}/videos").mock(
            return_value=httpx.Response(
                200, json={"items": [{"status": {"uploadStatus": "processed"}}]}
            )
        )
        provider.publish(credentials, _request(options={"privacy_status": "public"}))
        cuerpo = json.loads(sesion.calls[0].request.content)
        assert cuerpo["status"]["privacyStatus"] == "public"

    @respx.mock
    def test_publish_at_fuerza_privado(
        self, provider: YouTubeProvider, credentials: OAuthCredentials
    ) -> None:
        """La API de YouTube exige privacyStatus=private junto con publishAt."""
        sesion = respx.post(f"{UPLOAD}/videos").mock(
            return_value=httpx.Response(200, headers={"Location": SESSION_URL})
        )
        respx.put(SESSION_URL).mock(return_value=httpx.Response(200, json={"id": VIDEO_ID}))
        respx.get(f"{API}/videos").mock(
            return_value=httpx.Response(
                200, json={"items": [{"status": {"uploadStatus": "processed"}}]}
            )
        )
        provider.publish(
            credentials,
            _request(options={"privacy_status": "public", "publish_at": "2027-01-01T10:00:00Z"}),
        )
        cuerpo = json.loads(sesion.calls[0].request.content)
        assert cuerpo["status"]["privacyStatus"] == "private"
        assert cuerpo["status"]["publishAt"] == "2027-01-01T10:00:00Z"

    def test_privacidad_invalida(
        self, provider: YouTubeProvider, credentials: OAuthCredentials
    ) -> None:
        with pytest.raises(ConfigurationError, match="privacy_status"):
            provider._build_body(_request(options={"privacy_status": "secreto"}))

    def test_los_tags_se_recortan_a_500_caracteres(self, provider: YouTubeProvider) -> None:
        request = _request()
        request.tags = [f"tag{i:03d}" * 5 for i in range(30)]
        cuerpo = provider._build_body(request)
        tags = cuerpo["snippet"]["tags"]
        assert sum(len(t) + 1 for t in tags) <= 500
        assert len(tags) < 30

    def test_el_titulo_se_recorta_a_100_caracteres(self, provider: YouTubeProvider) -> None:
        request = _request()
        request.title = "T" * 250
        assert len(provider._build_body(request)["snippet"]["title"]) == 100

    @respx.mock
    def test_chunk_308_continua_la_subida(
        self, provider: YouTubeProvider, credentials: OAuthCredentials
    ) -> None:
        """308 (Resume Incomplete) significa que el chunk se aceptó."""
        from app.providers.youtube.provider import UPLOAD_CHUNK_SIZE

        size = UPLOAD_CHUNK_SIZE + 1024
        respx.post(f"{UPLOAD}/videos").mock(
            return_value=httpx.Response(200, headers={"Location": SESSION_URL})
        )
        subida = respx.put(SESSION_URL).mock(
            side_effect=[
                httpx.Response(308, headers={"Range": f"bytes=0-{UPLOAD_CHUNK_SIZE - 1}"}),
                httpx.Response(200, json={"id": VIDEO_ID}),
            ]
        )
        respx.get(f"{API}/videos").mock(
            return_value=httpx.Response(
                200, json={"items": [{"status": {"uploadStatus": "processed"}}]}
            )
        )
        video = VideoSource(
            filename="grande.mp4",
            content_type="video/mp4",
            size_bytes=size,
            open_stream=lambda: iter([b"a" * size]),
        )
        request = PublishRequest(video=video, title="Grande")
        resultado = provider.publish(credentials, request)
        assert resultado.external_post_id == VIDEO_ID
        assert subida.call_count == 2

    @respx.mock
    def test_sin_location_es_error_temporal(
        self, provider: YouTubeProvider, credentials: OAuthCredentials
    ) -> None:
        respx.post(f"{UPLOAD}/videos").mock(return_value=httpx.Response(200))
        with pytest.raises(TransientProviderError, match="URL de sesión"):
            provider.create_upload_session(credentials, _request())

    def test_sin_fichero_no_se_puede_publicar(
        self, provider: YouTubeProvider, credentials: OAuthCredentials
    ) -> None:
        """YouTube no acepta publicar desde URL: necesita el fichero."""
        video = VideoSource(filename="v.mp4", content_type="video/mp4", size_bytes=10)
        video.public_url = "https://cdn.test/v.mp4"
        with pytest.raises(ConfigurationError, match="requiere el fichero"):
            provider.publish(credentials, PublishRequest(video=video))

    @respx.mock
    def test_reanuda_con_la_sesion_guardada(
        self, provider: YouTubeProvider, credentials: OAuthCredentials
    ) -> None:
        sesion = respx.post(f"{UPLOAD}/videos").mock(
            return_value=httpx.Response(200, headers={"Location": "otra"})
        )
        respx.put(SESSION_URL).mock(return_value=httpx.Response(200, json={"id": VIDEO_ID}))
        respx.get(f"{API}/videos").mock(
            return_value=httpx.Response(
                200, json={"items": [{"status": {"uploadStatus": "processed"}}]}
            )
        )
        request = _request()
        request.state = {"session_url": SESSION_URL}
        provider.publish(credentials, request)
        assert sesion.call_count == 0


class TestEstadosYErrores:
    @respx.mock
    def test_video_rechazado(
        self, provider: YouTubeProvider, credentials: OAuthCredentials
    ) -> None:
        respx.get(f"{API}/videos").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "status": {
                                "uploadStatus": "rejected",
                                "rejectionReason": "copyright",
                            }
                        }
                    ]
                },
            )
        )
        with pytest.raises(InvalidVideoError, match="copyright"):
            provider.wait_for_processing(credentials, VIDEO_ID)

    @respx.mock
    def test_timeout_de_procesado(
        self, provider: YouTubeProvider, credentials: OAuthCredentials
    ) -> None:
        respx.get(f"{API}/videos").mock(
            return_value=httpx.Response(
                200, json={"items": [{"status": {"uploadStatus": "uploaded"}}]}
            )
        )
        with pytest.raises(ProcessingTimeoutError):
            provider.wait_for_processing(credentials, VIDEO_ID)

    @respx.mock
    def test_video_no_encontrado(
        self, provider: YouTubeProvider, credentials: OAuthCredentials
    ) -> None:
        respx.get(f"{API}/videos").mock(return_value=httpx.Response(200, json={"items": []}))
        estado = provider.get_post_status(credentials, VIDEO_ID)
        assert estado.state == "not_found"
        assert estado.is_final

    @pytest.mark.parametrize(
        ("reason", "status_code", "tipo"),
        [
            ("quotaExceeded", 403, RateLimitError),
            ("dailyLimitExceeded", 403, RateLimitError),
            ("uploadLimitExceeded", 400, RateLimitError),
            ("authError", 401, AuthenticationError),
            ("youtubeSignupRequired", 401, AuthenticationError),
            ("invalidVideoMetadata", 400, InvalidVideoError),
            ("backendError", 503, TransientProviderError),
            ("invalidFilter", 400, PermanentProviderError),
        ],
    )
    @respx.mock
    def test_clasifica_los_errores_de_google(
        self,
        provider: YouTubeProvider,
        credentials: OAuthCredentials,
        reason: str,
        status_code: int,
        tipo: type,
    ) -> None:
        respx.get(f"{API}/channels").mock(
            return_value=httpx.Response(
                status_code,
                json={
                    "error": {
                        "code": status_code,
                        "message": f"fallo {reason}",
                        "errors": [{"reason": reason, "domain": "youtube"}],
                    }
                },
            )
        )
        with pytest.raises(tipo):
            provider.get_account(credentials)

    @respx.mock
    def test_el_error_de_cuota_menciona_la_consola(
        self, provider: YouTubeProvider, credentials: OAuthCredentials
    ) -> None:
        respx.get(f"{API}/channels").mock(
            return_value=httpx.Response(
                403,
                json={
                    "error": {
                        "code": 403,
                        "message": "Cuota agotada",
                        "errors": [{"reason": "quotaExceeded"}],
                    }
                },
            )
        )
        with pytest.raises(RateLimitError, match="quotas"):
            provider.get_account(credentials)
