"""Punto de entrada ASGI. `uv run uvicorn app.main:app` (doc 07 §5.2)."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.agent import AgentService
from app.mission_agent.domain import RetailMissionDomain
from app.web.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Un solo `AgentService` por proceso: arma el pool de conexión del
    # backend de checkpoints (memoria o Firestore, según `AGENT_STORE_BACKEND`)
    # una vez y lo reutiliza en cada request -- ver app/agent/service.py.
    app.state.agent = await AgentService.create(RetailMissionDomain())
    try:
        yield
    finally:
        await app.state.agent.aclose()


app = FastAPI(title="Recomendador de misión de compra", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(router)
