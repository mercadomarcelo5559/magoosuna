"""Normalización de teléfonos mexicanos a +52XXXXXXXXXX y detección de celulares.

Desde 2019 todos los números en México tienen 10 dígitos y ya no se marca 044/045/01,
así que el prefijo NO dice si es celular. Para distinguir celular de fijo usamos el
Plan de Numeración público del IFT (archivo CSV opcional en data/ift_numeracion.csv).
Si no está, el número queda como "unknown" y WhatsApp nos dirá si no se puede entregar
(error 131026), en cuyo caso se marca como sin WhatsApp y no se vuelve a intentar.
"""
from __future__ import annotations

import csv
import re
from functools import lru_cache

from .config import ROOT

IFT_PATH = ROOT / "data" / "ift_numeracion.csv"


def normalize_mx(raw: str | None) -> str | None:
    """Devuelve +52 + 10 dígitos, o None si no es un número mexicano válido."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("52") and len(digits) in (12, 13):
        digits = digits[2:]
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]  # formato viejo +52 1 para celulares / wa_id
    elif len(digits) == 13 and digits[:3] in ("044", "045"):
        digits = digits[3:]
    elif len(digits) == 12 and digits.startswith("01"):
        digits = digits[2:]
    if len(digits) != 10 or digits[0] == "0":
        return None
    return "+52" + digits


def wa_number(e164: str) -> str:
    """Formato que espera la Cloud API: sin '+'."""
    return e164.lstrip("+")


@lru_cache
def _ift_index() -> dict[str, list[tuple[int, int, str]]]:
    idx: dict[str, list[tuple[int, int, str]]] = {}
    if not IFT_PATH.exists():
        return idx
    with open(IFT_PATH, encoding="latin-1", newline="") as f:
        reader = csv.DictReader(f)
        cols = {c.upper().strip(): c for c in (reader.fieldnames or [])}

        def col(*keys):
            for k, orig in cols.items():
                if all(x in k for x in keys):
                    return orig
            return None

        c_nir, c_serie = col("NIR"), col("SERIE")
        c_ini, c_fin = col("INICIAL"), col("FINAL")
        c_tipo = col("TIPO", "RED") or col("MODALIDAD") or col("TIPO")
        if not all([c_nir, c_serie, c_ini, c_fin, c_tipo]):
            return idx
        for row in reader:
            try:
                prefix = f"{int(row[c_nir])}{int(row[c_serie]):0{6 - len(str(int(row[c_nir])))}d}"
                kind = "mobile" if "MOV" in row[c_tipo].upper().replace("Ó", "O") else "fixed"
                idx.setdefault(prefix, []).append((int(row[c_ini]), int(row[c_fin]), kind))
            except (ValueError, TypeError, KeyError):
                continue
    return idx


def phone_kind(e164: str) -> str:
    """'mobile', 'fixed' o 'unknown' (sin datos del IFT)."""
    idx = _ift_index()
    if not idx or not e164:
        return "unknown"
    n = e164[-10:]
    for start, end, kind in idx.get(n[:6], []):
        if start <= int(n[6:]) <= end:
            return kind
    return "unknown"


def can_have_whatsapp(e164: str) -> bool:
    return phone_kind(e164) != "fixed"
