"""Nodo que envuelve al subagente `disambiguator`. Ver el docstring de
`nodes/history_researcher.py` sobre qué se reintenta y qué se anota como error."""

from __future__ import annotations

from langgraph.runtime import Runtime

from app.agent.graph.schemas import SubagentName, tier_for
from app.agent.graph.state import AgentState
from app.agent.llm.errors import TransientError, classify, error_kind
from app.agent.runtime import AgentRuntime
from app.agent.subagents import disambiguator as subagent

NAME = SubagentName.DISAMBIGUATOR.value


async def disambiguator_node(state: AgentState, runtime: Runtime[AgentRuntime]) -> dict:
    task = state["task"]
    tier = tier_for(state.get("tier_overrides", {}), NAME)

    models_used = {NAME: runtime.context.llm_router.model_name(NAME, tier)}
    try:
        result = await subagent.run(runtime=runtime.context, instruction=task["instruction"], tier=tier)
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
