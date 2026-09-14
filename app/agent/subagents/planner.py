"""Subagente planificador: el único que produce la salida final del dominio
(`AgentDomain.output_model`). No usa tools -- la instrucción del orquestador
ya trae todo el contexto resuelto (investigación de historial, aclaración del
usuario, plan previo si es una revisión)."""

from __future__ import annotations

from app.agent.contracts import AgentMode
from app.agent.llm.tiers import ModelTier
from app.agent.prompts import load_prompt
from app.agent.runtime import AgentRuntime
from app.agent.subagents.base import SubagentResult, run_subagent

ROLE = "planner"


def _system_prompt(runtime: AgentRuntime, mode: AgentMode) -> str:
    prompt_key = runtime.domain.prompt_key
    brief = load_prompt(f"domains/{prompt_key}/brief")
    template = "planner_revision" if mode is AgentMode.REVISE else "planner"
    return load_prompt(f"domains/{prompt_key}/{template}", brief=brief)


async def run(*, runtime: AgentRuntime, mode: AgentMode, instruction: str, tier: ModelTier) -> SubagentResult:
    llm = runtime.llm_router.get(ROLE, tier)
    return await run_subagent(
        llm=llm,
        system_prompt=_system_prompt(runtime, mode),
        instruction=instruction,
        output_model=runtime.domain.output_model,
        retry_after_cap=runtime.settings.retry_after_cap,
    )
