"""Subagente investigador de historial: usa las tools de `tools/session_history.py`
para averiguar si hay algo relevante en sesiones anteriores del usuario."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.agent.llm.tiers import ModelTier
from app.agent.prompts import load_prompt
from app.agent.runtime import AgentRuntime
from app.agent.subagents.base import SubagentResult, run_subagent
from app.agent.tools.session_history import build_history_tools

ROLE = "history_researcher"


class HistoryFinding(BaseModel):
    has_relevant_history: bool
    summary: str = Field(
        default="", description="1-3 frases con lo relevante encontrado, vacío si no hay nada."
    )
    related_session_ids: list[str] = Field(default_factory=list)


async def run(
    *, runtime: AgentRuntime, user_id: str, session_id: str, instruction: str, tier: ModelTier
) -> SubagentResult:
    llm = runtime.llm_router.get(ROLE, tier)
    tools = build_history_tools(runtime, user_id=user_id, current_session_id=session_id)
    return await run_subagent(
        llm=llm,
        system_prompt=load_prompt(ROLE),
        instruction=instruction,
        output_model=HistoryFinding,
        tools=tools,
        max_tool_calls=4,
        retry_after_cap=runtime.settings.retry_after_cap,
    )
