"""Funciones puras de ruteo: leen `AgentState` (nunca lo escriben) y deciden
la próxima arista. Se registran en `graph/builder.py` con
`add_conditional_edges`.

Ninguna vuelve a interpretar una decisión del LLM -- eso ya lo hizo el nodo
correspondiente (`nodes/orchestrator.py` valida y filtra, `nodes/reviewer.py`
decide `ready_to_finish`/`ambiguous`). Estas funciones sólo traducen esa
decisión YA VALIDADA a nombres de nodo o a una lista de `Send` para el
despacho en paralelo.
"""

from __future__ import annotations

import json

from langgraph.types import Send

from app.agent.config import AgentSettings
from app.agent.graph.schemas import SubagentName
from app.agent.graph.state import AgentState

_NODE_BY_SUBAGENT = {
    SubagentName.HISTORY_RESEARCHER.value: "history_researcher",
    SubagentName.DISAMBIGUATOR.value: "disambiguator",
    SubagentName.PLANNER.value: "planner",
}


def _task_with_context(task: dict, state: AgentState) -> dict:
    if task["subagent"] == SubagentName.HISTORY_RESEARCHER.value:
        return task
    # Estos roles necesitan el intercambio literal, incluso si la instrucción
    # del orquestador omitió una opción o una restricción ya confirmada.
    context = {
        "instruction": task["instruction"],
        "conversation": [
            {"role": message.type, "content": message.content}
            for message in state.get("messages", [])
        ],
        "previous_output": state["request"].get("previous_output"),
    }
    return {**task, "instruction": json.dumps(context, ensure_ascii=False)}


def route_after_shortcut(state: AgentState) -> str:
    return "finalize" if state.get("domain_output") is not None else "orchestrator"


def route_after_orchestrator(state: AgentState) -> str | list[Send]:
    decision = state["decision"]
    next_step = decision["next"]

    if next_step == "fallback":
        return "fallback"
    if next_step == "finish":
        return "finalize"
    if next_step in ("investigate", "plan"):
        sends = [
            Send(
                _NODE_BY_SUBAGENT[task["subagent"]],
                {
                    "task": _task_with_context(task, state),
                    "request": state["request"],
                    "tier_overrides": state.get("tier_overrides", {}),
                },
            )
            for task in decision["tasks"]
        ]
        # Guardia de cinturón: si por alguna razón no quedó ningún Send
        # (no debería pasar -- `orchestrator` ya fuerza "fallback" en ese
        # caso), no te quedes sin arista.
        return sends or "fallback"
    return "fallback"


def make_route_after_reviewer(settings: AgentSettings):
    """Factory: cierra sobre `settings` para no tener que inyectar `Runtime`
    en una función de ruteo (que LangGraph no invoca con la misma firma que
    un nodo)."""

    def route_after_reviewer(state: AgentState) -> str:
        review = state["review"]
        if review.get("fatal"):
            return "fallback"
        if review["ready_to_finish"]:
            return "finalize"
        if review["ambiguous"]:
            if state.get("clarifications_used", 0) >= settings.max_clarifications:
                return "fallback"
            return "clarify"
        if state.get("iteration", 0) >= settings.max_iterations:
            return "fallback"
        return "orchestrator"

    return route_after_reviewer
