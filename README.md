# YuyueAssist — Chatbot de WhatsApp para gestión de citas

> Proyecto Final de Grado Superior — DAM+ Fullstack
> **Autor:** Zhi Li
> **Centro:** CESUR
> **Curso:** 2023–2025

---

## 📌 Descripción

YuyueAssist es un chatbot conversacional integrado con **WhatsApp Cloud API** que permite a los usuarios gestionar citas en el **Salón Yuyue** de forma automática. El bot detecta intenciones del usuario y guía flujos de reserva y cancelación de citas paso a paso, con sesiones en memoria y persistencia en **Google Sheets** mediante n8n.

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
   ┌────┴────────────────┐
   │                     │
Reservas - Guardar   Reservas - Cancelar
   │                     │
   └────────┬────────────┘
            │
      Google Sheets
    (Reservas YuyueAssist)
```

---

## 🛠️ Tecnologías utilizadas

| Tecnología             | Versión | Uso                               |
| ----------------------- | -------- | --------------------------------- |
| Python                  | 3.11+    | Lenguaje principal                |
| FastAPI                 | 0.128+   | Framework API REST                |
| Uvicorn                 | 0.40+    | Servidor ASGI                     |
| httpx                   | 0.28+    | Cliente HTTP async                |
| Docker / Docker Compose | —       | Contenedorización                |
| n8n                     | —       | Orquestación de flujos           |
| Google Sheets API       | v4       | Persistencia de reservas          |
| Google OAuth2           | —       | Autenticación con Google         |
| Redis                   | —       | Caché (infraestructura incluida) |
| ngrok                   | 3.x      | Túnel HTTPS para desarrollo      |
| WhatsApp Cloud API      | v25.0    | Mensajería                       |
| Meta Developers         | —       | Plataforma de integración        |

> **Nota:** El stack incluye PostgreSQL y Redis como infraestructura preparada para producción. En la versión actual, las reservas se persisten en Google Sheets y las sesiones se gestionan en memoria con TTL de 30 minutos.

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
- Cuenta en Google Cloud con Google Sheets API y Google Drive API habilitadas
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

# Endpoint general del chatbot en n8n
N8N_ENDPOINT=http://host.docker.internal:5678/webhook/chatbot

# Endpoint para guardar reservas en Google Sheets
N8N_RESERVA_ENDPOINT=http://host.docker.internal:5678/webhook/reserva

# Endpoint para cancelar reservas en Google Sheets
N8N_CANCELAR_ENDPOINT=http://host.docker.internal:5678/webhook/cancelar

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
- `infra-db-1` — PostgreSQL (infraestructura, no activo en v1)
- `infra-redis-1` — Redis (infraestructura, no activo en v1)

### 4. Configurar Google Sheets en n8n

1. Ve a [Google Cloud Console](https://console.cloud.google.com)
2. Habilita **Google Sheets API** y **Google Drive API**
3. Crea credenciales OAuth2 → Tipo: Aplicación web
4. Añade URI de redirección: `http://localhost:5678/rest/oauth2-credential/callback`
5. En n8n → Settings → Credentials → Google Sheets OAuth2 API
6. Pega Client ID y Client Secret → Sign in with Google
7. Crea los workflows:
   - **Reservas - Guardar** → Webhook POST `/reserva` → Append Row en Google Sheets
   - **Reservas - Cancelar** → Webhook POST `/cancelar` → Get Rows + Update Row en Google Sheets

### 5. Iniciar ngrok

```bash
ngrok http 8080
```

Copia la URL HTTPS generada (ej: `https://xxxx.ngrok-free.dev`).

### 6. Configurar webhook en Meta Developers

