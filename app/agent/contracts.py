"""Contrato público del módulo de agente.

Éste es el ÚNICO lenguaje que el mundo exterior habla con `app.agent`. Nadie
fuera de este paquete debe importar nada de `app.agent.graph`, `.llm`,
`.persistence` ni `.subagents` — sólo lo que este archivo (y `domain.py`,
`service.py`) exponen. Eso es lo que permite copiar el directorio completo a
otro proyecto: quien lo integra escribe un `AgentDomain` y llama a
`AgentService`, nada más.

Todo acá es Pydantic simple. Ningún tipo de LangGraph (`Command`, `Send`,
`Checkpoint`...) ni de un SDK de base de datos cruza esta frontera.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Petición / respuesta
# ---------------------------------------------------------------------------


class AgentMode(str, Enum):
    """Si el agente arranca una necesidad nueva o revisa una ya resuelta."""

    START = "start"
    REVISE = "revise"


class ClarificationAnswer(BaseModel):
    """Cómo el humano resuelve una pregunta de desambiguación pendiente.

    `suggestion_id` referencia una de las `ClarificationSuggestion` que el
    agente propuso en el turno anterior; `free_text` es la aclaración cuando
    ninguna sugerencia calza (o cuando el agente no tenía ninguna que ofrecer).
    Exactamente uno de los dos debe venir con contenido — lo valida
    `AgentService`, no este modelo, para no acoplar el contrato al grafo.
    """

    suggestion_id: str | None = None
    free_text: str | None = None


class AgentRequest(BaseModel):
    """Lo único que la app anfitriona necesita construir para hablarle al agente."""

    user_id: str = Field(description="Quién pregunta. Sirve para listar sus sesiones pasadas.")
    session_id: str | None = Field(
        default=None,
        description="Identifica la conversación (= thread_id de LangGraph). "
        "None crea una sesión nueva; el `AgentResponse` devuelve el id asignado.",
    )
    message: str = Field(description="Texto libre del usuario para este turno.")
    mode: AgentMode = AgentMode.START
    previous_output: dict[str, Any] | None = Field(
        default=None,
        description="Última salida validada de esta sesión, tal cual la devolvió "
        "el agente. Sólo tiene sentido con mode=revise; el anfitrión no necesita "
        "reconstruirla, el agente ya la tiene checkpointeada, pero pasarla explícita "
        "evita depender de que el checkpoint todavía exista.",
    )
    snapshot: dict[str, Any] | None = Field(
        default=None,
        description="Resumen neutral del estado del anfitrión al cierre del turno "
        "anterior (p. ej. necesidades y nombres de producto, NUNCA precios ni "
        "monto — CLAUDE.md regla 6). Se guarda en el checkpoint de la sesión y es "
        "lo que el investigador de historial puede leer de sesiones pasadas.",
    )
    resume: ClarificationAnswer | None = Field(
        default=None,
        description="Presente sólo cuando este turno responde a un "
        "`AgentResponse.clarification` pendiente de un turno anterior.",
    )


class AgentStatus(str, Enum):
    ANSWERED = "answered"
    NEEDS_CLARIFICATION = "needs_clarification"
    PARTIAL = "partial"
    FAILED = "failed"


class ClarificationSuggestion(BaseModel):
    """Una interpretación concreta que el agente ya considera plausible.

    `rewritten_request` es el texto que el agente usaría si el humano confirma
    esta sugerencia — se lo puede re-inyectar tal cual como `message` del
    siguiente turno, o el anfitrión puede preferir mandar `ClarificationAnswer`
    y dejar que el agente lo resuelva internamente.
    """

    id: str
    label: str
    rewritten_request: str


class ClarificationRequest(BaseModel):
    """Lo que el agente necesita que un humano resuelva antes de seguir.

    Con `suggestions` no vacío, el anfitrión puede ofrecer chips ("¿Quisiste
    decir...?"); si además `allow_free_text` es True, puede ofrecer también un
    campo de texto libre. Sin sugerencias, sólo cabe pedir que aclare —
    `allow_free_text` es True siempre en ese caso.
    """

    question: str
    suggestions: list[ClarificationSuggestion] = Field(default_factory=list)
    allow_free_text: bool = True


class AgentTrace(BaseModel):
    """Metadatos de auditoría / diagnóstico. Nunca contenido de negocio."""

    iterations: int = 0
    models_used: dict[str, str] = Field(default_factory=dict)
    retries: int = 0
    warnings: list[str] = Field(default_factory=list)


ProducedBy = Literal["shortcut", "agent", "fallback"]


class AgentResponse(BaseModel):
    """Lo único que `AgentService.run`/`resume` devuelven.

    `output`, cuando está presente, valida contra `AgentDomain.output_model`
    del dominio configurado — el anfitrión lo revalida si quiere tipos fuertes;
    acá viaja como `dict` porque este contrato no puede depender del modelo
    Pydantic de un dominio concreto.
    """

    session_id: str
    status: AgentStatus
    output: dict[str, Any] | None = None
    message: str
    clarification: ClarificationRequest | None = None
    produced_by: ProducedBy
    trace: AgentTrace = Field(default_factory=AgentTrace)


class SessionSummary(BaseModel):
    """Una fila de `AgentService.list_sessions(user_id)`."""

    session_id: str
    title: str | None = None
    summary: str | None = None
    created_at: str
    updated_at: str
