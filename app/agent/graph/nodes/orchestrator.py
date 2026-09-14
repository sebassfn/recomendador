"""El orquestador: decide qué pasa en este ciclo.

El LLM PROPONE una `OrchestratorDecision` (a qué subagentes despachar, o si ya
se puede terminar); este nodo la VALIDA en Python antes de guardarla:

- filtra cualquier tarea que pida un subagente que ya agotó
  `AGENT_MAX_SUBAGENT_ATTEMPTS` en este turno,
- fuerza `next="fallback"` si esta iteración supera `AGENT_MAX_ITERATIONS`,
  o si después de filtrar no queda ninguna tarea válida para investigar/planificar.

`graph/routing.py` sólo lee el resultado ya validado — nunca vuelve a
interpretar la decisión cruda del LLM. Es la misma idea que el resto del
proyecto anfitrión (CLAUDE.md regla 6): el LLM propone, Python decide.

El escalamiento de modelo (`tier_overrides`) para el PRÓXIMO intento de un
subagente lo escribe acá, a partir de los `issues` del revisor del ciclo
anterior (`escalate=true`) -- nunca lo decide el propio LLM del orquestador.
"""

from __future__ import annotations

import json

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.runtime import Runtime

from app.agent.graph.schemas import OrchestratorDecision, tier_for
from app.agent.graph.state import AgentState
from app.agent.llm.errors import respect_retry_after
from app.agent.llm.tiers import ModelTier
from app.agent.prompts import load_prompt
from app.agent.runtime import AgentRuntime

ROLE = "orchestrator"


def _review_context(state: AgentState) -> str | None:
    review = state.get("review")
    if not review:
        return None
    lines = [f"Resultado del ciclo anterior: {review.get('summary', '')}".strip()]
    for issue in review.get("issues", []):
        if not issue.get("ok", True):
            lines.append(f"- {issue['subagent']} tuvo un problema: {issue.get('feedback', '')}")
    return "\n".join(lines)


def _next_tier_overrides(state: AgentState) -> dict[str, str]:
    """Aplica los `escalate=true` del revisor anterior al PRÓXIMO intento.
    No acumula entre turnos -- `fresh_turn_fields` ya vació esto en `intake`."""
    review = state.get("review")
    overrides = dict(state.get("tier_overrides", {}))
    if review:
        for issue in review.get("issues", []):
            if issue.get("escalate"):
                overrides[issue["subagent"]] = ModelTier.REASONING.value
    return overrides


async def orchestrator(state: AgentState, runtime: Runtime[AgentRuntime]) -> dict:
    settings = runtime.context.settings
    tier_overrides = _next_tier_overrides(state)
    tier = tier_for(tier_overrides, ROLE)
    llm = runtime.context.llm_router.get(ROLE, tier)
    # method="function_calling" explícito -- ver comentario en
    # app/agent/subagents/base.py sobre el default "json_schema" de
    # ChatOpenAI (proveedor openrouter) rompiendo con Claude detrás.
    structured_llm = llm.with_structured_output(OrchestratorDecision, method="function_calling")

    brief = load_prompt(f"domains/{runtime.context.domain.prompt_key}/brief")
    messages = [SystemMessage(load_prompt(ROLE) + "\n\n" + brief), *state["messages"]]
    context = {
        "results": {k: v for k, v in state.get("results", {}).items() if v is not None},
        "previous_output": state["request"].get("previous_output"),
    }
    if context["results"] or context["previous_output"]:
        messages.append(HumanMessage("Contexto disponible:\n" + json.dumps(context, ensure_ascii=False)))
    review_context = _review_context(state)
    if review_context:
        messages.append(HumanMessage(review_context))

    try:
        raw_decision = await structured_llm.ainvoke(messages)
    except Exception as exc:
        await respect_retry_after(exc, cap=settings.retry_after_cap)
        raise

    iteration = state.get("iteration", 0) + 1
    attempts = dict(state.get("attempts", {}))

    valid_tasks = []
    for task in raw_decision.tasks:
        name = task.subagent.value
        if attempts.get(name, 0) >= settings.max_subagent_attempts:
            continue
        attempts[name] = attempts.get(name, 0) + 1
        valid_tasks.append({"subagent": name, "instruction": task.instruction})

    next_step = raw_decision.next
    if iteration > settings.max_iterations:
        next_step = "fallback"
    elif next_step in ("investigate", "plan") and not valid_tasks:
        # El LLM quería seguir trabajando pero cada subagente que pidió ya
        # agotó sus intentos -- seguir insistiendo sería el mismo loop.
        next_step = "fallback"

    models_used = {**state.get("models_used", {}), ROLE: runtime.context.llm_router.model_name(ROLE, tier)}

    return {
        "iteration": iteration,
        "attempts": attempts,
        "tier_overrides": tier_overrides,
        "decision": {"next": next_step, "tasks": valid_tasks, "rationale": raw_decision.rationale},
        "last_dispatch": [t["subagent"] for t in valid_tasks] if next_step in ("investigate", "plan") else [],
        "models_used": models_used,
    }
