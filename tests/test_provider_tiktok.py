"""TikTokProvider contra respuestas HTTP simuladas (respx)."""

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
from app.providers.tiktok import TikTokProvider
from app.providers.tiktok.provider import MAX_CHUNK_SIZE, WHOLE_FILE_LIMIT

API = "https://open.tiktokapis.com"
PUBLISH_ID = "v_pub_url~v2.123456789"

CREATOR_INFO = {
    "creator_username": "mi_usuario",
    "creator_nickname": "Mi Marca",
    "creator_avatar_url": "https://p16.tiktokcdn.com/avatar.jpeg",
    "privacy_level_options": ["PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "SELF_ONLY"],
    "comment_disabled": False,
    "duet_disabled": False,
    "stitch_disabled": True,
    "max_video_post_duration_sec": 300,
}


@pytest.fixture
def provider() -> TikTokProvider:
    return TikTokProvider()


@pytest.fixture
def credentials() -> OAuthCredentials:
    return OAuthCredentials(
        access_token="act.tiktok-token",
        refresh_token="rft.tiktok-refresh",
        metadata={"open_id": "open-id-123"},
    )


def _request(size: int = 2048, **kwargs) -> PublishRequest:
    video = VideoSource(
        filename="v.mp4",
        content_type="video/mp4",
        size_bytes=size,
        open_stream=lambda: iter([b"y" * size]),
    )
    return PublishRequest(video=video, caption="Mi TikTok #test", **kwargs)


class TestOAuth:
    def test_url_de_autorizacion_oficial(self, provider: TikTokProvider) -> None:
        request = provider.build_authorization_request(
            state="st", redirect_uri="https://api.test/cb"
        )
        assert request.url.startswith("https://www.tiktok.com/v2/auth/authorize/?")
        assert "client_key=test-tt-key" in request.url
        assert "response_type=code" in request.url
        assert "video.publish" in request.url
        assert "state=st" in request.url

    @respx.mock
    def test_canjea_code(self, provider: TikTokProvider) -> None:
        ruta = respx.post(f"{API}/v2/oauth/token/").mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "act.nuevo",
                    "refresh_token": "rft.nuevo",
                    "expires_in": 86400,
                    "refresh_expires_in": 31536000,
                    "open_id": "open-id-123",
                    "scope": "user.info.basic,video.publish",
                    "token_type": "Bearer",
                },
            )
        )
        credentials = provider.exchange_code(code="c", redirect_uri="https://api.test/cb")
        assert credentials.access_token == "act.nuevo"
        assert credentials.refresh_token == "rft.nuevo"
        assert credentials.scopes == ["user.info.basic", "video.publish"]
        assert credentials.metadata["open_id"] == "open-id-123"

        cuerpo = ruta.calls[0].request.content.decode()
        assert "grant_type=authorization_code" in cuerpo
        assert "client_key=test-tt-key" in cuerpo

    @respx.mock
    def test_refresh_conserva_metadata(
        self, provider: TikTokProvider, credentials: OAuthCredentials
    ) -> None:
        ruta = respx.post(f"{API}/v2/oauth/token/").mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "act.renovado",
                    "refresh_token": "rft.renovado",
                    "expires_in": 86400,
                    "open_id": "open-id-123",
                },
            )
        )
        credentials.metadata["creator_username"] = "mi_usuario"
        renovado = provider.refresh_token(credentials)
        assert renovado.access_token == "act.renovado"
        assert renovado.metadata["creator_username"] == "mi_usuario"
        assert "grant_type=refresh_token" in ruta.calls[0].request.content.decode()

    def test_sin_refresh_token_lanza_auth_error(self, provider: TikTokProvider) -> None:
        with pytest.raises(AuthenticationError, match="reconéctala"):
            provider.refresh_token(OAuthCredentials(access_token="a"))

    @respx.mock
    def test_error_oauth(self, provider: TikTokProvider) -> None:
        respx.post(f"{API}/v2/oauth/token/").mock(
            return_value=httpx.Response(
                400,
                json={"error": "invalid_grant", "error_description": "El code caducó"},
            )
        )
        with pytest.raises(PermanentProviderError, match="caducó"):
            provider.exchange_code(code="viejo", redirect_uri="https://api.test/cb")

    @respx.mock
    def test_revoke(self, provider: TikTokProvider, credentials: OAuthCredentials) -> None:
        ruta = respx.post(f"{API}/v2/oauth/revoke/").mock(return_value=httpx.Response(200, json={}))
        provider.revoke(credentials)
        assert ruta.call_count == 1


