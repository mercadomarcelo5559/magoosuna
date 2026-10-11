"""Sitio SEO: páginas por giro x ciudad, blog (2 por semana), calculadora y sitemap."""
from __future__ import annotations

import ftplib
import json
import logging
import re
import unicodedata
from urllib.parse import quote

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import llm
from .config import ROOT, env, public_url, settings
from .content import CAL_SYSTEM
from .timeutil import local_naive

log = logging.getLogger(__name__)
OUT = ROOT / "data" / "site_out"
CACHE = ROOT / "data" / "seo"
TEMPLATES = ROOT / "site_templates"

BLOG_TOPICS = [
    "Cómo cobrar mensualidades sin perseguir a los papás",
    "7 formas de reducir la morosidad en tu academia",
    "Plantillas de recordatorio de pago por WhatsApp (listas para copiar)",
    "Pago en OXXO para academias: cómo funciona y por qué sube la cobranza",
    "Cuánto le cuesta a tu gimnasio cada pago atrasado",
    "Cómo escribir un reglamento de pagos para tu academia",
    "Excel vs software de cobranza: cuándo dar el salto",
    "Qué hacer cuando un alumno debe 2 meses",
    "Recargos por pago tardío: ¿sí o no?",
    "Cómo cobrar inscripción y mensualidad sin confusiones",
    "Domiciliación con tarjeta para academias pequeñas",
    "Cómo comunicar un aumento de mensualidad sin perder alumnos",
]


def slugify(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def jenv() -> Environment:
    return Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))


def wa_link(text: str) -> str:
    return f"https://wa.me/{env('WHATSAPP_PUBLIC_NUMBER')}?text={quote(text)}"


# ---------------- Calculadora ----------------

def calc_loss(students: int, fee: float, late_pct: float) -> dict:
    """Modelo simple y explicable:
    - atrasado al mes = alumnos × mensualidad × % atraso
    - 25% de lo atrasado nunca se recupera (bajas sin pagar)
    - 10 min de seguimiento por pago atrasado, valuados a $150/h
    """
    students, fee, late_pct = max(0, int(students)), max(0.0, float(fee)), min(100.0, max(0.0, float(late_pct)))
    late_month = students * fee * late_pct / 100
    late_year = late_month * 12
    never = late_year * 0.25
    late_count_year = students * late_pct / 100 * 12
    hours = late_count_year * 10 / 60
    time_cost = hours * 150
    return {"atrasado_mes": round(late_month), "atrasado_anual": round(late_year),
            "no_recuperado": round(never), "horas_persiguiendo": round(hours),
            "costo_tiempo": round(time_cost), "perdida_anual": round(never + time_cost)}


# ---------------- Contenido por giro x ciudad ----------------

