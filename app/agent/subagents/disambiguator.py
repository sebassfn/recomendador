"""Subagente desambiguador: evalúa si el pedido alcanza para actuar o si hace
falta preguntarle al usuario. No usa tools -- sólo lee la instrucción que le
da el orquestador (que ya incluye el pedido y cualquier contexto relevante)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.agent.llm.tiers import ModelTier
from app.agent.prompts import load_prompt
from app.agent.runtime import AgentRuntime
from app.agent.subagents.base import SubagentResult, run_subagent

ROLE = "disambiguator"


class SuggestionDraft(BaseModel):
    """Lo que el LLM puede razonablemente inventar. El `id` estable que ve el
    anfitrión (`ClarificationSuggestion.id`) lo asigna `nodes/reviewer.py` en
    Python -- pedirle a un LLM que invente un identificador único es pedirle
    que falle de una forma tonta y evitable."""

    label: str
    rewritten_request: str


class DisambiguationResult(BaseModel):
    is_ambiguous: bool
    question: str = Field(
        default="",
        description="Pregunta breve sobre un dato imprescindible para actuar; vacía si se puede avanzar.",
    )
    suggestions: list[SuggestionDraft] = Field(default_factory=list)


async def run(*, runtime: AgentRuntime, instruction: str, tier: ModelTier) -> SubagentResult:
    llm = runtime.llm_router.get(ROLE, tier)
    return await run_subagent(
        llm=llm,
        system_prompt=load_prompt(ROLE) + "\n\n" + load_prompt(f"domains/{runtime.domain.prompt_key}/brief"),
        instruction=instruction,
        output_model=DisambiguationResult,
        retry_after_cap=runtime.settings.retry_after_cap,
    )
