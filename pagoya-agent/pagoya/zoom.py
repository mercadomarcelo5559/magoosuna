"""Zoom Server-to-Server OAuth: crear reuniones de demo."""
from __future__ import annotations

import base64
import datetime as dt
import time

import httpx

from .config import env

_token = {"value": None, "exp": 0}


def configured() -> bool:
    return bool(env("ZOOM_ACCOUNT_ID") and env("ZOOM_CLIENT_ID") and env("ZOOM_CLIENT_SECRET"))


def _access_token() -> str:
    if _token["value"] and _token["exp"] > time.time() + 60:
        return _token["value"]
    basic = base64.b64encode(f"{env('ZOOM_CLIENT_ID')}:{env('ZOOM_CLIENT_SECRET')}".encode()).decode()
    r = httpx.post("https://zoom.us/oauth/token", timeout=30,
                   params={"grant_type": "account_credentials", "account_id": env("ZOOM_ACCOUNT_ID")},
                   headers={"Authorization": f"Basic {basic}"})
    r.raise_for_status()
    data = r.json()
    _token.update(value=data["access_token"], exp=time.time() + data.get("expires_in", 3600))
    return _token["value"]


def create_meeting(topic: str, start_local: dt.datetime, minutes: int, timezone: str) -> dict:
    if not configured():
        return {"join_url": "(Zoom no configurado: se enviará el link manualmente)", "id": ""}
    r = httpx.post(f"https://api.zoom.us/v2/users/{env('ZOOM_USER', 'me')}/meetings", timeout=30,
                   headers={"Authorization": f"Bearer {_access_token()}"},
                   json={"topic": topic[:200], "type": 2,
                         "start_time": start_local.strftime("%Y-%m-%dT%H:%M:%S"),
                         "timezone": timezone, "duration": minutes,
                         "settings": {"join_before_host": False, "waiting_room": True}})
    r.raise_for_status()
    d = r.json()
    return {"join_url": d["join_url"], "id": str(d["id"])}


def delete_meeting(meeting_id: str) -> None:
    if configured() and meeting_id:
        httpx.delete(f"https://api.zoom.us/v2/meetings/{meeting_id}", timeout=30,
                     headers={"Authorization": f"Bearer {_access_token()}"})
