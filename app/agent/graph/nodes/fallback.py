"""Último recurso: agotadas las iteraciones (o sin forma de desambiguar), se
le pide al dominio una respuesta determinista de resguardo. A diferencia de
`shortcut`, esto SIEMPRE devuelve algo -- `AgentDomain.fallback` no puede
devolver `None` (ver `domain.py`)."""

from __future__ import annotations

from langgraph.runtime import Runtime

from app.agent.contracts import AgentRequest
from app.agent.graph.state import AgentState
from app.agent.runtime import AgentRuntime

_DEFAULT_REASON = "Se alcanzó el límite de intentos sin una respuesta completamente validada."


async def fallback_node(state: AgentState, runtime: Runtime[AgentRuntime]) -> dict:
    request = AgentRequest.model_validate(state["request"])
    output = runtime.context.domain.fallback(request)

    review = state.get("review") or {}
    reason = review.get("summary") or _DEFAULT_REASON
    warnings = [*state.get("warnings", []), reason]

    return {
        "domain_output": output,
        "status": "partial",
        "produced_by": "fallback",
        "message_out": f"No pude completarlo del todo con el modelo; usé una respuesta de resguardo. {reason}",
        "warnings": warnings,
    }
