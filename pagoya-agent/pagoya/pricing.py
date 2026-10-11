from .config import settings


def plan_for(students: int) -> dict:
    cfg = settings()["pricing"]
    for p in cfg["plans"]:
        if students >= p["min"] and (p["max"] is None or students <= p["max"]):
            return p
    return cfg["plans"][0]


def quote(students: int) -> dict:
    cfg = settings()["pricing"]
    p = plan_for(max(1, int(students)))
    annual = p["monthly"] * (12 - cfg["annual_free_months"])
    desde = "desde " if p.get("from") else ""
    rango = f"{p['min']} a {p['max']}" if p["max"] else f"más de {p['min'] - 1}"
    return {
        "plan": p["name"],
        "range": rango,
        "monthly": p["monthly"],
        "annual": annual,
        "text": (f"Plan {p['name']} ({rango} alumnos): {desde}${p['monthly']:,} al mes, IVA incluido. "
                 f"Si pagas anual son {desde}${annual:,} (te regalamos {cfg['annual_free_months']} meses)."),
    }