def _page_content(giro: str, ciudad: str) -> dict:
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"page-{slugify(giro)}-{slugify(ciudad)}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    data = llm.ask_json(CAL_SYSTEM, f"""Escribe el contenido de una landing page SEO para "software de cobranza para {giro} en {ciudad}".
Debe ser útil y específica del giro (cómo cobran normalmente, problemas típicos de pago, temporadas, inscripciones, uniformes, etc.) y mencionar {ciudad} con naturalidad (sin relleno ni repetir la ciudad en cada frase). No inventes clientes, cifras de clientes ni testimonios.
JSON: {{"title": "<60 caracteres>", "meta": "<155 caracteres>", "h1": "...", "intro": "2 párrafos",
"problemas": ["4 problemas típicos de cobranza en este giro"], "como_ayuda": ["5 beneficios concretos de Pagoya para este giro"],
"faq": [{{"q": "...", "a": "..."}}] (4 preguntas, incluye una de precio que diga que depende del número de alumnos y empieza en $399 al mes)}}""",
                         max_tokens=8000, effort="low")
    f.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data


def _cities() -> list[str]:
    return [c.split(",")[0] for c in settings()["prospecting"]["cities"]]


GIRO_SEO = {
    "natación": "academias de natación", "idiomas": "escuelas de idiomas", "música": "academias de música",
    "artes marciales": "academias de artes marciales", "gimnasia": "escuelas de gimnasia",
    "guardería": "guarderías", "gimnasio": "gimnasios", "crossfit": "boxes de crossfit",
    "box": "gimnasios de box", "pilates": "estudios de pilates", "yoga": "estudios de yoga",
    "baile": "academias de baile", "pádel y tenis": "clubes de pádel y tenis",
}


def build_site(generate_missing: bool = True, max_new: int = 400) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    e = jenv()
    site = env("SITE_URL", "https://www.pagoya.com.mx").rstrip("/")
    urls, pages, new = [], [], 0
    for giro in settings()["prospecting"]["categories"]:
        for ciudad in _cities():
            name = GIRO_SEO.get(giro, giro)
            cache = CACHE / f"page-{slugify(name)}-{slugify(ciudad)}.json"
            if not cache.exists():
                if not generate_missing or new >= max_new:
                    continue
                new += 1
            try:
                c = _page_content(name, ciudad)
            except Exception as ex:  # noqa: BLE001
                log.warning("No se generó %s/%s: %s", name, ciudad, ex)
                continue
            slug = f"software-cobranza-{slugify(name)}-{slugify(ciudad)}"
            path = OUT / "cobranza" / slug / "index.html"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(e.get_template("landing.html").render(
                c=c, giro=name, ciudad=ciudad, canonical=f"{site}/cobranza/{slug}/",
                wa=wa_link(f"Hola, vi su página de {name} en {ciudad} y quiero agendar una demo de Pagoya"),
                api=public_url()), encoding="utf-8")
            urls.append(f"{site}/cobranza/{slug}/")
            pages.append({"url": f"/cobranza/{slug}/", "title": c["h1"], "giro": name, "ciudad": ciudad})
    # índice
    (OUT / "cobranza").mkdir(parents=True, exist_ok=True)
    (OUT / "cobranza" / "index.html").write_text(e.get_template("index.html").render(
        pages=pages, wa=wa_link("Hola, quiero agendar una demo de Pagoya")), encoding="utf-8")
    urls.append(f"{site}/cobranza/")
    # blog
    posts = sorted(CACHE.glob("blog-*.json"), reverse=True)
    blog_items = []
    for f in posts:
        b = json.loads(f.read_text(encoding="utf-8"))
        p = OUT / "blog" / b["slug"] / "index.html"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(e.get_template("blog_post.html").render(
            b=b, canonical=f"{site}/blog/{b['slug']}/",
            wa=wa_link("Hola, leí su blog y quiero agendar una demo de Pagoya")), encoding="utf-8")
        urls.append(f"{site}/blog/{b['slug']}/")
        blog_items.append(b)
    (OUT / "blog").mkdir(parents=True, exist_ok=True)
    (OUT / "blog" / "index.html").write_text(e.get_template("blog_index.html").render(
        posts=blog_items, wa=wa_link("Hola, quiero agendar una demo de Pagoya")), encoding="utf-8")
    urls.append(f"{site}/blog/")
    # calculadora
    (OUT / "calculadora").mkdir(parents=True, exist_ok=True)
    (OUT / "calculadora" / "index.html").write_text(e.get_template("calculadora.html").render(
        api=public_url(), canonical=f"{site}/calculadora/",
        wa=wa_link("Hola, usé la calculadora y quiero agendar una demo de Pagoya")), encoding="utf-8")
    urls.append(f"{site}/calculadora/")
    today = local_naive().date().isoformat()
    (OUT / "sitemap-pagoya.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "".join(f"<url><loc>{u}</loc><lastmod>{today}</lastmod></url>\n" for u in urls) + "</urlset>\n",
        encoding="utf-8")
    return {"pages": len(pages), "new_pages": new, "blog_posts": len(blog_items), "urls": len(urls)}


def write_blog_post() -> str:
    CACHE.mkdir(parents=True, exist_ok=True)
    done = {json.loads(f.read_text(encoding="utf-8")).get("topic") for f in CACHE.glob("blog-*.json")}
    topic = next((t for t in BLOG_TOPICS if t not in done), None)
    if topic is None:
        topic = llm.ask(CAL_SYSTEM, "Propón UN título nuevo de artículo de blog sobre cobranza para academias "
                                    f"que no repita estos: {sorted(done)}. Solo el título.", max_tokens=500,
                        effort="low").strip().strip('"')
    data = llm.ask_json(CAL_SYSTEM, f"""Escribe un artículo de blog: "{topic}".
900 a 1,300 palabras, útil y práctico para dueños de academias y gimnasios en México, con ejemplos concretos. Menciona Pagoya solo al final como una opción (no todo el artículo). No inventes estadísticas con fuente falsa.
JSON: {{"title": "...", "meta": "<155 caracteres>", "html": "cuerpo en HTML usando solo <h2>, <h3>, <p>, <ul>, <li>, <strong>"}}""")
    data["topic"] = topic
    data["slug"] = slugify(data["title"])[:80]
    data["date"] = local_naive().date().isoformat()
    data["html"] = re.sub(r"<(?!/?(h2|h3|p|ul|ol|li|strong|em|br)\b)[^>]*>", "", data["html"])
    (CACHE / f"blog-{data['date']}-{data['slug']}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data["title"]


def deploy_ftp() -> str:
    host = env("SITE_FTP_HOST")
    if not host:
        return "FTP no configurado: el sitio se sirve desde el servidor del agente"
    with ftplib.FTP_TLS(host, env("SITE_FTP_USER"), env("SITE_FTP_PASSWORD"), timeout=60) as ftp:
        ftp.prot_p()
        base = env("SITE_FTP_DIR", "/public_html").rstrip("/")
        for f in OUT.rglob("*"):
            if f.is_dir():
                continue
            rel = f.relative_to(OUT)
            cur = base
            for part in rel.parts[:-1]:
                cur = f"{cur}/{part}"
                try:
                    ftp.mkd(cur)
                except ftplib.error_perm:
                    pass
            with open(f, "rb") as fh:
                ftp.storbinary(f"STOR {base}/{rel.as_posix()}", fh)
    return "ok"


def weekly_seo_job() -> dict:
    title = write_blog_post()
    res = build_site(generate_missing=True, max_new=40)  # 40 páginas nuevas por corrida
    res["blog"] = title
    try:
        res["deploy"] = deploy_ftp()
    except Exception as e:  # noqa: BLE001
        res["deploy"] = f"error: {e}"
    return res
