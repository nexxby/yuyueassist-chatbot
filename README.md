# YuyueAssist — Chatbot de WhatsApp con IA

> Proyecto Final de Grado Superior — DAM+ Fullstack  
> **Autor:** Zhi Li  
> **Centro:** CESUR  
> **Curso:** 2023–2025

---

## 📌 Descripción

YuyueAssist es un chatbot conversacional integrado con **WhatsApp Cloud API** que permite a los usuarios interactuar de forma automática con un asistente virtual. El bot gestiona conversaciones con sesiones en memoria, detecta intenciones del usuario y guía flujos de reserva de citas paso a paso.

El sistema se comunica con **n8n** como orquestador de flujos de trabajo, permitiendo extender la lógica del bot con automatizaciones externas sin modificar el código principal.

---

## 🏗️ Arquitectura

```
WhatsApp Cloud API (Meta)
        │
        ▼
     ngrok (túnel HTTPS)
        │
        ▼
  FastAPI Gateway (Python)
   ├── Verificación webhook (GET)
   ├── Recepción de mensajes (POST)
   ├── Lógica del chatbot (sesiones + intents)
   ├── Cliente n8n (orquestación)
   └── Envío de respuestas (WhatsApp API)
        │
        ▼
      n8n (flujos de trabajo)
        │
   ┌────┴────┐
   DB      Redis
(PostgreSQL) (caché)
```

---

## 🛠️ Tecnologías utilizadas

| Tecnología | Versión | Uso |
|---|---|---|
| Python | 3.11+ | Lenguaje principal |
| FastAPI | 0.128+ | Framework API REST |
| Uvicorn | 0.40+ | Servidor ASGI |
| httpx | 0.28+ | Cliente HTTP async |
| Docker / Docker Compose | — | Contenedorización |
| n8n | — | Orquestación de flujos |
| PostgreSQL | — | Base de datos |
| Redis | — | Caché y sesiones |
| ngrok | 3.x | Túnel HTTPS para desarrollo |
| WhatsApp Cloud API | v25.0 | Mensajería |
| Meta Developers | — | Plataforma de integración |

---

## 📁 Estructura del proyecto

```
chatbot/
├── apps/
│   └── gateway/
│       ├── app/
│       │   ├── main.py              # Punto de entrada FastAPI
│       │   ├── routes/
│       │   │   ├── webhook.py       # Lógica principal del bot
│       │   │   └── health.py        # Endpoint de salud
│       │   └── services/
│       │       └── n8n_client.py    # Cliente HTTP para n8n
│       ├── Dockerfile
│       └── pyproject.toml
├── infra/
│   ├── docker-compose.yml           # Orquestación de contenedores
│   └── .env                         # Variables de entorno
├── flows/
│   └── n8n/                         # Flujos exportados de n8n
├── docs/                            # Documentación adicional
└── requirements.txt
```

---

## ⚙️ Instalación y configuración

### Requisitos previos

- Docker Desktop instalado y en ejecución
- ngrok instalado
- Cuenta en Meta Developers con app de WhatsApp configurada
- Python 3.11+ (para desarrollo local)

### 1. Clonar el repositorio

```bash
git clone <url-del-repositorio>
cd chatbot
```

### 2. Configurar variables de entorno

Copia y edita el archivo `.env` en la carpeta `infra/`:

```env
ENV=dev
PORT=8080

DB_URL=postgresql+psycopg2://chatbot:chatbot@db:5432/chatbot
REDIS_URL=redis://redis:6379/0

N8N_ENDPOINT=http://host.docker.internal:5678/webhook/chatbot

WA_VERIFY_TOKEN=mi_token_webhook
WA_ACCESS_TOKEN=<tu_token_de_meta>
WA_PHONE_NUMBER_ID=<tu_phone_number_id>

LLM_MODEL=gpt-4o-mini
```

### 3. Levantar los contenedores

```bash
cd infra
docker compose up -d
```

Esto arranca 4 contenedores:
- `infra-gateway-1` — FastAPI en puerto 8080
- `infra-n8n-1` — n8n en puerto 5678
- `infra-db-1` — PostgreSQL
- `infra-redis-1` — Redis

### 4. Iniciar ngrok

```bash
ngrok http 8080
```

