import re
import time
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import httpx
from fastapi import APIRouter, Request, Response, Query

from ..services.n8n_client import call_flow

router = APIRouter()

# -------------------------
# Configuración
# -------------------------
N8N_RESERVA_ENDPOINT = os.getenv(
    "N8N_RESERVA_ENDPOINT",
    "http://host.docker.internal:5678/webhook/reserva"
)
N8N_CANCELAR_ENDPOINT = os.getenv(
    "N8N_CANCELAR_ENDPOINT",
    "http://host.docker.internal:5678/webhook/cancelar"
)

# -------------------------
# Información del negocio
# -------------------------
HORARIO = (
    "🕐 *Horario Salón Yuyue:*\n"
    "- Lunes a Viernes: 9:00 - 20:00\n"
    "- Sábados: 10:00 - 15:00\n"
    "- Domingos: Cerrado\n\n"
    "¿Quieres reservar una cita? Escribe 'reserva'."
)

SERVICIOS = (
    "💇 *Servicios y precios Salón Yuyue:*\n\n"
    "✂️ Corte de pelo: 15€\n"
    "✂️ Corte + lavado: 20€\n"
    "🎨 Tinte completo: 45€\n"
    "🎨 Mechas: 60€\n"
    "💅 Manicura: 18€\n"
    "💅 Pedicura: 22€\n"
    "💅 Manicura + Pedicura: 35€\n\n"
    "¿Quieres reservar? Escribe 'reserva'."
)

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
    to = "34605935947"  # Forzar número real para pruebas
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
# Guardar reserva en Google Sheets via n8n
# -------------------------
async def save_reserva_to_n8n(user_id: str, data: dict) -> dict:
    payload = {
        "id": str(uuid.uuid4())[:8].upper(),
        "telefono": user_id,
        "nombre": data.get("nombre", user_id),
        "servicio": data.get("service", ""),
        "fecha": data.get("date", ""),
        "hora": data.get("time", ""),
        "estado": "confirmada",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(N8N_RESERVA_ENDPOINT, json=payload)
            return {
                "ok": r.status_code < 400,
                "status": r.status_code,
                "payload_sent": payload,
            }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# -------------------------
# Cancelar reserva en Google Sheets via n8n
# -------------------------
async def cancel_reserva_to_n8n(user_id: str) -> dict:
    payload = {
        "telefono": user_id,
        "estado": "cancelada",
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(N8N_CANCELAR_ENDPOINT, json=payload)
            return {
                "ok": r.status_code < 400,
                "status": r.status_code,
            }
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
    if re.search(r"\b(servicios|precio|tarifa|corte|tinte|uñas|manicura|pedicura|mechas)\b", t):
        return "SERVICIOS"
    if re.search(r"\b(cancelar mi cita|anular mi cita|quiero cancelar|cancelar reserva)\b", t):
        return "CANCELAR_CITA"
    if re.search(r"\b(reserva|cita|reservar|pedir cita|agendar)\b", t):
        return "RESERVA"
    if re.search(r"\b(cancelar|anular)\b", t):
        return "CANCELAR"
    if re.search(r"\b(persona|humano|agente)\b", t):
        return "HUMANO"

    return "DESCONOCIDO"


def menu_text() -> str:
    return (
        "Hola, soy YuyueAssist 👋\n"
        "Bienvenido al Salon Yuyue.\n\n"
        "¿Qué necesitas?\n\n"
        "1️⃣ Reservar cita\n"
        "2️⃣ Horario\n"
        "3️⃣ Servicios y precios\n"
        "4️⃣ Cancelar mi cita\n\n"
        "Escribe 'reserva', 'horario', 'servicios' o 'cancelar mi cita'."
    )


def handle_chatbot(user_id: str, text: str) -> Tuple[str, Dict[str, Any]]:
    s = _get_session(user_id)
    step = s.get("step", "idle")
    data = s.get("data", {})
    intent = detect_intent(text)

    # CANCELAR FLUJO ACTIVO (abortar reserva en curso)
    if intent == "CANCELAR" and step != "idle":
        _reset_session(user_id)
        return "De acuerdo. He cancelado el proceso. Escribe 'menu' para ver opciones.", {"step": "idle", "data": {}}

    # CANCELAR CITA EXISTENTE
    if intent == "CANCELAR_CITA" and step == "idle":
        s["step"] = "confirm_cancel"
        return (
            "Voy a cancelar tu cita más reciente.\n\n"
            "¿Confirmas que quieres cancelarla? (sí / no)"
        ), {"step": s["step"], "data": s["data"]}

    if step == "confirm_cancel":
        if text.lower().strip() in ("si", "sí", "s", "ok", "confirmo"):
            _reset_session(user_id)
            return (
                "Tu cita ha sido cancelada. ✅\n"
                "Si necesitas algo más, escribe 'menu'."
            ), {"step": "idle", "data": {}, "_cancel_reserva": True}
        else:
            _reset_session(user_id)
            return "De acuerdo, tu cita sigue activa. Escribe 'menu' si necesitas algo.", {"step": "idle", "data": {}}

    # AYUDA
    if intent == "AYUDA":
        _reset_session(user_id)
        return menu_text(), {"step": "idle", "data": {}}

    # SALUDO
    if intent == "SALUDO" and step == "idle":
        return menu_text(), {"step": step, "data": data}

    # HORARIO
    if intent == "HORARIO" and step == "idle":
        return HORARIO, {"step": step, "data": data}

    # SERVICIOS
    if intent == "SERVICIOS" and step == "idle":
        return SERVICIOS, {"step": step, "data": data}

    # HUMANO
    if intent == "HUMANO" and step == "idle":
        return "Ahora mismo no hay agentes disponibles. Puedes llamarnos o escribe 'menu' para ver opciones.", {"step": step, "data": data}

    # INICIO FLUJO RESERVA
    if intent == "RESERVA" and step == "idle":
        s["step"] = "ask_name"
        return "Perfecto 😊 ¿Cómo te llamas?", {"step": s["step"], "data": s["data"]}

    # PASO 1: Nombre
    if step == "ask_name":
        nombre = text.strip()
        if len(nombre) < 2:
            return "Por favor, dime tu nombre completo.", {"step": s["step"], "data": s["data"]}
        s["data"]["nombre"] = nombre
        s["step"] = "ask_service"
        return (
            f"Encantado, {nombre} 👋\n\n"
            "¿Qué servicio quieres reservar?\n\n"
            "✂️ Corte de pelo - 15€\n"
            "✂️ Corte + lavado - 20€\n"
            "🎨 Tinte completo - 45€\n"
            "🎨 Mechas - 60€\n"
            "💅 Manicura - 18€\n"
            "💅 Pedicura - 22€\n"
            "💅 Manicura + Pedicura - 35€"
        ), {"step": s["step"], "data": s["data"]}

    # PASO 2: Servicio
    if step == "ask_service":
        s["data"]["service"] = text.strip()
        s["step"] = "ask_date"
        return (
            "Genial. ¿Para qué fecha?\n"
            "Formato: YYYY-MM-DD (ej: 2026-06-15)\n\n"
            "Recuerda que abrimos L-V 9:00-20:00 y S 10:00-15:00."
        ), {"step": s["step"], "data": s["data"]}

    # PASO 3: Fecha
    if step == "ask_date":
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text.strip()):
            return "Formato de fecha no válido. Usa YYYY-MM-DD (ej: 2026-06-15).", {"step": s["step"], "data": s["data"]}
        s["data"]["date"] = text.strip()
        s["step"] = "ask_time"
        return "Perfecto. ¿A qué hora? (formato: HH:MM, ej: 10:30)", {"step": s["step"], "data": s["data"]}

    # PASO 4: Hora
    if step == "ask_time":
        if not re.fullmatch(r"\d{2}:\d{2}", text.strip()):
            return "Formato de hora no válido. Usa HH:MM (ej: 10:30).", {"step": s["step"], "data": s["data"]}
        s["data"]["time"] = text.strip()
        s["step"] = "confirm"
        nombre = s["data"].get("nombre", "")
        service = s["data"].get("service", "")
        date = s["data"].get("date", "")
        hour = s["data"].get("time", "")
        return (
            f"📋 Resumen de tu cita:\n"
            f"- Nombre: {nombre}\n"
            f"- Servicio: {service}\n"
            f"- Fecha: {date}\n"
            f"- Hora: {hour}\n\n"
            "Responde 'sí' para confirmar o 'cancelar' para anular."
        ), {"step": s["step"], "data": s["data"]}

    # PASO 5: Confirmación reserva
    if step == "confirm":
        if text.lower().strip() in ("si", "sí", "s", "ok", "confirmo", "confirmar"):
            reserva_data = dict(s["data"])
            _reset_session(user_id)
            nombre = reserva_data.get("nombre", "")
            return (
                f"✅ ¡Cita confirmada, {nombre}! Te esperamos en el Salón Yuyue.\n"
                "Si necesitas algo más, escribe 'menu'."
            ), {"step": "idle", "data": reserva_data, "_save_reserva": True}
        return "Responde 'sí' para confirmar o 'cancelar' para anular.", {"step": s["step"], "data": s["data"]}

    # IDLE sin intent reconocido
    if step == "idle":
        return "No te he entendido 🤔 Escribe 'menu' para ver opciones.", {"step": step, "data": data}

    return "Escribe 'menu' para empezar de nuevo.", {"step": step, "data": data}


# -------------------------
# Webhook POST (mensajes)
# -------------------------
@router.post("")
async def whatsapp_webhook(req: Request):
    body = await req.json()
    text, user_id = extract_whatsapp_text_and_user(body)

    # Generar respuesta del chatbot
    local_reply, state_snapshot = handle_chatbot(user_id=user_id, text=text)

    # Guardar reserva confirmada en Sheets
    reserva_result = {}
    if state_snapshot.get("_save_reserva") is True:
        reserva_result = await save_reserva_to_n8n(user_id, state_snapshot["data"])

    # Cancelar reserva en Sheets
    cancel_result = {}
    if state_snapshot.get("_cancel_reserva") is True:
        cancel_result = await cancel_reserva_to_n8n(user_id)

    # Notificar a n8n del mensaje (flujo general)
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

    # Enviar respuesta a WhatsApp
    wa_result = {}
    if user_id != "anonymous" and text:
        wa_result = await send_whatsapp_message(to=user_id, text=reply)

    return {
        "ok": True,
        "reply": reply,
        "user_id": user_id,
        "wa": wa_result,
        "n8n": n8n_result,
        "reserva": reserva_result,
        "cancelacion": cancel_result,
        "state": state_snapshot,
    }


@router.post("/whatsapp")
async def whatsapp_webhook_alias(req: Request):
    return await whatsapp_webhook(req)