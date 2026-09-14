"""Human-in-the-loop: el revisor detecta ambigüedad, el grafo se pausa
(`interrupt()`), el anfitrión responde con `Command(resume=...)` y el turno
sigue EXACTAMENTE donde se cortó -- sin perder el trabajo ya hecho ni
reiniciar `intake`."""

from __future__ import annotations

import json

import pytest

from app.agent.contracts import AgentMode, AgentRequest, AgentStatus, ClarificationAnswer
from app.agent.graph.nodes.clarify import _resolve_answer
from app.agent.graph.schemas import ReviewVerdict
from app.agent.subagents.disambiguator import DisambiguationResult, SuggestionDraft
from tests.agent.conftest import make_test_service
from tests.agent.fakes import FakeOutput, orchestrator_decision


@pytest.mark.asyncio
async def test_ambiguous_request_pauses_and_resumes_with_a_suggestion() -> None:
    service, router, _ = make_test_service(max_clarifications=2)

    router.get("orchestrator").structured_queue = [
        orchestrator_decision(
            "investigate", tasks=[{"subagent": "disambiguator", "instruction": "¿está claro el pedido?"}]
        ),
        # Ciclo posterior a la respuesta humana:
        orchestrator_decision("plan", tasks=[{"subagent": "planner", "instruction": "algo para la playa"}]),
    ]
    router.get("disambiguator").structured_queue = [
        DisambiguationResult(
            is_ambiguous=True,
            suggestions=[
                SuggestionDraft(label="Para la playa", rewritten_request="algo para la playa"),
                SuggestionDraft(label="Para el auto", rewritten_request="algo para el auto"),
            ],
        )
    ]
    router.get("reviewer").structured_queue = [
        ReviewVerdict(ready_to_finish=False, ambiguous=True, summary="¿playa o auto?"),
        ReviewVerdict(ready_to_finish=True, ambiguous=False, summary="listo"),
    ]
    router.get("planner").structured_queue = [FakeOutput(text="plan playa", confirmed=True)]

    first = await service.run(AgentRequest(user_id="u1", message="quiero algo para el finde", mode=AgentMode.START))

    assert first.status is AgentStatus.NEEDS_CLARIFICATION
    assert first.clarification is not None
    assert [s.label for s in first.clarification.suggestions] == ["Para la playa", "Para el auto"]
    chosen_id = first.clarification.suggestions[0].id

    second = await service.run(
        AgentRequest(
            user_id="u1",
            session_id=first.session_id,
            message="",  # irrelevante en un resume: se usa `resume`, no `message`
            mode=AgentMode.START,
            resume=ClarificationAnswer(suggestion_id=chosen_id),
        )
    )

    assert second.status is AgentStatus.ANSWERED
    assert second.output == {"text": "plan playa", "confirmed": True}
    assert second.session_id == first.session_id


@pytest.mark.asyncio
async def test_clarifications_are_capped_then_falls_back() -> None:
    service, router, _ = make_test_service(max_clarifications=1, max_iterations=5)

    router.get("orchestrator").structured_queue = [
        orchestrator_decision(
            "investigate", tasks=[{"subagent": "disambiguator", "instruction": "¿está claro?"}]
        )
        for _ in range(3)
    ]
    router.get("disambiguator").structured_queue = [
        DisambiguationResult(is_ambiguous=True, suggestions=[]) for _ in range(3)
    ]
    router.get("reviewer").structured_queue = [
        ReviewVerdict(ready_to_finish=False, ambiguous=True, summary="sigue sin estar claro") for _ in range(3)
    ]

    response = await service.run(AgentRequest(user_id="u1", message="algo", mode=AgentMode.START))

    # Primer ciclo: se pide aclaración (clarifications_used pasa de 0 a 1,
    # que ya es el tope). El humano responde con texto libre; en el segundo
    # ciclo el revisor sigue sin conformarse pero el tope ya está alcanzado.
    assert response.status is AgentStatus.NEEDS_CLARIFICATION

    second = await service.run(
        AgentRequest(
            user_id="u1",
            session_id=response.session_id,
            message="",
            mode=AgentMode.START,
            resume=ClarificationAnswer(free_text="sigo sin saber qué quiero"),
        )
    )

    assert second.status is AgentStatus.PARTIAL
    assert second.produced_by == "fallback"


