"""Primer nodo de cada turno: abre el turno.

`AgentService` ya dejó `request` (y, si vino, `snapshot`) en el estado antes
de que este nodo corra -- es la actualización de entrada de `ainvoke`. Acá se
hacen las dos cosas que sólo tienen sentido UNA vez por turno: registrar el
mensaje del usuario en el historial de la conversación y resetear todos los
contadores/resultados de turno (`fresh_turn_fields`), para que un turno nuevo
nunca vea basura de decisiones de un turno anterior.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from app.agent.graph.state import AgentState, fresh_turn_fields


async def intake(state: AgentState) -> dict:
    request = state["request"]
    return {
        "messages": [HumanMessage(request["message"])],
        **fresh_turn_fields(request),
    }
