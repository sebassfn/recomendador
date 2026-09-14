"""Punto de salida único del turno. Para cuando `shortcut`/`reviewer`/`fallback`
ya dejaron todo listo (el caso normal); es una red de seguridad barata para
el caso -- no debería pasar nunca -- de llegar acá sin que nada haya fijado
un `status`."""

from __future__ import annotations

from langchain_core.messages import AIMessage

from app.agent.graph.state import AgentState


async def finalize(state: AgentState) -> dict:
    if state.get("status") is not None:
        message = state.get("message_out")
        return {"messages": [AIMessage(message)]} if message else {}
    return {
        "status": "failed",
        "produced_by": "fallback",
        "message_out": "No se pudo completar el pedido por un error interno del agente.",
    }
