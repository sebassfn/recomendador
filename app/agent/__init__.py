"""Módulo de agente de IA (LangGraph) reutilizable entre proyectos.

Ver `README.md` en este mismo directorio para la explicación completa. Esta
es la única superficie pública: nada fuera de este archivo, `contracts.py` y
`domain.py` debería importarse desde afuera del paquete.
"""

from __future__ import annotations

from app.agent.config import AgentSettings
from app.agent.contracts import (
    AgentMode,
    AgentRequest,
    AgentResponse,
    AgentStatus,
    AgentTrace,
    ClarificationAnswer,
    ClarificationRequest,
    ClarificationSuggestion,
    SessionSummary,
)
from app.agent.domain import AgentDomain
from app.agent.service import AgentService

__all__ = [
    "AgentDomain",
    "AgentMode",
    "AgentRequest",
    "AgentResponse",
    "AgentService",
    "AgentSettings",
    "AgentStatus",
    "AgentTrace",
    "ClarificationAnswer",
    "ClarificationRequest",
    "ClarificationSuggestion",
    "SessionSummary",
]
