"""Cuando el revisor marca `escalate=true` sobre un subagente, el orquestador
debe reintentarlo en el ciclo SIGUIENTE con el modelo de razonamiento -- y
volver a `STANDARD` en el turno de después (el escalamiento es de UN turno,
no permanente)."""

from __future__ import annotations

import pytest

from app.agent.contracts import AgentMode, AgentRequest, AgentStatus
from app.agent.graph.schemas import ReviewIssue, ReviewVerdict
from app.agent.llm.tiers import ModelTier
from app.agent.subagents.planner import ROLE as PLANNER_ROLE
from tests.agent.conftest import make_test_service
from tests.agent.fakes import FakeOutput, orchestrator_decision


@pytest.mark.asyncio
async def test_reviewer_escalation_upgrades_planner_tier_for_one_retry() -> None:
    service, router, _ = make_test_service()

    router.get("orchestrator").structured_queue = [
        orchestrator_decision("plan", tasks=[{"subagent": "planner", "instruction": "plan v1"}]),
        orchestrator_decision("plan", tasks=[{"subagent": "planner", "instruction": "plan v2, corregido"}]),
    ]
    router.get("planner").structured_queue = [
        FakeOutput(text="borrador con error", confirmed=False),
        FakeOutput(text="plan corregido", confirmed=True),
    ]
    router.get("reviewer").structured_queue = [
        ReviewVerdict(
            ready_to_finish=False,
            ambiguous=False,
            issues=[ReviewIssue(subagent="planner", ok=False, feedback="faltó confirmar", escalate=True)],
            summary="hay que corregir",
        ),
        ReviewVerdict(ready_to_finish=True, ambiguous=False, issues=[], summary="ahora sí"),
    ]
    router.requested_tiers.clear()  # las líneas de arriba ya llamaron a .get() para armar los fakes

    response = await service.run(AgentRequest(user_id="u1", message="pedido", mode=AgentMode.START))

    assert response.status is AgentStatus.ANSWERED
    assert response.output == {"text": "plan corregido", "confirmed": True}

    tiers_requested = [tier for role, tier in router.requested_tiers if role == PLANNER_ROLE]
    assert tiers_requested == [ModelTier.STANDARD, ModelTier.REASONING]
    assert response.trace.models_used[PLANNER_ROLE] == "fake-planner-reasoning"


@pytest.mark.asyncio
async def test_tier_escalation_does_not_carry_over_to_the_next_turn() -> None:
    service, router, _ = make_test_service()

    # Turno 1: escala planner a REASONING.
    router.get("orchestrator").structured_queue = [
        orchestrator_decision("plan", tasks=[{"subagent": "planner", "instruction": "v1"}]),
        orchestrator_decision("plan", tasks=[{"subagent": "planner", "instruction": "v2"}]),
        # Turno 2: un solo ciclo, no debería seguir en REASONING.
        orchestrator_decision("plan", tasks=[{"subagent": "planner", "instruction": "v3"}]),
    ]
    router.get("planner").structured_queue = [
        FakeOutput(text="v1", confirmed=False),
        FakeOutput(text="v2", confirmed=True),
        FakeOutput(text="v3", confirmed=True),
    ]
    router.get("reviewer").structured_queue = [
        ReviewVerdict(
            ready_to_finish=False,
            ambiguous=False,
            issues=[ReviewIssue(subagent="planner", ok=False, feedback="x", escalate=True)],
            summary="corregir",
        ),
        ReviewVerdict(ready_to_finish=True, ambiguous=False, issues=[], summary="ok turno 1"),
        ReviewVerdict(ready_to_finish=True, ambiguous=False, issues=[], summary="ok turno 2"),
    ]
    router.requested_tiers.clear()  # las líneas de arriba ya llamaron a .get() para armar los fakes

    session_id = None
    for message in ("primer pedido", "segundo pedido"):
        response = await service.run(
            AgentRequest(user_id="u1", session_id=session_id, message=message, mode=AgentMode.START)
        )
        session_id = response.session_id

    tiers_requested = [tier for role, tier in router.requested_tiers if role == PLANNER_ROLE]
    assert tiers_requested == [ModelTier.STANDARD, ModelTier.REASONING, ModelTier.STANDARD]
