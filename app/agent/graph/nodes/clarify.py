"""Human-in-the-loop: pausa el grafo y le pregunta al humano.

`interrupt()` corta la ejecución acá mismo -- LangGraph guarda el valor que
se le pasa en el checkpoint (canal especial `__interrupt__`) y devuelve el
control a quien llamó `ainvoke` sin terminar el turno. `AgentService` lo
detecta, lo traduce a `ClarificationRequest` y se lo entrega al anfitrión.
Cuando alguien responde, el anfitrión llama de nuevo con
`Command(resume=ClarificationAnswer(...))` sobre el MISMO `thread_id`, y la
ejecución continúa EXACTAMENTE acá, con `interrupt()` devolviendo esa
respuesta -- nunca se re-ejecuta `intake`. La respuesta invalida el diagnóstico
anterior, conservando la conversación y la investigación del historial.

Antes de este punto no hay efectos secundarios que valga la pena deshacer
(ningún nodo anterior escribe fuera del propio estado del grafo), así que
reanudar simplemente sigue de largo con la respuesta del humano como si fuera
la instrucción del orquestador para el próximo ciclo.
"""

from __future__ import annotations

import re

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import interrupt

from app.agent.graph.schemas import SubagentName
from app.agent.graph.state import AgentState, RESET_ERRORS


def _resolve_answer(answer: dict, suggestions: list[dict]) -> str:
    suggestion_id = (answer or {}).get("suggestion_id")
    if suggestion_id:
        for suggestion in suggestions:
            if suggestion["id"] == suggestion_id:
                return suggestion["rewritten_request"]
    text = (answer or {}).get("free_text") or ""
    # Sólo selecciones completas: "3 meses" o "la 3, pero sin perfume"
    # deben conservarse como texto libre, sin perder datos o restricciones.
    match = re.fullmatch(
        r"\s*(?:(?:la\s+)?opci[oó]n\s+|(?:del\s+)?tipo\s+|la\s+)?([0-9]{1,3})[.)]?\s*",
        text,
        re.IGNORECASE,
    )
    if match and 1 <= int(match[1]) <= len(suggestions):
        return suggestions[int(match[1]) - 1]["rewritten_request"]
    return text


async def clarify(state: AgentState) -> dict:
    review = state.get("review") or {}
    disambiguation = (state.get("results") or {}).get(SubagentName.DISAMBIGUATOR.value) or {}
    suggestions = [
        {"id": f"s{i}", "label": s["label"], "rewritten_request": s["rewritten_request"]}
        for i, s in enumerate(disambiguation.get("suggestions", []))
    ]
    clarification_request = {
        "question": (
            review.get("clarification_question")
            or disambiguation.get("question")
            or review.get("summary")
            or "¿Qué necesitás resolver con este pedido?"
        ),
        "suggestions": suggestions,
        "allow_free_text": True,
    }

    answer = interrupt(clarification_request)

    resolved_text = _resolve_answer(answer, suggestions)
    question = clarification_request["question"]
    prompt_text = "\n".join([
        question,
        *(f"{i}. {s['label']} — {s['rewritten_request']}" for i, s in enumerate(suggestions, start=1)),
    ])
    raw_text = (answer or {}).get("free_text") or resolved_text
    response_text = raw_text
    if raw_text != resolved_text:
        response_text += f"\nOpción seleccionada: {resolved_text}"
    return {
        # El nodo se reejecuta al hacer resume. Escribimos ambos mensajes
        # juntos DESPUÉS del interrupt: así no se duplican por el replay.
        "messages": [AIMessage(prompt_text), HumanMessage(response_text)],
        "request": {
            **state["request"],
            "message": f"{state['request']['message']}\nPregunta: {question}\nAclaración: {response_text}",
        },
        # La respuesta humana invalida el diagnóstico previo, no el historial
        # investigado. Cada respuesta tiene presupuesto de trabajo propio;
        # max_clarifications sigue acotando la interacción completa.
        "review": None,
        "results": {SubagentName.DISAMBIGUATOR.value: None, SubagentName.PLANNER.value: None},
        "errors": RESET_ERRORS,
        "iteration": 0,
        "attempts": {},
        "tier_overrides": {},
        "decision": None,
        "last_dispatch": [],
        "clarifications_used": state.get("clarifications_used", 0) + 1,
    }
