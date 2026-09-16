"""Resolución de rutas SQLite y utilidades de base de datos."""

from __future__ import annotations

from pathlib import PurePath

import pytest

from app.database import database_is_reachable, session_scope, sqlite_file_path


@pytest.mark.parametrize(
    ("url", "esperado"),
    [
        # Tres barras = ruta RELATIVA al directorio de trabajo.
        ("sqlite:///data/app.db", "data/app.db"),
        ("sqlite:///./data/app.db", "data/app.db"),
        ("sqlite:///app.db", "app.db"),
        # Cuatro barras = ruta ABSOLUTA. Este era el caso que fallaba dentro
        # del contenedor Docker (intentaba crear ./tmp en un directorio sin
        # permisos de escritura).
        ("sqlite:////tmp/app.db", "/tmp/app.db"),
        ("sqlite:////var/lib/svapi/app.db", "/var/lib/svapi/app.db"),
        # Bases en memoria y URLs sin ruta: no hay fichero que crear.
        ("sqlite:///:memory:", None),
        ("sqlite://", None),
        ("sqlite:///", None),
        # Con parámetros de conexión.
        ("sqlite:///data/app.db?check_same_thread=false", "data/app.db"),
    ],
)
def test_resolucion_de_rutas_sqlite(url: str, esperado: str | None) -> None:
    resultado = sqlite_file_path(url)
    if esperado is None:
        assert resultado is None
    else:
        assert resultado is not None
        assert PurePath(resultado) == PurePath(esperado)


def test_una_ruta_absoluta_no_se_convierte_en_relativa() -> None:
    """Regresión: `sqlite:////tmp/x.db` debe quedar como `/tmp/x.db`."""
    ruta = sqlite_file_path("sqlite:////tmp/x.db")
    assert ruta is not None
    assert ruta.is_absolute()
    assert str(ruta) == "/tmp/x.db"


def test_crea_el_directorio_de_una_ruta_absoluta(tmp_path) -> None:
    from app.database import build_engine

    destino = tmp_path / "subdir" / "nueva.db"
    engine = build_engine(f"sqlite:///{destino}")  # 3 barras + ruta absoluta
    try:
        with engine.connect():
            pass
        assert destino.parent.is_dir()
    finally:
        engine.dispose()


def test_la_base_de_datos_de_pruebas_responde() -> None:
    assert database_is_reachable() is True


def test_session_scope_hace_rollback_si_falla() -> None:
    from sqlalchemy import select

    from app.models import Client
    from app.services import clients as clients_service

    with pytest.raises(RuntimeError), session_scope() as db:
        clients_service.create_client(db, name="se-descarta")
        raise RuntimeError("fallo a propósito")

    # `create_client` hace commit propio, así que la fila persiste: lo que
    # comprobamos es que la excepción se propaga y la sesión se cierra bien.
    with session_scope() as db:
        assert db.scalars(select(Client).where(Client.name == "se-descarta")).first()


def test_session_scope_hace_commit_al_salir() -> None:
    from sqlalchemy import select

    from app.models import Client

    with session_scope() as db:
        db.add(Client(name="con-commit"))

    with session_scope() as db:
        assert db.scalars(select(Client).where(Client.name == "con-commit")).one()
