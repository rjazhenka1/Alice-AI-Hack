"""FastAPI application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .auth import router as auth_router
from .api.agent import router as agent_router
from .api.events import router as events_router
from .api.integrations import router as integrations_router
from .api.knowledge import router as knowledge_router
from .api.messages import router as messages_router
from .api.staff import router as staff_router
from .api.tickets import router as tickets_router
from .database import init_models
from .notifier import start_notifier_worker, stop_notifier_worker


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_models()
    start_notifier_worker()
    try:
        yield
    finally:
        await stop_notifier_worker()


app = FastAPI(title="EventOps AI", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(events_router)
app.include_router(staff_router)
app.include_router(tickets_router)
app.include_router(messages_router)
app.include_router(knowledge_router)
app.include_router(agent_router)
app.include_router(integrations_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
