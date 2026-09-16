"""Motor de base de datos y sesiones SQLAlchemy.

Se usa SQLAlchemy en modo síncrono a propósito: el mismo código de negocio
corre dentro de FastAPI (endpoints `def`, ejecutados en threadpool) y dentro
de los workers Celery, sin duplicar lógica async/sync.
"""

from __future__ import annotations

import os
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings


def sqlite_file_path(url: str) -> Path | None:
    """Ruta del fichero de una URL SQLite, o `None` si es en memoria.

    SQLAlchemy distingue rutas relativas de absolutas por el número de barras:
      * `sqlite:///data/x.db`  → relativa  `data/x.db`
      * `sqlite:////tmp/x.db`  → absoluta  `/tmp/x.db`
    """
    if "://" not in url:
        return None
    resto = url.split("://", 1)[1].split("?", 1)[0]
    if resto.startswith("//"):
        candidato = resto[1:]  # absoluta: /tmp/x.db
    elif resto.startswith("/"):
        candidato = resto[1:]  # relativa: data/x.db
    else:
        candidato = resto
    if not candidato or candidato == ":memory:":
        return None
    return Path(candidato)


def _ensure_sqlite_dir(url: str) -> None:
    """Crea el directorio del fichero SQLite si hace falta."""
    path = sqlite_file_path(url)
    if path is None:
        return
    parent = path.parent
    if str(parent) not in ("", "."):
        parent.mkdir(parents=True, exist_ok=True)


def build_engine(url: str | None = None) -> Engine:
    database_url = url or settings.database_url
    kwargs: dict[str, object] = {"echo": settings.db_echo, "future": True}

    if database_url.startswith("sqlite"):
        _ensure_sqlite_dir(database_url)
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs["pool_pre_ping"] = True
        kwargs["pool_size"] = settings.db_pool_size
        kwargs["max_overflow"] = settings.db_max_overflow

    engine = create_engine(database_url, **kwargs)

    if database_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, _record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine


engine: Engine = build_engine()
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """Dependencia FastAPI: una sesión por request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Contexto transaccional para workers y scripts."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def create_all() -> None:
    """Crea el esquema directamente (solo desarrollo/tests; en prod usar Alembic)."""
    from app.models import Base  # import local para evitar ciclos

    Base.metadata.create_all(bind=engine)


def database_is_reachable() -> bool:
    from sqlalchemy import text

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def reset_engine(url: str | None = None) -> None:
    """Reconstruye el engine (usado en tests)."""
    global engine, SessionLocal
    engine.dispose()
    engine = build_engine(url or os.environ.get("DATABASE_URL") or settings.database_url)
    SessionLocal.configure(bind=engine)
