import os
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def env_bool(name: str, default: bool = False) -> bool:
    v = env(name)
    if not v:
        return default
    return v.lower() in ("1", "true", "yes", "si", "sí")


@lru_cache
def settings() -> dict:
    path = Path(env("PAGOYA_SETTINGS", str(ROOT / "config" / "settings.yaml")))
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_mode() -> bool:
    return env_bool("TEST_MODE", True)


def public_url(path: str = "") -> str:
    return env("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/") + path


def graph_version() -> str:
    return env("GRAPH_API_VERSION", "v21.0")
