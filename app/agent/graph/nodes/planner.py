"""Nodo que envuelve al subagente `planner`. A diferencia de los otros dos,
su salida (`AgentDomain.output_model`) es la que eventualmente llega al
usuario -- pero sigue siendo el revisor, no este nodo, quien decide si es
suficiente."""

from __future__ import annotations

from langgraph.runtime import Runtime

from app.agent.contracts import AgentMode
from app.agent.graph.schemas import SubagentName, tier_for
from app.agent.graph.state import AgentState
from app.agent.llm.errors import TransientError, classify, error_kind
from app.agent.runtime import AgentRuntime
from app.agent.subagents import planner as subagent

NAME = SubagentName.PLANNER.value


async def planner_node(state: AgentState, runtime: Runtime[AgentRuntime]) -> dict:
    task = state["task"]
    request = state["request"]
    tier = tier_for(state.get("tier_overrides", {}), NAME)
    mode = AgentMode(request["mode"])

    models_used = {NAME: runtime.context.llm_router.model_name(NAME, tier)}
    try:
        result = await subagent.run(runtime=runtime.context, mode=mode, instruction=task["instruction"], tier=tier)
    except Exception as exc:
        classified = classify(exc)
        if isinstance(classified, TransientError):
            raise
        return {
            "results": {NAME: None},
            "errors": [{"subagent": NAME, "message": str(classified), "kind": error_kind(classified)}],
            "models_used": models_used,
        }

    return {"results": {NAME: result.output}, "models_used": models_used}
