"""El grafo nunca queda dando vueltas para siempre: agotadas las iteraciones
(revisor que siempre encuentra un problema), corta al fallback determinista
del dominio en vez de dejar escapar un `GraphRecursionError`."""

from __future__ import annotations

import pytest

from app.agent.contracts import AgentMode, AgentRequest, AgentStatus
from app.agent.graph.schemas import ReviewIssue, ReviewVerdict
from tests.agent.conftest import make_test_service
from tests.agent.fakes import FakeOutput, orchestrator_decision


@pytest.mark.asyncio
async def test_reviewer_that_never_approves_ends_in_partial_via_fallback() -> None:
    service, router, _ = make_test_service(max_iterations=2, max_subagent_attempts=5)

    # El orquestador SIEMPRE quiere replanificar; el revisor SIEMPRE dice que
    # no alcanza -- sin la guarda de `AGENT_MAX_ITERATIONS` esto no terminaría.
    router.get("orchestrator").structured_queue = [
        orchestrator_decision("plan", tasks=[{"subagent": "planner", "instruction": f"intento {i}"}])
        for i in range(10)
    ]
    router.get("planner").structured_queue = [FakeOutput(text=f"borrador {i}", confirmed=False) for i in range(10)]
    router.get("reviewer").structured_queue = [
        ReviewVerdict(
            ready_to_finish=False,
            ambiguous=False,
            issues=[ReviewIssue(subagent="planner", ok=False, feedback="todavía no", escalate=False)],
            summary="no alcanza",
        )
        for _ in range(10)
    ]

    response = await service.run(AgentRequest(user_id="u1", message="pedido difícil", mode=AgentMode.START))

    assert response.status is AgentStatus.PARTIAL
    assert response.produced_by == "fallback"
    assert response.output == {"text": "fallback:pedido difícil", "confirmed": False}
    assert response.trace.iterations <= 3  # se cortó cerca de max_iterations=2, no siguió de largo


@pytest.mark.asyncio
async def test_subagent_attempts_are_capped_even_if_orchestrator_keeps_asking() -> None:
    """Guarda distinta de la de arriba: acá el orquestador podría, en teoría,
    seguir pidiendo el MISMO subagente turno tras turno dentro de un único
    ciclo de iteraciones -- `AGENT_MAX_SUBAGENT_ATTEMPTS` corta eso incluso
    con `AGENT_MAX_ITERATIONS` generoso."""
    service, router, _ = make_test_service(max_iterations=10, max_subagent_attempts=1)

    router.get("orchestrator").structured_queue = [
        orchestrator_decision("plan", tasks=[{"subagent": "planner", "instruction": f"intento {i}"}])
        for i in range(10)
    ]
    router.get("planner").structured_queue = [FakeOutput(text="borrador", confirmed=False) for _ in range(10)]
    router.get("reviewer").structured_queue = [
        ReviewVerdict(
            ready_to_finish=False,
            ambiguous=False,
            issues=[ReviewIssue(subagent="planner", ok=False, feedback="todavía no")],
            summary="no alcanza",
        )
        for _ in range(10)
    ]

    response = await service.run(AgentRequest(user_id="u1", message="pedido", mode=AgentMode.START))

    assert response.status is AgentStatus.PARTIAL
    assert response.produced_by == "fallback"
    # planner sólo corrió UNA vez (max_subagent_attempts=1): el segundo
    # intento del orquestador se filtró y forzó el fallback de inmediato.
    assert len(router.get("planner").calls) == 1
