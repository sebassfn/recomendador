"""Estado de misión en memoria del proceso (doc 03 §10.4).

TTL de 1 hora, indexado por `mission_id`. Ni disco ni cuentas: un carrito vive
lo que vive el proceso (CLAUDE.md prohíbe "carrito persistente"). La única
cookie es `uid` (`USER_COOKIE`), un id anónimo que le permite al agente
encontrar las conversaciones pasadas de este navegador; no guarda carrito ni
canasta. En Cloud Run esto exige `--min-instances=1 --max-instances=1`
durante la demo: con dos instancias, un request cae en la que no tiene la
sesión y el carrito "desaparece".

Recuperación
------------
Si la sesión no existe (expiró o la instancia se recicló) y el id empieza con el
nombre de una misión semilla, la ruta la re-interpreta desde la caché de
semillas — cero LLM — y avisa que el carrito se reinició. Por eso el id de una
semilla lleva su nombre como prefijo.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.domain.schema import Basket, MissionPlan
from app.mission_agent.seeds import SEED_MISSION_FILES
from app.presentation.cart import CartState
from app.presentation.viewmodel import TurnVM

if TYPE_CHECKING:
    from fastapi import Request

TTL_SECONDS = 3600
USER_COOKIE = "uid"
USER_COOKIE_MAX_AGE = 60 * 60 * 24 * 365  # un año -- es sólo un id anónimo, no una cuenta

# stem del JSON -> texto exacto que pega en la caché de semillas.
SEED_TEXT_BY_STEM: dict[str, str] = {
    filename.removesuffix(".json"): text for text, filename in SEED_MISSION_FILES.items()
}


@dataclass
class MissionSession:
    mission_id: str
    mission: MissionPlan
    basket: Basket
    cart: CartState
    agent_session_id: str
    """`session_id` del agente (app/agent/) -- el `thread_id` de LangGraph que
    checkpointea esta conversación. Vive independiente de `mission_id` (que es
    sólo la URL de esta pestaña): dos pestañas del mismo usuario pueden tener
    `mission_id` distintos pero comparten memoria de agente si comparten
    `agent_session_id`."""
    user_id: str
    """Id anónimo persistido en la cookie `uid` -- lo que le permite al
    agente (`list_sessions`) encontrar las conversaciones pasadas de ESTE
    navegador."""
    pending_clarification: dict | None = None
    """`ClarificationRequest` (serializado) cuando el agente pidió aclarar
    algo y todavía no hay respuesta. `None` en cualquier otro momento."""
    conversation: list[TurnVM] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)


_SESSIONS: dict[str, MissionSession] = {}
_LOCK = threading.Lock()


def new_mission_id(mission: MissionPlan) -> str:
    """`{stem}-{hex6}` si es una misión semilla, `{hex12}` si no.

    El sufijo aleatorio también en las semillas es deliberado: sin él, el
    jurado desde su celular y el presentador en la laptop abrirían la misma
    semilla y compartirían —y se pisarían— el mismo carrito.
    """
    if mission.interpreted_by == "cached_seed":
        for stem, text in SEED_TEXT_BY_STEM.items():
            if " ".join(mission.raw_input.split()) == text:
                return f"{stem}-{uuid.uuid4().hex[:6]}"
    return uuid.uuid4().hex[:12]


def seed_text_for(mission_id: str) -> str | None:
    """Texto semilla recuperable desde un id, o None si el id es opaco."""
    for stem, text in SEED_TEXT_BY_STEM.items():
        if mission_id.startswith(f"{stem}-"):
            return text
    return None


def purge_expired(now: float | None = None) -> int:
    now = time.time() if now is None else now
    with _LOCK:
        dead = [k for k, s in _SESSIONS.items() if now - s.last_seen > TTL_SECONDS]
        for k in dead:
            del _SESSIONS[k]
    return len(dead)


def put(session: MissionSession) -> None:
    purge_expired()
    with _LOCK:
        _SESSIONS[session.mission_id] = session


def get(mission_id: str, now: float | None = None) -> MissionSession | None:
    now = time.time() if now is None else now
    purge_expired(now)
    with _LOCK:
        session = _SESSIONS.get(mission_id)
        if session is not None:
            session.last_seen = now
        return session


def clear() -> None:
    """Sólo para tests."""
    with _LOCK:
        _SESSIONS.clear()


def resolve_user_id(request: "Request") -> str:
    """El id anónimo de la cookie `uid`, o uno nuevo si no existe todavía
    (`app.web.routes` lo escribe en la respuesta). No es una cuenta -- es lo
    mínimo para que `AgentService.list_sessions` sepa qué conversaciones son
    del mismo navegador (CLAUDE.md sigue prohibiendo cuentas/login)."""
    existing = request.cookies.get(USER_COOKIE)
    return existing if existing else uuid.uuid4().hex
