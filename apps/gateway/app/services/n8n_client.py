# import os, httpx

# N8N_ENDPOINT = os.getenv("N8N_ENDPOINT", "")

# async def call_flow(payload: dict) -> dict:
#     async with httpx.AsyncClient(timeout=15) as client:
#         r = await client.post(N8N_ENDPOINT, json=payload)
#         r.raise_for_status()
#         return r.json()

import os
import asyncio
import random
from typing import Any, Dict, Optional

import httpx

N8N_ENDPOINT = os.getenv("N8N_ENDPOINT", "").strip()

# Timeouts razonables para no bloquear el webhook.
_TIMEOUT = httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=5.0)

# Reintentos cortos (no te interesa que Meta espere demasiado).
_MAX_RETRIES = int(os.getenv("N8N_MAX_RETRIES", "2"))  # 0,1,2...
_BASE_BACKOFF = float(os.getenv("N8N_BACKOFF_SECONDS", "0.25"))


class N8NError(RuntimeError):
    pass


async def _sleep_backoff(attempt: int) -> None:
    # Exponential backoff con jitter pequeño
    delay = _BASE_BACKOFF * (2 ** attempt) + random.uniform(0, 0.15)
    await asyncio.sleep(delay)


async def call_flow(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Llama a un webhook de n8n con JSON y devuelve dict.

    Nunca lanza excepciones "brutas" hacia arriba: si falla, devuelve:
      {"ok": False, "error": "...", "provider": "n8n"}
    """
    if not N8N_ENDPOINT:
        return {"ok": False, "error": "N8N_ENDPOINT no configurado", "provider": "n8n"}

    last_err: Optional[str] = None

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for attempt in range(_MAX_RETRIES + 1):
            try:
                r = await client.post(N8N_ENDPOINT, json=payload)
                # Reintentar 5xx (n8n caído / intermitente)
                if 500 <= r.status_code <= 599:
                    last_err = f"n8n 5xx: {r.status_code}"
                    if attempt < _MAX_RETRIES:
                        await _sleep_backoff(attempt)
                        continue
                    return {"ok": False, "error": last_err, "provider": "n8n"}

                # Errores 4xx: normalmente payload mal formado -> no reintentar
                if r.status_code >= 400:
                    return {
                        "ok": False,
                        "error": f"n8n {r.status_code}: {r.text[:300]}",
                        "provider": "n8n",
                    }

                # JSON esperado
                try:
                    data = r.json()
                except Exception:
                    # Si n8n devolviera texto plano
                    return {"ok": True, "data": {"text": r.text}, "provider": "n8n"}

                # Normalizamos
                if isinstance(data, dict):
                    return {"ok": True, "data": data, "provider": "n8n"}
                return {"ok": True, "data": {"value": data}, "provider": "n8n"}

            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout, httpx.RemoteProtocolError) as e:
                last_err = f"network: {type(e).__name__}"
                if attempt < _MAX_RETRIES:
                    await _sleep_backoff(attempt)
                    continue
                return {"ok": False, "error": last_err, "provider": "n8n"}
            except Exception as e:
                return {"ok": False, "error": f"unexpected: {e}", "provider": "n8n"}
