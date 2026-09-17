"""Fixtures compartidas. NUNCA se publica de verdad: los providers van mockeados."""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

# La configuración debe fijarse ANTES de importar la app.
_TMP = tempfile.mkdtemp(prefix="svapi-tests-")
os.environ.update(
    {
        "ENVIRONMENT": "development",
        "ENCRYPTION_KEY": "dGVzdC1rZXktMzItYnl0ZXMtZm9yLXRlc3RpbmctMDE=",
        "SIGNING_SECRET": "test-signing-secret-para-pruebas-0123456789",
        "ADMIN_API_KEYS": "adm_test_key",
        "BOOTSTRAP_API_KEYS": "",
        "DATABASE_URL": f"sqlite:///{_TMP}/test.db",
        "LOCAL_STORAGE_PATH": f"{_TMP}/media",
        "STORAGE_BACKEND": "local",
        # Modo explícito: los tests publican de forma síncrona para poder
        # comprobar el resultado en la propia respuesta. Se pone a mano para
        # que un `.env` del proyecto no altere el comportamiento.
        "PUBLISH_MODE": "inline",
        "CELERY_TASK_ALWAYS_EAGER": "true",
        "SCHEDULER_IN_PROCESS": "false",
        "RATE_LIMIT_ENABLED": "false",
        "PUBLIC_BASE_URL": "https://api.ejemplo.test",
        "MAX_VIDEO_SIZE_MB": "5",
        "PROCESSING_POLL_INTERVAL_SECONDS": "1",
        "PROCESSING_TIMEOUT_SECONDS": "5",
        "RETRY_BASE_DELAY_SECONDS": "1",
        "MAX_PUBLISH_ATTEMPTS": "3",
        "INSTAGRAM_APP_ID": "test-ig-app",
        "INSTAGRAM_APP_SECRET": "test-ig-secret",
        "TIKTOK_CLIENT_KEY": "test-tt-key",
        "TIKTOK_CLIENT_SECRET": "test-tt-secret",
        "YOUTUBE_CLIENT_ID": "test-yt-id",
        "YOUTUBE_CLIENT_SECRET": "test-yt-secret",
    }
)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.database import SessionLocal, engine  # noqa: E402
from app.models import Base, Client, Platform  # noqa: E402
from app.providers.base import (  # noqa: E402
    AccountInfo,
    BaseProvider,
    OAuthCredentials,
    PublishResult,
    RemoteStatus,
)
from app.services import clients as clients_service  # noqa: E402

#: Cabecera de ~24 bytes que `sniff_content_type` reconoce como mp4.
MP4_HEADER = b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2avc1"


def make_video_bytes(size: int = 4096) -> bytes:
    """Bytes de un fichero que pasa la validación de MIME type."""
    body = MP4_HEADER
    return body + b"\x00" * max(0, size - len(body))


@pytest.fixture(scope="session", autouse=True)
def _limpiar_directorio_temporal() -> Iterator[None]:
    """Borra el directorio temporal de la sesión al terminar.

    Se cierra antes el engine: si quedara una conexión viva, SQLAlchemy
    volvería a crear el directorio del fichero SQLite.
    """
    yield
    engine.dispose()
    shutil.rmtree(_TMP, ignore_errors=True)


