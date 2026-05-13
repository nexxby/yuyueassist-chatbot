import re
import time
import os
from typing import Any, Dict, Optional, Tuple

import httpx
from fastapi import APIRouter, Request, Response, Query

from ..services.n8n_client import call_flow

router = APIRouter()

# -------------------------
# Estado en memoria (sin BD)
# -------------------------
sessions: Dict[str, Dict[str, Any]] = {}
SESSION_TTL_SECONDS = 30 * 60  # 30 min


def _now() -> float:
    return time.time()


def _purge_sessions() -> None:
    cutoff = _now() - SESSION_TTL_SECONDS
    for k in list(sessions.keys()):
        if sessions[k].get("ts", 0) < cutoff:
            sessions.pop(k, None)


def _get_session(user_id: str) -> Dict[str, Any]:
    _purge_sessions()
    s = sessions.get(user_id)
    if not s:
        s = {"step": "idle", "data": {}, "ts": _now()}
        sessions[user_id] = s
    s["ts"] = _now()
    return s


def _reset_session(user_id: str) -> None:
    sessions[user_id] = {"step": "idle", "data": {}, "ts": _now()}


# -------------------------
# Enviar mensaje a WhatsApp
# -------------------------
async def send_whatsapp_message(to: str, text: str) -> dict:
    token = os.getenv("WA_ACCESS_TOKEN", "")
    phone_number_id = os.getenv("WA_PHONE_NUMBER_ID", "")

    if not token or not phone_number_id:
        return {"ok": False, "error": "WA_ACCESS_TOKEN o WA_PHONE_NUMBER_ID no configurados"}

    url = f"https://graph.facebook.com/v25.0/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(url, json=payload, headers=headers)
            return {"ok": r.status_code == 200, "status": r.status_code, "body": r.text}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# -------------------------
# Verificación Meta (GET)
# -------------------------
@router.get("")
def verify_webhook(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
):
    if hub_mode == "subscribe" and hub_verify_token == os.getenv("WA_VERIFY_TOKEN"):
        return Response(content=hub_challenge or "", media_type="text/plain", status_code=200)
    return Response(content="Forbidden", media_type="text/plain", status_code=403)


@router.get("/whatsapp")
def verify_webhook_alias(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
):
    return verify_webhook(hub_mode, hub_challenge, hub_verify_token)


# -------------------------
# Parsing WhatsApp payload
# -------------------------
def extract_whatsapp_text_and_user(body: dict) -> Tuple[str, str]:
    try:
        entry = (body.get("entry") or [])[0]
        change = (entry.get("changes") or [])[0]
        value = change.get("value") or {}

        contacts = value.get("contacts") or []
        wa_id = "anonymous"
        if contacts and isinstance(contacts[0], dict) and contacts[0].get("wa_id"):
            wa_id = str(contacts[0]["wa_id"])

        messages = value.get("messages") or []
        if messages and isinstance(messages[0], dict):
            msg0 = messages[0]
            text_obj = msg0.get("text") or {}
            if isinstance(text_obj, dict) and isinstance(text_obj.get("body"), str):
                return text_obj["body"].strip(), wa_id

        return "", wa_id
    except Exception:
        if isinstance(body.get("text"), str):
            return body["text"].strip(), "anonymous"
        return "", "anonymous"


# -------------------------
# Intent detection
# -------------------------
def detect_intent(text: str) -> str:
    t = text.lower().strip()

    if not t:
        return "EMPTY"
    if re.search(r"\b(hola|buenas|hey|hello)\b", t):
        return "SALUDO"
    if re.search(r"\b(menu|ayuda|help|opciones)\b", t):
        return "AYUDA"
    if re.search(r"\b(horario|hora|abiert|cerrad)\b", t):
        return "HORARIO"
    if re.search(r"\b(servicios|precio|tarifa|corte|tinte|uñas)\b", t):
        return "SERVICIOS"
    if re.search(r"\b(reserva|cita|reservar|pedir cita|agendar)\b", t):
        return "RESERVA"
    if re.search(r"\b(cancelar|anular)\b", t):
        return "CANCELAR"
    if re.search(r"\b(persona|humano|agente)\b", t):
        return "HUMANO"

    return "DESCONOCIDO"


def menu_text() -> str:
    return (
        "Hola, soy YuyueAssist.\n"
        "¿Qué necesitas?\n"
        "1) Reservar cita\n"
        "2) Horario\n"
        "3) Servicios y precios\n"
        "Responde con el número o escribe 'reserva', 'horario' o 'servicios'."
    )


