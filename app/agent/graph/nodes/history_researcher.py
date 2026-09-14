"""Nodo que envuelve al subagente `history_researcher` (`subagents/history_researcher.py`).

Errores TRANSITORIOS (429/5xx/timeout) se dejan propagar sin capturar: el
`RetryPolicy` que `graph/builder.py` le pone a este nodo los reintenta solo.
Sólo se capturan errores que NO tiene sentido reintentar tal cual
(`BadRequestError`/`OutputError`/`FatalError`) -- ésos se anotan en `errors`
para que el revisor decida cómo seguir, en vez de tumbar todo el turno.
"""

from __future__ import annotations

from langgraph.runtime import Runtime

from app.agent.graph.schemas import SubagentName, tier_for
from app.agent.graph.state import AgentState
from app.agent.llm.errors import TransientError, classify, error_kind
from app.agent.runtime import AgentRuntime
from app.agent.subagents import history_researcher as subagent

NAME = SubagentName.HISTORY_RESEARCHER.value


async def history_researcher_node(state: AgentState, runtime: Runtime[AgentRuntime]) -> dict:
    task = state["task"]
    request = state["request"]
    tier = tier_for(state.get("tier_overrides", {}), NAME)

    models_used = {NAME: runtime.context.llm_router.model_name(NAME, tier)}
    try:
        result = await subagent.run(
            runtime=runtime.context,
            user_id=request["user_id"],
            session_id=request["session_id"],
            instruction=task["instruction"],
            tier=tier,
        )
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