Copia la URL HTTPS generada (ej: `https://xxxx.ngrok-free.dev`).

### 5. Configurar webhook en Meta Developers

1. Ve a [Meta Developers](https://developers.facebook.com)
2. Selecciona tu app → WhatsApp → Paso 2. Configuración de producción
3. En **Configure Webhooks**:
   - **URL de devolución de llamada:** `https://xxxx.ngrok-free.dev/webhook`
   - **Identificador de verificación:** `mi_token_webhook`
4. Suscríbete al campo **messages**

---

## 🤖 Funcionalidades del bot

### Intents detectados

| Intent | Palabras clave | Respuesta |
|---|---|---|
| SALUDO | hola, buenas, hey, hello | Menú principal |
| AYUDA | menu, ayuda, help, opciones | Menú principal |
| HORARIO | horario, hora, abierto | Horario del negocio |
| SERVICIOS | servicios, precio, tarifa | Lista de servicios |
| RESERVA | reserva, cita, reservar | Inicio flujo reserva |
| CANCELAR | cancelar, anular | Cancelar proceso |
| HUMANO | persona, humano, agente | Derivar a agente |

### Flujo de reserva

```
Usuario: "reserva"
    │
    ▼
Bot: ¿Qué servicio? (corte / tinte / uñas)
    │
    ▼
Bot: ¿Para qué fecha? (YYYY-MM-DD)
    │
    ▼
Bot: ¿A qué hora? (HH:MM)
    │
    ▼
Bot: Resumen → confirmar o cancelar
    │
    ▼
Bot: Cita confirmada ✅
```

### Gestión de sesiones

- Las sesiones se mantienen en memoria con TTL de 30 minutos
- Cada usuario tiene su propio estado independiente
- Se purgan automáticamente las sesiones expiradas

---

## 🔌 API Endpoints

### GET /webhook
Verificación del webhook de Meta.

**Parámetros:**
- `hub.mode` — debe ser `subscribe`
- `hub.challenge` — challenge de Meta
- `hub.verify_token` — token de verificación

### POST /webhook
Recepción de mensajes de WhatsApp.

**Body (ejemplo):**
```json
{
  "entry": [{
    "changes": [{
      "value": {
        "contacts": [{"wa_id": "34600000000"}],
        "messages": [{
          "text": {"body": "hola"}
        }]
      }
    }]
  }]
}
```

**Respuesta:**
```json
{
  "ok": true,
  "reply": "Hola, soy YuyueAssist...",
  "user_id": "34600000000",
  "wa": {"ok": true},
  "n8n": {"ok": true},
  "state": {"step": "idle", "data": {}}
}
```

### GET /health
Comprobación de estado del servicio.

---

## 🧪 Pruebas

### Probar con Postman o curl

```bash
curl -X POST http://localhost:8080/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "entry": [{
      "changes": [{
        "value": {
          "contacts": [{"wa_id": "34600000000"}],
          "messages": [{"text": {"body": "hola"}}]
        }
      }]
    }]
  }'
```

### Ver logs del gateway

```bash
docker logs infra-gateway-1 -f
```

---

## 🔄 Integración con n8n

El gateway envía a n8n el siguiente payload en cada mensaje:

```json
{
  "user_id": "34600000000",
  "text": "hola",
  "intent": "SALUDO",
  "state": {"step": "idle", "data": {}},
  "local_reply": "Hola, soy YuyueAssist...",
  "raw": { ... }
}
```

Si n8n devuelve un campo `reply` o `text`, se prioriza sobre la respuesta local del bot.

---

## 📝 Notas de desarrollo

- El token de acceso de Meta expira periódicamente. En producción se recomienda usar un **token de larga duración** o el **token del sistema**.
- ngrok genera una URL diferente en cada reinicio (plan gratuito). Para producción se recomienda un servidor con IP fija o un dominio propio.
- Las sesiones son en memoria. Si se reinicia el gateway, las sesiones activas se pierden. Para producción se recomienda persistirlas en Redis.

---

## 👨‍💻 Autor

**Zhi Li**  
Grado Superior en Desarrollo de Aplicaciones Multiplataforma (DAM+) — Fullstack  
CESUR — Curso 2023–2025

---

## 📄 Licencia

Proyecto académico — CESUR 2023–2025
