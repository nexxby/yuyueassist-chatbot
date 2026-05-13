from fastapi import FastAPI
from .routes import webhook, health

app = FastAPI(title="chatbot-gateway")

app.include_router(
    health.router,
    prefix="/health",
    tags=["health"]
)

app.include_router(
    webhook.router,
    prefix="/webhook",
    tags=["webhook"]
)