@pytest.mark.parametrize("answer", [
    ClarificationAnswer(suggestion_id="s2"),
    ClarificationAnswer(free_text="3"),
    ClarificationAnswer(free_text="del tipo 3"),
    ClarificationAnswer(free_text="la opción 3"),
])
async def test_selection_keeps_question_and_clears_obsolete_ambiguity(answer) -> None:
    service, router, _ = make_test_service()
    router.get("orchestrator").structured_queue = [
        orchestrator_decision("investigate", tasks=[{"subagent": "disambiguator", "instruction": "evaluar"}]),
        orchestrator_decision("plan", tasks=[{"subagent": "planner", "instruction": "resolver lo confirmado"}]),
    ]
    router.get("disambiguator").structured_queue = [DisambiguationResult(
        is_ambiguous=True,
        question="¿Qué tipo de aseo necesitás?",
        suggestions=[
            SuggestionDraft(label="Cambio de pañal", rewritten_request="pañales y toallitas para mi bebé"),
            SuggestionDraft(label="Accesorios", rewritten_request="esponja y toalla para mi bebé"),
            SuggestionDraft(label="Baño", rewritten_request="sólo jabón y champú para mi bebé"),
        ],
    )]
    router.get("reviewer").structured_queue = [
        ReviewVerdict(ready_to_finish=False, ambiguous=True, summary="DIAGNÓSTICO OBSOLETO"),
        ReviewVerdict(ready_to_finish=True, summary="Listo, jabón y champú."),
    ]
    router.get("planner").structured_queue = [FakeOutput(text="jabón y champú", confirmed=True)]

    first = await service.run(AgentRequest(user_id="u1", message="útiles de aseo para mi bebé"))
    assert first.clarification.question == "¿Qué tipo de aseo necesitás?"
    second = await service.run(AgentRequest(
        user_id="u1", session_id=first.session_id, message="", resume=answer,
    ))
    assert second.status is AgentStatus.ANSWERED
    messages = router.get("orchestrator").inputs[1]
    conversation = messages[1:]
    assert [m.type for m in conversation] == ["human", "ai", "human"]
    assert "3. Baño" in conversation[1].content
    assert "sólo jabón y champú" in conversation[2].content
    assert all("DIAGNÓSTICO OBSOLETO" not in m.content for m in messages)

    # El planner recibe la elección literal aunque su tarea no la mencione.
    planner_input = json.loads(router.get("planner").inputs[0][-1].content)
    assert "sólo jabón y champú" in planner_input["conversation"][-1]["content"]
    reviewer_input = router.get("reviewer").inputs[1]
    assert any(m.type == "human" and "sólo jabón y champú" in m.content for m in reviewer_input)
    state = await service._graph.aget_state({"configurable": {"thread_id": first.session_id}})
    assert "sólo jabón y champú" in state.values["request"]["message"]
    assert state.values["messages"][-1].type == "ai"


@pytest.mark.parametrize("text", ["3 meses", "pesa 3 kg", "la 3, pero sin perfume", "99", "0"])
def test_numeric_details_are_not_silently_replaced_by_a_selection(text) -> None:
    suggestions = [
        {"id": f"s{i}", "rewritten_request": f"selección {i}"} for i in range(4)
    ]
    assert _resolve_answer({"free_text": text}, suggestions) == text
    assert _resolve_answer({"free_text": "3"}, []) == "3"


async def test_new_information_gets_work_budget_and_preserves_both_answers() -> None:
    # Cada respuesta permite una nueva investigación aunque el intento
    # anterior hubiera consumido el presupuesto completo antes de pausar.
    service, router, _ = make_test_service(max_iterations=1, max_subagent_attempts=1)
    router.get("orchestrator").structured_queue = [
        orchestrator_decision("investigate", tasks=[{"subagent": "disambiguator", "instruction": "evaluar"}]),
        orchestrator_decision("investigate", tasks=[{"subagent": "disambiguator", "instruction": "evaluar dato restante"}]),
        orchestrator_decision("plan", tasks=[{"subagent": "planner", "instruction": "resolver"}]),
    ]
    router.get("disambiguator").structured_queue = [
        DisambiguationResult(is_ambiguous=True, question="¿Cuántos meses tiene?"),
        DisambiguationResult(is_ambiguous=True, question="¿Qué talla de pañal usa?"),
    ]
    router.get("reviewer").structured_queue = [
        ReviewVerdict(ready_to_finish=False, ambiguous=True, summary="Falta edad"),
        ReviewVerdict(ready_to_finish=False, ambiguous=True, summary="Falta talla",
                      clarification_question="Para los pañales, ¿qué talla usa actualmente?"),
        ReviewVerdict(ready_to_finish=True, summary="Plan listo"),
    ]
    router.get("planner").structured_queue = [FakeOutput(text="plan", confirmed=True)]
    first = await service.run(AgentRequest(user_id="u1", message="aseo para mi bebé"))
    second = await service.run(AgentRequest(
        user_id="u1", session_id=first.session_id, message="", resume=ClarificationAnswer(free_text="3 meses"),
    ))
    assert second.status is AgentStatus.NEEDS_CLARIFICATION
    assert second.clarification.question == "Para los pañales, ¿qué talla usa actualmente?"
    second_investigation = json.loads(router.get("disambiguator").inputs[1][-1].content)
    assert second_investigation["conversation"][-1]["content"] == "3 meses"
    third = await service.run(AgentRequest(
        user_id="u1", session_id=first.session_id, message="", resume=ClarificationAnswer(free_text="talla M"),
    ))
    assert third.status is AgentStatus.ANSWERED
    conversation = json.loads(router.get("planner").inputs[0][-1].content)["conversation"]
    assert [m["role"] for m in conversation] == ["human", "ai", "human", "ai", "human"]
    assert conversation[2]["content"] == "3 meses"
    assert conversation[4]["content"] == "talla M"

    # Un pedido posterior en la misma sesión conserva memoria, pero tiene
    # su propio límite de preguntas (el anterior consumió las dos).
    router.get("orchestrator").structured_queue = [
        orchestrator_decision("investigate", tasks=[{"subagent": "disambiguator", "instruction": "nuevo pedido"}]),
    ]
    router.get("disambiguator").structured_queue = [DisambiguationResult(is_ambiguous=True, question="¿Qué medida?")]
    router.get("reviewer").structured_queue = [ReviewVerdict(ready_to_finish=False, ambiguous=True)]
    fourth = await service.run(AgentRequest(user_id="u1", session_id=first.session_id, message="ahora necesito llantas"))
    assert fourth.status is AgentStatus.NEEDS_CLARIFICATION