1. Ve a [Meta Developers](https://developers.facebook.com)
2. Selecciona tu app → WhatsApp → Configuración de producción
3. En **Configure Webhooks**:
   - **URL:** `https://xxxx.ngrok-free.dev/webhook`
   - **Token:** `mi_token_webhook`
4. Suscríbete al campo **messages**

---

## 🤖 Funcionalidades del bot

### Intents detectados

| Intent        | Palabras clave                     | Respuesta                    |
| ------------- | ---------------------------------- | ---------------------------- |
| SALUDO        | hola, buenas, hey, hello           | Menú principal              |
| AYUDA         | menu, ayuda, help, opciones        | Menú principal              |
| HORARIO       | horario, hora, abierto             | Horario del Salón Yuyue     |
| SERVICIOS     | servicios, precio, corte, tinte... | Lista de servicios y precios |
| RESERVA       | reserva, cita, reservar            | Inicio flujo reserva         |
| CANCELAR_CITA | cancelar mi cita, anular mi cita   | Inicio flujo cancelación    |
| CANCELAR      | cancelar, anular                   | Abortar proceso activo       |
| HUMANO        | persona, humano, agente            | Derivar a agente             |

### Horario del Salón Yuyue

- **Lunes a Viernes:** 9:00 - 20:00
- **Sábados:** 10:00 - 15:00
- **Domingos:** Cerrado

### Servicios y precios

| Servicio            | Precio |
| ------------------- | ------ |
| Corte de pelo       | 15€   |
| Corte + lavado      | 20€   |
| Tinte completo      | 45€   |
| Mechas              | 60€   |
| Manicura            | 18€   |
| Pedicura            | 22€   |
| Manicura + Pedicura | 35€   |

### Flujo de reserva

```
Usuario: "reserva"
    │
    ▼
Bot: ¿Cómo te llamas?
    │
    ▼
Bot: ¿Qué servicio? (con lista y precios)
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
Bot: ¡Cita confirmada! ✅
    │
    ▼
n8n → Google Sheets (nueva fila)
```

### Flujo de cancelación

```
Usuario: "cancelar mi cita"
    │
    ▼
Bot: ¿Confirmas que quieres cancelar? (sí / no)
    │
    ▼
Bot: Tu cita ha sido cancelada ✅
    │
    ▼
n8n → Google Sheets (estado → "cancelada")
```

### Gestión de sesiones

- Las sesiones se mantienen en memoria con TTL de 30 minutos
- Cada usuario tiene su propio estado independiente
- Se purgan automáticamente las sesiones expiradas

---

## 🗄️ Google Sheets — Estructura de datos

| Columna    | Descripción                   | Ejemplo                   |
| ---------- | ------------------------------ | ------------------------- |
| id         | Identificador único (8 chars) | A1B2C3D4                  |
| telefono   | Número WhatsApp del usuario   | 34600000000               |
| nombre     | Nombre del cliente             | Zhi Li                    |
| servicio   | Servicio reservado             | corte                     |
| fecha      | Fecha de la cita               | 2026-06-15                |
| hora       | Hora de la cita                | 11:00                     |
| estado     | Estado de la reserva           | confirmada / cancelada    |
| created_at | Timestamp UTC de creación     | 2026-05-13T10:00:00+00:00 |

---

## 🔌 API Endpoints

### GET /webhook

Verificación del webhook de Meta.

### POST /webhook

Recepción de mensajes de WhatsApp.

**Body:**

```json
{
  "entry": [{
    "changes": [{
      "value": {
        "contacts": [{"wa_id": "34600000000"}],
        "messages": [{"text": {"body": "hola"}}]
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
  "reserva": {},
  "cancelacion": {},
  "state": {"step": "idle", "data": {}}
}
```

### GET /health

Comprobación de estado del servicio.

---

## 🧪 Pruebas

### Probar con PowerShell (Windows)

```powershell
# Hola
Invoke-WebRequest -Uri "http://localhost:8080/webhook" -Method POST -ContentType "application/json" -Body '{"entry":[{"changes":[{"value":{"contacts":[{"wa_id":"34600000000"}],"messages":[{"text":{"body":"hola"}}]}}]}]}' -UseBasicParsing

# Reservar
Invoke-WebRequest -Uri "http://localhost:8080/webhook" -Method POST -ContentType "application/json" -Body '{"entry":[{"changes":[{"value":{"contacts":[{"wa_id":"34600000000"}],"messages":[{"text":{"body":"reserva"}}]}}]}]}' -UseBasicParsing

# Cancelar cita
Invoke-WebRequest -Uri "http://localhost:8080/webhook" -Method POST -ContentType "application/json" -Body '{"entry":[{"changes":[{"value":{"contacts":[{"wa_id":"34600000000"}],"messages":[{"text":{"body":"cancelar mi cita"}}]}}]}]}' -UseBasicParsing
```

### Ver logs del gateway

```bash
docker logs infra-gateway-1 -f
```

---

## 🔄 Integración con n8n

### Workflows activos

| Workflow            | Webhook        | Función                           |
| ------------------- | -------------- | ---------------------------------- |
| Reservas - Guardar  | POST /reserva  | Añade nueva fila en Google Sheets |
| Reservas - Cancelar | POST /cancelar | Actualiza estado a "cancelada"     |

> El workflow "My workflow" (LLM) debe estar **inactivo** para que el bot local gestione las respuestas correctamente.

---

## 📝 Notas de desarrollo

- El token de acceso de Meta expira periódicamente. En producción usar token de larga duración.
- ngrok genera una URL diferente en cada reinicio. En producción usar servidor con IP fija o dominio propio.
- Las sesiones están en memoria. Si se reinicia el gateway, las sesiones activas se pierden. Para producción se recomienda migrarlas a Redis.
- PostgreSQL está incluido en el stack como infraestructura preparada para futuras versiones.

---

## 👨‍💻 Autor

**Zhi Li**
Grado Superior en Desarrollo de Aplicaciones Multiplataforma (DAM+) — Fullstack
CESUR — Curso 2023–2025

---

## 📄 Licencia

Proyecto académico — CESUR 2023–2025