def handle_chatbot(user_id: str, text: str) -> Tuple[str, Dict[str, Any]]:
    s = _get_session(user_id)
    step = s.get("step", "idle")
    data = s.get("data", {})
    intent = detect_intent(text)

    if intent == "CANCELAR":
        _reset_session(user_id)
        return "De acuerdo. He cancelado el proceso. Si necesitas algo más, escribe 'menu'.", {"step": "idle", "data": {}}

    if intent == "AYUDA":
        _reset_session(user_id)
        return menu_text(), {"step": "idle", "data": {}}

    if intent == "SALUDO" and step == "idle":
        return menu_text(), {"step": step, "data": data}

    if intent == "HORARIO" and step == "idle":
        return "Horario habitual: L-V 10:00-20:00, S 10:00-14:00. ¿Quieres reservar una cita?", {"step": step, "data": data}

    if intent == "SERVICIOS" and step == "idle":
        return (
            "Servicios (ejemplo):\n"
            "- Corte: desde 12€\n"
            "- Tinte: desde 25€\n"
            "- Uñas: desde 20€\n"
            "Si quieres, puedo ayudarte a reservar. Escribe 'reserva'."
        ), {"step": step, "data": data}

    if intent == "RESERVA" and step == "idle":
        s["step"] = "ask_service"
        return "Perfecto. ¿Qué servicio quieres reservar? (corte / tinte / uñas)", {"step": s["step"], "data": s["data"]}

    if step == "ask_service":
        s["data"]["service"] = text.strip()
        s["step"] = "ask_date"
        return "Genial. ¿Para qué fecha? (ej: 2026-01-25)", {"step": s["step"], "data": s["data"]}

    if step == "ask_date":
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text.strip()):
            return "Formato de fecha no válido. Usa YYYY-MM-DD (ej: 2026-01-25).", {"step": s["step"], "data": s["data"]}
        s["data"]["date"] = text.strip()
        s["step"] = "ask_time"
        return "Perfecto. ¿A qué hora? (ej: 17:30)", {"step": s["step"], "data": s["data"]}

    if step == "ask_time":
        if not re.fullmatch(r"\d{2}:\d{2}", text.strip()):
            return "Formato de hora no válido. Usa HH:MM (ej: 17:30).", {"step": s["step"], "data": s["data"]}
        s["data"]["time"] = text.strip()
        s["step"] = "confirm"
        service = s["data"].get("service", "")
        date = s["data"].get("date", "")
        hour = s["data"].get("time", "")
        return (
            f"Resumen de tu cita:\n"
            f"- Servicio: {service}\n"
            f"- Fecha: {date}\n"
            f"- Hora: {hour}\n"
            "Responde 'sí' para confirmar o 'cancelar' para anular."
        ), {"step": s["step"], "data": s["data"]}

    if step == "confirm":
        if text.lower().strip() in ("si", "sí", "s", "ok", "confirmo", "confirmar"):
            s["step"] = "idle"
            return "Perfecto. Tu solicitud de cita está confirmada. Te contactaremos si hay algún ajuste.", {"step": "idle", "data": s["data"]}
        return "Entendido. Si quieres confirmar, responde 'sí'. Si no, escribe 'cancelar'.", {"step": s["step"], "data": s["data"]}

    if step == "idle":
        return "No te he entendido. Escribe 'menu' para ver opciones.", {"step": step, "data": data}

    return "Estoy procesando tu solicitud. Escribe 'menu' para empezar de nuevo.", {"step": step, "data": data}


# -------------------------
# Webhook POST (mensajes)
# -------------------------
@router.post("")
async def whatsapp_webhook(req: Request):
    body = await req.json()
    text, user_id = extract_whatsapp_text_and_user(body)

    # Generar respuesta
    local_reply, state_snapshot = handle_chatbot(user_id=user_id, text=text)

    # Intentar n8n
    n8n_payload = {
        "user_id": user_id,
        "text": text,
        "intent": detect_intent(text),
        "state": state_snapshot,
        "raw": body,
        "local_reply": local_reply,
    }
    n8n_result = await call_flow(n8n_payload)

    reply = local_reply
    if n8n_result.get("ok") is True:
        data = n8n_result.get("data") or {}
        if isinstance(data, dict):
            if isinstance(data.get("reply"), str) and data["reply"].strip():
                reply = data["reply"].strip()
            elif isinstance(data.get("text"), str) and data["text"].strip():
                reply = data["text"].strip()

    # Enviar respuesta a WhatsApp si tenemos un user_id real
    wa_result = {}
    if user_id != "anonymous" and text:
        wa_result = await send_whatsapp_message(to=user_id, text=reply)

    return {
        "ok": True,
        "reply": reply,
        "user_id": user_id,
        "wa": wa_result,
        "n8n": n8n_result,
        "state": state_snapshot,
    }


@router.post("/whatsapp")
async def whatsapp_webhook_alias(req: Request):
    return await whatsapp_webhook(req)