@pytest.fixture(autouse=True)
def _clean_database() -> Iterator[None]:
    """Base de datos limpia en cada test."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def api_client(db: Session) -> Iterator[tuple[TestClient, Client, str]]:
    """Cliente HTTP autenticado: `(client, cliente_db, api_key)`."""
    from app.main import app

    record = clients_service.create_client(db, name="test-client")
    issued = clients_service.issue_api_key(db, record, label="test")
    with TestClient(app) as client:
        client.headers.update({"Authorization": f"Bearer {issued.api_key}"})
        yield client, record, issued.api_key


@pytest.fixture
def anon_client() -> Iterator[TestClient]:
    from app.main import app

    with TestClient(app) as client:
        yield client


@pytest.fixture
def media_dir() -> Path:
    return Path(_TMP) / "media"


# --------------------------------------------------------------- doble de test
class FakeProvider(BaseProvider):
    """Provider de prueba: no hace ninguna llamada de red."""

    def __init__(self, platform: Platform) -> None:
        self.platform = platform  # type: ignore[misc]
        self.publish_calls: list[object] = []
        self.refresh_calls = 0
        self.revoke_calls = 0
        #: Excepción a lanzar en `publish` (para probar reintentos).
        self.publish_error: BaseException | None = None
        self.configured = True

    def is_configured(self) -> bool:
        return self.configured

    def build_authorization_request(self, *, state: str, redirect_uri: str):
        from app.providers.base import AuthorizationRequest

        return AuthorizationRequest(
            url=f"https://fake.test/authorize?state={state}&redirect_uri={redirect_uri}",
            state=state,
        )

    def exchange_code(self, *, code: str, redirect_uri: str, code_verifier=None):
        from datetime import timedelta

        from app.models import utcnow

        return OAuthCredentials(
            access_token=f"access-{code}",
            refresh_token=f"refresh-{code}",
            expires_at=utcnow() + timedelta(hours=1),
            scopes=["scope.a"],
        )

    def refresh_token(self, credentials: OAuthCredentials) -> OAuthCredentials:
        from datetime import timedelta

        from app.models import utcnow

        self.refresh_calls += 1
        return OAuthCredentials(
            access_token=f"{credentials.access_token}-refreshed",
            refresh_token=credentials.refresh_token,
            expires_at=utcnow() + timedelta(hours=2),
            scopes=credentials.scopes,
            metadata=credentials.metadata,
        )

    def get_account(self, credentials: OAuthCredentials) -> AccountInfo:
        return AccountInfo(
            external_account_id=f"ext-{self.platform.value}",
            account_name=f"cuenta-{self.platform.value}",
            metadata={"fake": True},
        )

    def publish(self, credentials: OAuthCredentials, request) -> PublishResult:
        self.publish_calls.append(request)
        if self.publish_error is not None:
            raise self.publish_error
        request.set_stage("uploading")
        request.save_state(step="uploaded")
        request.set_stage("publishing")
        return PublishResult(
            external_post_id=f"ext-post-{self.platform.value}",
            external_url=f"https://fake.test/{self.platform.value}/post",
            metadata={"fake": True},
        )

    def get_post_status(self, credentials: OAuthCredentials, external_post_id: str) -> RemoteStatus:
        return RemoteStatus(
            state="PUBLISHED",
            is_final=True,
            external_url=f"https://fake.test/{self.platform.value}/post",
        )

    def revoke(self, credentials: OAuthCredentials) -> None:
        self.revoke_calls += 1


@pytest.fixture
def fake_providers(monkeypatch: pytest.MonkeyPatch) -> dict[Platform, FakeProvider]:
    """Sustituye TODOS los providers por dobles de test.

    Garantiza que ningún test haga una publicación real.
    """
    providers = {platform: FakeProvider(platform) for platform in Platform}

    def _get_provider(platform):
        return providers[Platform(platform)]

    for module in (
        "app.providers.registry",
        "app.services.accounts",
        "app.services.publisher",
        "app.routers.oauth",
        "app.routers.accounts",
        "app.providers",
    ):
        monkeypatch.setattr(f"{module}.get_provider", _get_provider, raising=False)
    return providers


@pytest.fixture
def connected_accounts(db: Session, api_client, fake_providers):
    """Conecta cuentas de las tres plataformas para el cliente de prueba."""
    from datetime import timedelta

    from app.models import utcnow
    from app.services import accounts as accounts_service

    _client, record, _key = api_client
    accounts = {}
    for platform in (Platform.INSTAGRAM, Platform.TIKTOK, Platform.YOUTUBE):
        accounts[platform] = accounts_service.upsert_account(
            db,
            client_id=record.id,
            platform=platform,
            external_account_id=f"ext-{platform.value}",
            account_name=f"cuenta-{platform.value}",
            credentials=OAuthCredentials(
                access_token=f"token-{platform.value}",
                refresh_token=f"refresh-{platform.value}",
                expires_at=utcnow() + timedelta(days=30),
                scopes=["scope.a"],
            ),
        )
    return accounts
