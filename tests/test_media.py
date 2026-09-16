"""Validación y gestión de videos."""

from __future__ import annotations

import io

import pytest

from app.config import settings
from app.utils.video import VideoValidationError, sniff_content_type, validate_video
from tests.conftest import MP4_HEADER, make_video_bytes


class TestValidacionDeVideo:
    def test_detecta_mp4_por_los_bytes(self) -> None:
        assert sniff_content_type(MP4_HEADER) == "video/mp4"

    def test_detecta_webm_por_los_bytes(self) -> None:
        assert sniff_content_type(b"\x1a\x45\xdf\xa3" + b"\x00" * 20) == "video/webm"

    def test_detecta_quicktime_por_la_marca(self) -> None:
        header = b"\x00\x00\x00\x14ftypqt  " + b"\x00" * 12
        assert sniff_content_type(header) == "video/quicktime"

    def test_no_detecta_nada_en_un_fichero_de_texto(self) -> None:
        assert sniff_content_type(b"esto no es un video en absoluto") is None

    def test_acepta_un_mp4_valido(self) -> None:
        resultado = validate_video(
            filename="reel.mp4",
            declared_content_type="video/mp4",
            header_bytes=MP4_HEADER,
            size_bytes=1024,
        )
        assert resultado.content_type == "video/mp4"
        assert resultado.extension == ".mp4"

    def test_rechaza_extension_no_permitida(self) -> None:
        with pytest.raises(VideoValidationError, match="no permitida"):
            validate_video(filename="video.avi", declared_content_type="video/x-msvideo")

    def test_rechaza_sin_extension(self) -> None:
        with pytest.raises(VideoValidationError, match="no permitida"):
            validate_video(filename="video", declared_content_type="video/mp4")

    def test_rechaza_mime_no_permitido(self) -> None:
        with pytest.raises(VideoValidationError, match="no permitido"):
            validate_video(filename="a.mp4", declared_content_type="application/pdf")

    def test_rechaza_contenido_que_no_es_video(self) -> None:
        """Extensión correcta pero bytes falsos: se detecta y se rechaza."""
        with pytest.raises(VideoValidationError, match="no parece un video"):
            validate_video(
                filename="falso.mp4",
                declared_content_type="video/mp4",
                header_bytes=b"%PDF-1.4 en realidad soy un pdf",
            )

    def test_rechaza_video_demasiado_grande(self) -> None:
        with pytest.raises(VideoValidationError, match="máximo"):
            validate_video(
                filename="grande.mp4",
                declared_content_type="video/mp4",
                header_bytes=MP4_HEADER,
                size_bytes=settings.max_video_size_bytes + 1,
            )

    def test_rechaza_video_vacio(self) -> None:
        with pytest.raises(VideoValidationError, match="vacío"):
            validate_video(
                filename="vacio.mp4",
                declared_content_type="video/mp4",
                header_bytes=MP4_HEADER,
                size_bytes=0,
            )

    def test_sanea_el_nombre_de_fichero_con_ruta(self) -> None:
        """Un intento de path traversal en el nombre se limpia."""
        resultado = validate_video(
            filename="../../../etc/passwd.mp4",
            declared_content_type="video/mp4",
            header_bytes=MP4_HEADER,
        )
        assert resultado.filename == "passwd.mp4"
        assert "/" not in resultado.filename

    def test_rechaza_nombre_vacio(self) -> None:
        with pytest.raises(VideoValidationError):
            validate_video(filename="", declared_content_type="video/mp4")