class TestCreatorInfo:
    @respx.mock
    def test_consulta_creator_info(
        self, provider: TikTokProvider, credentials: OAuthCredentials
    ) -> None:
        ruta = respx.post(f"{API}/v2/post/publish/creator_info/query/").mock(
            return_value=httpx.Response(200, json={"data": CREATOR_INFO, "error": {"code": "ok"}})
        )
        info = provider.get_creator_info(credentials)
        assert info["creator_username"] == "mi_usuario"
        assert info["max_video_post_duration_sec"] == 300
        assert ruta.calls[0].request.headers["authorization"] == "Bearer act.tiktok-token"

    @respx.mock
    def test_get_account_usa_creator_info(
        self, provider: TikTokProvider, credentials: OAuthCredentials
    ) -> None:
        respx.post(f"{API}/v2/post/publish/creator_info/query/").mock(
            return_value=httpx.Response(200, json={"data": CREATOR_INFO})
        )
        info = provider.get_account(credentials)
        assert info.external_account_id == "open-id-123"
        assert info.account_name == "mi_usuario"
        assert info.metadata["privacy_level_options"] == CREATOR_INFO["privacy_level_options"]
        assert info.metadata["audit_passed"] is False


class TestChunking:
    def test_fichero_pequeno_va_en_una_peticion(self, provider: TikTokProvider) -> None:
        chunk, total = provider.compute_chunks(5 * 1024 * 1024)
        assert chunk == 5 * 1024 * 1024
        assert total == 1

    def test_justo_por_debajo_del_limite(self, provider: TikTokProvider) -> None:
        size = WHOLE_FILE_LIMIT - 1
        chunk, total = provider.compute_chunks(size)
        assert (chunk, total) == (size, 1)

    def test_fichero_grande_se_parte(self, provider: TikTokProvider) -> None:
        size = 200 * 1024 * 1024
        chunk, total = provider.compute_chunks(size)
        assert chunk == MAX_CHUNK_SIZE
        assert total == size // MAX_CHUNK_SIZE  # el último chunk absorbe el resto

    def test_video_vacio(self, provider: TikTokProvider) -> None:
        with pytest.raises(InvalidVideoError, match="vacío"):
            provider.compute_chunks(0)


