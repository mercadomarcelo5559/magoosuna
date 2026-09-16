"""Cifrado de tokens, firma de URLs y redacción de secretos en los logs."""

from __future__ import annotations

import logging

import pytest

from app.logging_config import RedactingFilter, redact, redact_mapping
from app.security import crypto


def test_cifrado_ida_y_vuelta() -> None:
    secreto = "EAAG-token-de-instagram-muy-largo"
    cifrado = crypto.encrypt(secreto)
    assert cifrado is not None
    assert cifrado.startswith("fernet:")
    assert secreto not in cifrado
    assert crypto.decrypt(cifrado) == secreto


def test_cifrado_de_none_devuelve_none() -> None:
    assert crypto.encrypt(None) is None
    assert crypto.decrypt(None) is None


def test_el_cifrado_no_es_determinista() -> None:
    """Dos cifrados del mismo valor difieren (Fernet incluye IV y timestamp)."""
    assert crypto.encrypt("mismo") != crypto.encrypt("mismo")


def test_descifrar_valor_no_cifrado_falla() -> None:
    with pytest.raises(crypto.CryptoError):
        crypto.decrypt("texto-en-claro")


def test_descifrar_con_otra_clave_falla(monkeypatch: pytest.MonkeyPatch) -> None:
    cifrado = crypto.encrypt("secreto")
    monkeypatch.setattr(crypto.settings, "encryption_key", "otra-clave-totalmente-distinta")
    with pytest.raises(crypto.CryptoError):
        crypto.decrypt(cifrado)


def test_generar_clave_fernet_es_valida() -> None:
    from cryptography.fernet import Fernet

    key = crypto.generate_encryption_key()
    assert Fernet(key.encode())


def test_hash_de_api_key_es_determinista_y_no_reversible() -> None:
    key = "svk_abc123"
    assert crypto.hash_api_key(key) == crypto.hash_api_key(key)
    assert key not in crypto.hash_api_key(key)
    assert crypto.hash_api_key(key) != crypto.hash_api_key("svk_abc124")


def test_firma_de_url_valida_y_caducada() -> None:
    token = crypto.sign_payload("media:123", ttl_seconds=60)
    assert crypto.verify_signature("media:123", token)
    # Otro payload no valida con la misma firma.
    assert not crypto.verify_signature("media:456", token)
    # Token caducado.
    caducado = crypto.sign_payload("media:123", ttl_seconds=-10)
    assert not crypto.verify_signature("media:123", caducado)
    # Token corrupto.
    assert not crypto.verify_signature("media:123", "basura")


def test_comparacion_en_tiempo_constante() -> None:
    assert crypto.constant_time_equals("igual", "igual")
    assert not crypto.constant_time_equals("igual", "distinto")


@pytest.mark.parametrize(
    "entrada",
    [
        "access_token=EAAGabc123xyz",
        "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9",
        "Authorization: OAuth EAAGsecret",
        '{"refresh_token": "rt_muy_secreto"}',
        "client_secret=abcdef123456",
        "fernet:gAAAAABmZ29vZA==",
    ],
)
def test_redaccion_oculta_secretos(entrada: str) -> None:
    salida = redact(entrada)
    assert "***" in salida
    for fragmento in (
        "EAAGabc123xyz",
        "eyJhbGciOiJIUzI1NiJ9",
        "rt_muy_secreto",
        "abcdef123456",
        "gAAAAABmZ29vZA==",
    ):
        assert fragmento not in salida


def test_redaccion_de_diccionarios_anidados() -> None:
    datos = {
        "platform": "instagram",
        "access_token": "secreto",
        "nested": {"refresh_token": "otro", "post_id": "123"},
    }
    seguro = redact_mapping(datos)
    assert seguro["access_token"] == "***"
    assert seguro["nested"]["refresh_token"] == "***"
    assert seguro["platform"] == "instagram"
    assert seguro["nested"]["post_id"] == "123"


def test_el_filtro_de_logging_redacta_el_registro() -> None:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="publicando con access_token=%s",
        args=("EAAGsuper_secreto",),
        exc_info=None,
    )
    RedactingFilter().filter(record)
    assert "EAAGsuper_secreto" not in record.getMessage()
    assert "***" in record.getMessage()


def test_los_tokens_se_guardan_cifrados_en_la_base_de_datos(db, fake_providers) -> None:
    """Comprobación de extremo a extremo: en la fila no hay texto en claro."""
    from app.models import Platform
    from app.providers.base import OAuthCredentials
    from app.services import accounts as accounts_service
    from app.services import clients as clients_service

    cliente = clients_service.create_client(db, name="cifrado")
    account = accounts_service.upsert_account(
        db,
        client_id=cliente.id,
        platform=Platform.INSTAGRAM,
        external_account_id="ext-1",
        account_name="cuenta",
        credentials=OAuthCredentials(
            access_token="TOKEN_EN_CLARO", refresh_token="REFRESH_EN_CLARO"
        ),
    )
    assert "TOKEN_EN_CLARO" not in account.access_token_encrypted
    assert "REFRESH_EN_CLARO" not in (account.refresh_token_encrypted or "")
    credenciales = accounts_service.credentials_from_account(account)
    assert credenciales.access_token == "TOKEN_EN_CLARO"
    assert credenciales.refresh_token == "REFRESH_EN_CLARO"


def test_la_api_nunca_devuelve_tokens(db, api_client, fake_providers) -> None:
    """`GET /v1/accounts` no debe filtrar tokens ni en el metadata."""
    from app.models import Platform
    from app.providers.base import OAuthCredentials
    from app.services import accounts as accounts_service

    client, record, _key = api_client
    accounts_service.upsert_account(
        db,
        client_id=record.id,
        platform=Platform.INSTAGRAM,
        external_account_id="ext-1",
        account_name="cuenta",
        credentials=OAuthCredentials(access_token="TOKEN_SECRETO"),
        metadata={"page_access_token": "TOKEN_DE_PAGINA", "page_name": "Mi página"},
    )
    cuerpo = client.get("/v1/accounts").text
    assert "TOKEN_SECRETO" not in cuerpo
    assert "TOKEN_DE_PAGINA" not in cuerpo
    assert "page_access_token" not in cuerpo
    assert "Mi página" in cuerpo