class TestSubidaPorApi:
    def test_subida_correcta(self, api_client) -> None:
        client, _record, _key = api_client
        data = make_video_bytes(2048)
        response = client.post(
            "/v1/media",
            files={"file": ("reel.mp4", io.BytesIO(data), "video/mp4")},
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["filename"] == "reel.mp4"
        assert body["content_type"] == "video/mp4"
        assert body["size_bytes"] == len(data)
        assert body["status"] == "ready"
        assert len(body["checksum_sha256"]) == 64
        assert body["download_url"] and "token=" in body["download_url"]
        assert body["expires_at"] is not None

    def test_el_fichero_se_escribe_en_el_almacenamiento(self, api_client, media_dir) -> None:
        client, _record, _key = api_client
        client.post(
            "/v1/media", files={"file": ("x.mp4", io.BytesIO(make_video_bytes()), "video/mp4")}
        )
        assert list(media_dir.rglob("x.mp4"))

    def test_rechaza_fichero_no_video(self, api_client) -> None:
        client, _record, _key = api_client
        response = client.post(
            "/v1/media",
            files={"file": ("doc.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")},
        )
        assert response.status_code == 422
        assert response.json()["error"] in {"invalid_video", "validation_error"}

    def test_rechaza_mp4_falsificado(self, api_client) -> None:
        client, _record, _key = api_client
        response = client.post(
            "/v1/media",
            files={"file": ("falso.mp4", io.BytesIO(b"no soy un video"), "video/mp4")},
        )
        assert response.status_code == 422

    def test_rechaza_video_mayor_que_el_limite(self, api_client) -> None:
        client, _record, _key = api_client
        grande = make_video_bytes(settings.max_video_size_bytes + 1024)
        response = client.post(
            "/v1/media", files={"file": ("grande.mp4", io.BytesIO(grande), "video/mp4")}
        )
        assert response.status_code == 422
        assert "MB" in response.json()["message"]

    def test_limites_publicados(self, api_client) -> None:
        client, _record, _key = api_client
        body = client.get("/v1/media/limits").json()
        assert body["max_size_mb"] == settings.max_video_size_mb
        assert "video/mp4" in body["allowed_mime_types"]
        assert body["storage_backend"] == "local"
        assert body["public_url_reachable"] is True

    def test_listar_y_consultar_media(self, api_client) -> None:
        client, _record, _key = api_client
        created = client.post(
            "/v1/media", files={"file": ("a.mp4", io.BytesIO(make_video_bytes()), "video/mp4")}
        ).json()

        listado = client.get("/v1/media").json()
        assert listado["total"] == 1
        assert listado["items"][0]["id"] == created["id"]

        detalle = client.get(f"/v1/media/{created['id']}")
        assert detalle.status_code == 200

        assert client.get("/v1/media/no-existe").status_code == 404

    def test_borrado_elimina_el_fichero(self, api_client, media_dir) -> None:
        client, _record, _key = api_client
        created = client.post(
            "/v1/media", files={"file": ("b.mp4", io.BytesIO(make_video_bytes()), "video/mp4")}
        ).json()
        assert list(media_dir.rglob("b.mp4"))

        assert client.delete(f"/v1/media/{created['id']}").status_code == 200
        assert not list(media_dir.rglob("b.mp4"))
        assert client.get(f"/v1/media/{created['id']}").json()["status"] == "deleted"


class TestDescargaFirmada:
    def test_descarga_con_token_valido(self, api_client, anon_client) -> None:
        client, _record, _key = api_client
        data = make_video_bytes(1500)
        created = client.post(
            "/v1/media", files={"file": ("d.mp4", io.BytesIO(data), "video/mp4")}
        ).json()

        # Sin API key: es la URL que usa Instagram para descargar el video.
        url = created["download_url"].replace("https://api.ejemplo.test", "")
        response = anon_client.get(url)
        assert response.status_code == 200
        assert response.content == data
        assert response.headers["content-type"] == "video/mp4"

    def test_descarga_sin_token_o_con_token_falso(self, api_client, anon_client) -> None:
        client, _record, _key = api_client
        created = client.post(
            "/v1/media", files={"file": ("e.mp4", io.BytesIO(make_video_bytes()), "video/mp4")}
        ).json()
        media_id = created["id"]

        assert anon_client.get(f"/v1/media/{media_id}/download").status_code == 422
        assert anon_client.get(f"/v1/media/{media_id}/download?token=falso").status_code == 403


class TestRetencion:
    def test_purga_borra_los_videos_caducados(self, db, api_client) -> None:
        from datetime import timedelta

        from app.models import MediaStatus, utcnow
        from app.services import media as media_service

        client, record, _key = api_client
        asset = media_service.create_asset_from_upload(
            db,
            client_id=record.id,
            filename="viejo.mp4",
            content_type="video/mp4",
            stream=io.BytesIO(make_video_bytes()),
        )
        asset.expires_at = utcnow() - timedelta(hours=1)
        db.add(asset)
        db.commit()

        assert media_service.purge_expired_assets(db) == 1
        db.refresh(asset)
        assert asset.status == MediaStatus.DELETED

    def test_la_purga_respeta_los_videos_con_publicaciones_en_curso(
        self, db, api_client, connected_accounts
    ) -> None:
        from datetime import timedelta

        from app.models import MediaStatus, Platform, as_utc, utcnow
        from app.services import media as media_service
        from app.services import posts as posts_service

        _client, record, _key = api_client
        asset = media_service.create_asset_from_upload(
            db,
            client_id=record.id,
            filename="en-uso.mp4",
            content_type="video/mp4",
            stream=io.BytesIO(make_video_bytes()),
        )
        posts_service.create_post_group(
            db,
            client_id=record.id,
            asset=asset,
            platforms=[Platform.INSTAGRAM],
            scheduled_at=utcnow() + timedelta(days=1),
        )
        asset.expires_at = utcnow() - timedelta(hours=1)
        db.add(asset)
        db.commit()

        assert media_service.purge_expired_assets(db) == 0
        db.refresh(asset)
        assert asset.status == MediaStatus.READY
        # Y la expiración se ha pospuesto.
        assert as_utc(asset.expires_at) > utcnow()
