"""Plantillas de WhatsApp para someter a aprobación de Meta (python -m pagoya templates)."""
from __future__ import annotations

import httpx

from .config import env, graph_version, public_url, settings

BAJA_FOOTER = "Responde BAJA si no te interesa"


def definitions() -> list[dict]:
    t = settings()["whatsapp"]["templates"]
    lang = settings()["whatsapp"]["template_language"]
    qr = {"type": "BUTTONS", "buttons": [{"type": "QUICK_REPLY", "text": "Sí, me interesa"},
                                         {"type": "QUICK_REPLY", "text": "BAJA"}]}
    defs = [
        {"name": t["invitation"], "category": "MARKETING", "language": lang, "components": [
            {"type": "BODY", "text": "Hola, ¿qué tal equipo de {{1}}? Soy Marcelo de Pagoya. Ayudamos a {{2}} a "
                                     "cobrar sus mensualidades sin perseguir a nadie: recordatorios automáticos "
                                     "por WhatsApp y pagos con tarjeta u OXXO. ¿Te muestro en 15 minutos cómo funciona?",
             "example": {"body_text": [["Academia Delfines", "academias de natación"]]}},
            {"type": "FOOTER", "text": BAJA_FOOTER}, qr]},
        {"name": t["followup"], "category": "MARKETING", "language": lang, "components": [
            {"type": "BODY", "text": "Hola de nuevo, equipo de {{1}}. Te escribí hace unos días sobre Pagoya: "
                                     "nosotros cargamos tu lista de alumnos gratis y en un día ya mandas "
                                     "recordatorios y cobras con tarjeta u OXXO. ¿Te agendo una demo de 15 minutos?",
             "example": {"body_text": [["Academia Delfines"]]}},
            {"type": "FOOTER", "text": BAJA_FOOTER}, qr]},
        {"name": t["calculator"], "category": "MARKETING", "language": lang, "components": [
            {"type": "BODY", "text": "Hola {{1}}, soy Marcelo de Pagoya. Vi tu resultado en la calculadora: "
                                     "{{2}} podría estar perdiendo ${{3}} al año por pagos atrasados. ¿Te muestro "
                                     "en 15 minutos cómo recuperarlo con recordatorios automáticos y pagos en OXXO?",
             "example": {"body_text": [["Ana", "Academia Delfines", "48,000"]]}},
            {"type": "FOOTER", "text": BAJA_FOOTER},
            {"type": "BUTTONS", "buttons": [{"type": "QUICK_REPLY", "text": "Agendar demo"},
                                            {"type": "QUICK_REPLY", "text": "BAJA"}]}]},
        {"name": t["referral_invite"], "category": "MARKETING", "language": lang, "components": [
            {"type": "BODY", "text": "¡Hola {{1}}! Ya cumpliste un mes con Pagoya. Si recomiendas a otra academia "
                                     "y se vuelve cliente, tú ganas 1 mes gratis y ellos 50% de descuento en su "
                                     "primer mes. Tu código es {{2}}.",
             "example": {"body_text": [["Ana", "PYAB12C"]]}},
            {"type": "BUTTONS", "buttons": [{"type": "URL", "text": "Mi link para compartir",
                                             "url": public_url("/r/{{1}}"), "example": [public_url("/r/PYAB12C")]}]}]},
        {"name": t["demo_reminder"], "category": "UTILITY", "language": lang, "components": [
            {"type": "BODY", "text": "Hola {{1}}, te recuerdo tu demo de Pagoya hoy a las {{2}} (hora de Monterrey). "
                                     "Entra aquí: {{3}}",
             "example": {"body_text": [["Ana", "11:00", "https://zoom.us/j/123456789"]]}}]},
    ]
    if env("GOOGLE_REVIEW_LINK"):
        defs.append({"name": t["review_request"], "category": "MARKETING", "language": lang, "components": [
            {"type": "BODY", "text": "Hola {{1}}, ¿cómo te ha ido con Pagoya? Si te está ayudando a cobrar, "
                                     "una reseña en Google nos ayudaría muchísimo. ¡Gracias!",
             "example": {"body_text": [["Ana"]]}},
            {"type": "BUTTONS", "buttons": [{"type": "URL", "text": "Dejar reseña", "url": env("GOOGLE_REVIEW_LINK")}]}]})
    return defs


def submit_all() -> list[dict]:
    waba = env("WHATSAPP_BUSINESS_ACCOUNT_ID")
    out = []
    for d in definitions():
        r = httpx.post(f"https://graph.facebook.com/{graph_version()}/{waba}/message_templates",
                       headers={"Authorization": f"Bearer {env('WHATSAPP_TOKEN')}"}, json=d, timeout=30)
        out.append({"name": d["name"], "status": r.status_code, "response": r.json() if r.content else {}})
    return out
