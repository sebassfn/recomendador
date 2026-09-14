"""Atajo determinista del dominio (p. ej. caché de misiones semilla): cero
LLM, cero latencia. `AgentDomain.shortcut` decide si aplica; este nodo sólo
lo invoca y, si hay hit, deja el turno listo para `finalize` sin pasar por el
orquestador. Un miss simplemente no escribe `domain_output` y el grafo sigue
de largo -- `routing.route_after_shortcut` lee eso, no un valor de retorno
especial.
"""

from __future__ import annotations

from langgraph.runtime import Runtime

from app.agent.contracts import AgentRequest
from app.agent.graph.state import AgentState
from app.agent.runtime import AgentRuntime


async def shortcut(state: AgentState, runtime: Runtime[AgentRuntime]) -> dict:
    request = AgentRequest.model_validate(state["request"])
    output = runtime.context.domain.shortcut(request)
    if output is None:
        return {}
    return {
        "domain_output": output,
        "status": "answered",
        "produced_by": "shortcut",
        "message_out": "Resuelto desde una respuesta ya conocida, sin necesidad de razonar de nuevo.",
    }
