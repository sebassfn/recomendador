"""El revisor: la única fuente de verdad sobre si el ciclo actual alcanza
para terminar. Corre después de que TODO lo despachado en este ciclo
(`state["last_dispatch"]`) terminó -- `graph/builder.py` conecta los tres
subagentes acá como un fan-in.

Dos capas, en este orden:

1. **Determinista, en Python**: si `planner` corrió, su salida se valida
   contra `AgentDomain.output_model` de verdad (no se le pregunta al LLM si
   "parece válida"). Un fallo de schema SIEMPRE gana sobre lo que diga el
   LLM revisor -- nunca se termina el turno con una salida que no valida.
2. **Holística, con LLM**: para todo lo demás (¿la investigación fue útil?,
   ¿el pedido sigue siendo ambiguo?, ¿hace falta escalar un subagente a un
   modelo con más razonamiento?) se le pide un veredicto al modelo, con sólo
   los resultados de ESTE ciclo y la conversación -- nunca el estado
   completo del grafo.
"""

from __future__ import annotations

import json

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.runtime import Runtime
from pydantic import ValidationError

from app.agent.graph.schemas import ReviewVerdict, SubagentName, tier_for
from app.agent.graph.state import AgentState
from app.agent.llm.errors import respect_retry_after
from app.agent.prompts import load_prompt
from app.agent.runtime import AgentRuntime

ROLE = "reviewer"


def _fatal_error(state: AgentState) -> dict | None:
    """Un error `FatalError` (401/403, credenciales) de CUALQUIER subagente
    despachado este ciclo corta directo al fallback -- reintentar o
    reformular la instrucción no cambia nada si las credenciales están mal."""
    last_dispatch = state.get("last_dispatch", [])
    for err in state.get("errors", []):
        if err.get("subagent") in last_dispatch and err.get("kind") == "fatal":
            return err
    return None


def _planner_schema_issue(runtime: Runtime[AgentRuntime], state: AgentState) -> dict | None:
    last_dispatch = state.get("last_dispatch", [])
    if SubagentName.PLANNER.value not in last_dispatch:
        return None

    raw = state.get("results", {}).get(SubagentName.PLANNER.value)
    if raw is None:
        attempts = state.get("attempts", {}).get(SubagentName.PLANNER.value, 0)
        return {
            "subagent": SubagentName.PLANNER.value,
            "ok": False,
            "feedback": "El planificador no produjo salida (ver el error asociado).",
            "escalate": attempts >= 2,
        }
    try:
        runtime.context.domain.output_model.model_validate(raw)
    except ValidationError as exc:
        return {
            "subagent": SubagentName.PLANNER.value,
            "ok": False,
            "feedback": f"La salida no valida contra el esquema esperado: {exc}",
            "escalate": True,
        }
    return None


async def reviewer(state: AgentState, runtime: Runtime[AgentRuntime]) -> dict:
    fatal = _fatal_error(state)
    if fatal is not None:
        # Ni el LLM revisor necesita opinar acá: un 401/403 no se arregla
        # reformulando, así que ni vale la pena gastar la llamada.
        return {
            "review": {
                "ready_to_finish": False,
                "ambiguous": False,
                "fatal": True,
                "issues": [
                    {"subagent": fatal["subagent"], "ok": False, "feedback": fatal["message"], "escalate": False}
                ],
                "summary": fatal["message"],
            }
        }

    settings = runtime.context.settings
    last_dispatch = state.get("last_dispatch", [])
    results = state.get("results", {})
    errors = state.get("errors", [])

    schema_issue = _planner_schema_issue(runtime, state)

    tier = tier_for(state.get("tier_overrides", {}), ROLE)
    llm = runtime.context.llm_router.get(ROLE, tier)
    # method="function_calling" explícito -- ver comentario en
    # app/agent/subagents/base.py sobre el default "json_schema" de
    # ChatOpenAI (proveedor openrouter) rompiendo con Claude detrás.
    structured_llm = llm.with_structured_output(ReviewVerdict, method="function_calling")

    payload = {
        "dispatched_this_cycle": last_dispatch,
        "results": {k: results.get(k) for k in last_dispatch},
        "errors_this_cycle": [e for e in errors if e.get("subagent") in last_dispatch],
    }
    messages = [
        SystemMessage(load_prompt(ROLE) + "\n\n" + load_prompt(f"domains/{runtime.context.domain.prompt_key}/brief")),
        *state.get("messages", []),
        HumanMessage(json.dumps(payload, ensure_ascii=False, default=str)),
    ]
    try:
        verdict = await structured_llm.ainvoke(messages)
    except Exception as exc:
        await respect_retry_after(exc, cap=settings.retry_after_cap)
        raise

    issues = [issue.model_dump(mode="json") for issue in verdict.issues]
    ready_to_finish = verdict.ready_to_finish
    if schema_issue is not None:
        # Python tiene la última palabra: un fallo de schema real siempre
        # gana sobre lo que haya dicho el LLM revisor sobre `planner`.
        issues = [i for i in issues if i["subagent"] != SubagentName.PLANNER.value] + [schema_issue]
        ready_to_finish = False

    models_used = {**state.get("models_used", {}), ROLE: runtime.context.llm_router.model_name(ROLE, tier)}
    update: dict = {
        "review": {
            "ready_to_finish": ready_to_finish,
            "ambiguous": verdict.ambiguous,
            "issues": issues,
            "summary": verdict.summary,
            "clarification_question": verdict.clarification_question,
        },
        "models_used": models_used,
    }
    if ready_to_finish:
        update["domain_output"] = results.get(SubagentName.PLANNER.value)
        update["status"] = "answered"
        update["produced_by"] = "agent"
        update["message_out"] = verdict.summary or "Listo."
    return update