class TestDirectPost:
    @respx.mock
    def test_flujo_completo_con_file_upload(
        self, provider: TikTokProvider, credentials: OAuthCredentials
    ) -> None:
        respx.post(f"{API}/v2/post/publish/creator_info/query/").mock(
            return_value=httpx.Response(200, json={"data": CREATOR_INFO})
        )
        init = respx.post(f"{API}/v2/post/publish/video/init/").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "publish_id": PUBLISH_ID,
                        "upload_url": "https://open-upload.tiktokapis.com/upload/?u=1",
                    }
                },
            )
        )
        subir = respx.put("https://open-upload.tiktokapis.com/upload/").mock(
            return_value=httpx.Response(201)
        )
        respx.post(f"{API}/v2/post/publish/status/fetch/").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "status": "PUBLISH_COMPLETE",
                        "publicaly_available_post_id": ["7300000000000000000"],
                    }
                },
            )
        )

        credentials.metadata["creator_username"] = "mi_usuario"
        resultado = provider.publish(credentials, _request())

        assert resultado.external_post_id == "7300000000000000000"
        assert resultado.external_url == (
            "https://www.tiktok.com/@mi_usuario/video/7300000000000000000"
        )

        cuerpo = init.calls[0].request.content.decode()
        assert '"source":"FILE_UPLOAD"' in cuerpo.replace(" ", "")
        assert '"post_info"' in cuerpo
        # Sin audit aprobado se pide SELF_ONLY.
        assert "SELF_ONLY" in cuerpo
        assert '"disable_stitch":true' in cuerpo.replace(" ", "")

        cabeceras = subir.calls[0].request.headers
        assert cabeceras["content-range"] == "bytes 0-2047/2048"
        assert cabeceras["content-type"] == "video/mp4"

    @respx.mock
    def test_con_audit_aprobado_pide_publico(
        self,
        provider: TikTokProvider,
        credentials: OAuthCredentials,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "tiktok_audit_passed", True)
        respx.post(f"{API}/v2/post/publish/creator_info/query/").mock(
            return_value=httpx.Response(200, json={"data": CREATOR_INFO})
        )
        init = respx.post(f"{API}/v2/post/publish/video/init/").mock(
            return_value=httpx.Response(200, json={"data": {"publish_id": PUBLISH_ID}})
        )
        respx.post(f"{API}/v2/post/publish/status/fetch/").mock(
            return_value=httpx.Response(200, json={"data": {"status": "PUBLISH_COMPLETE"}})
        )
        request = _request()
        request.video.public_url = "https://cdn.verificado.test/v.mp4"
        resultado = provider.publish(credentials, request)

        cuerpo = init.calls[0].request.content.decode()
        assert "PUBLIC_TO_EVERYONE" in cuerpo
        assert "PULL_FROM_URL" in cuerpo
        assert resultado.metadata["note"] is None

    @respx.mock
    def test_pull_from_url_no_sube_fichero(
        self, provider: TikTokProvider, credentials: OAuthCredentials
    ) -> None:
        respx.post(f"{API}/v2/post/publish/creator_info/query/").mock(
            return_value=httpx.Response(200, json={"data": CREATOR_INFO})
        )
        respx.post(f"{API}/v2/post/publish/video/init/").mock(
            return_value=httpx.Response(200, json={"data": {"publish_id": PUBLISH_ID}})
        )
        subir = respx.put("https://open-upload.tiktokapis.com/upload/").mock(
            return_value=httpx.Response(201)
        )
        respx.post(f"{API}/v2/post/publish/status/fetch/").mock(
            return_value=httpx.Response(200, json={"data": {"status": "PUBLISH_COMPLETE"}})
        )
        request = _request()
        request.video.public_url = "https://cdn.verificado.test/v.mp4"
        provider.publish(credentials, request)
        assert subir.call_count == 0

    @respx.mock
    def test_privacy_level_no_permitido(
        self, provider: TikTokProvider, credentials: OAuthCredentials
    ) -> None:
        respx.post(f"{API}/v2/post/publish/creator_info/query/").mock(
            return_value=httpx.Response(
                200,
                json={"data": {**CREATOR_INFO, "privacy_level_options": ["SELF_ONLY"]}},
            )
        )
        request = _request(options={"privacy_level": "PUBLIC_TO_EVERYONE"})
        with pytest.raises(PermanentProviderError, match="no está permitido"):
            provider.publish(credentials, request)

    @respx.mock
    def test_video_mas_largo_que_el_permitido(
        self, provider: TikTokProvider, credentials: OAuthCredentials
    ) -> None:
        respx.post(f"{API}/v2/post/publish/creator_info/query/").mock(
            return_value=httpx.Response(200, json={"data": CREATOR_INFO})
        )
        request = _request(options={"duration_seconds": 400})
        with pytest.raises(InvalidVideoError, match="permite hasta 300"):
            provider.publish(credentials, request)

    @respx.mock
    def test_modo_inbox_usa_el_otro_endpoint(
        self, provider: TikTokProvider, credentials: OAuthCredentials
    ) -> None:
        inbox = respx.post(f"{API}/v2/post/publish/inbox/video/init/").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "publish_id": PUBLISH_ID,
                        "upload_url": "https://open-upload.tiktokapis.com/upload/?u=1",
                    }
                },
            )
        )
        respx.put("https://open-upload.tiktokapis.com/upload/").mock(
            return_value=httpx.Response(201)
        )
        respx.post(f"{API}/v2/post/publish/status/fetch/").mock(
            return_value=httpx.Response(200, json={"data": {"status": "SEND_TO_USER_INBOX"}})
        )
        resultado = provider.publish(credentials, _request(options={"post_mode": "INBOX"}))
        assert inbox.call_count == 1
        assert resultado.metadata["post_mode"] == "INBOX"
        # En modo inbox no hay post_info (el usuario completa la publicación).
        assert '"post_info"' not in inbox.calls[0].request.content.decode()

    @respx.mock
    def test_reanuda_con_el_publish_id_guardado(
        self, provider: TikTokProvider, credentials: OAuthCredentials
    ) -> None:
        init = respx.post(f"{API}/v2/post/publish/video/init/").mock(
            return_value=httpx.Response(200, json={"data": {"publish_id": "OTRO"}})
        )
        respx.post(f"{API}/v2/post/publish/status/fetch/").mock(
            return_value=httpx.Response(200, json={"data": {"status": "PUBLISH_COMPLETE"}})
        )
        request = _request()
        request.state = {"publish_id": PUBLISH_ID, "uploaded": True}
        provider.publish(credentials, request)
        assert init.call_count == 0


class TestEstadosYErrores:
    @respx.mock
    def test_status_failed_con_motivo_de_video(
        self, provider: TikTokProvider, credentials: OAuthCredentials
    ) -> None:
        respx.post(f"{API}/v2/post/publish/status/fetch/").mock(
            return_value=httpx.Response(
                200,
                json={"data": {"status": "FAILED", "fail_reason": "file_format_check_failed"}},
            )
        )
        with pytest.raises(InvalidVideoError, match="file_format_check_failed"):
            provider.wait_for_publish(credentials, PUBLISH_ID, direct_post=True)

    @respx.mock
    def test_status_failed_generico(
        self, provider: TikTokProvider, credentials: OAuthCredentials
    ) -> None:
        respx.post(f"{API}/v2/post/publish/status/fetch/").mock(
            return_value=httpx.Response(
                200, json={"data": {"status": "FAILED", "fail_reason": "internal_error"}}
            )
        )
        with pytest.raises(PermanentProviderError):
            provider.wait_for_publish(credentials, PUBLISH_ID, direct_post=True)

    @respx.mock
    def test_timeout_de_procesado(
        self, provider: TikTokProvider, credentials: OAuthCredentials
    ) -> None:
        respx.post(f"{API}/v2/post/publish/status/fetch/").mock(
            return_value=httpx.Response(200, json={"data": {"status": "PROCESSING_UPLOAD"}})
        )
        with pytest.raises(ProcessingTimeoutError):
            provider.wait_for_publish(credentials, PUBLISH_ID, direct_post=True)

    @pytest.mark.parametrize(
        ("code", "tipo"),
        [
            ("access_token_invalid", AuthenticationError),
            ("scope_not_authorized", AuthenticationError),
            ("rate_limit_exceeded", RateLimitError),
            ("spam_risk_too_many_posts", RateLimitError),
            ("file_format_check_failed", InvalidVideoError),
            ("url_ownership_unverified", PermanentProviderError),
            ("internal_error", TransientProviderError),
        ],
    )
    @respx.mock
    def test_clasifica_los_codigos_de_tiktok(
        self,
        provider: TikTokProvider,
        credentials: OAuthCredentials,
        code: str,
        tipo: type,
    ) -> None:
        respx.post(f"{API}/v2/post/publish/creator_info/query/").mock(
            return_value=httpx.Response(
                400, json={"error": {"code": code, "message": f"fallo {code}", "log_id": "x"}}
            )
        )
        with pytest.raises(tipo):
            provider.get_creator_info(credentials)

    @respx.mock
    def test_error_devuelto_con_http_200(
        self, provider: TikTokProvider, credentials: OAuthCredentials
    ) -> None:
        """TikTok puede responder 200 con error.code != ok."""
        respx.post(f"{API}/v2/post/publish/creator_info/query/").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {},
                    "error": {"code": "access_token_invalid", "message": "token malo"},
                },
            )
        )
        with pytest.raises(AuthenticationError):
            provider.get_creator_info(credentials)
