"""El orquestador puede despachar `history_researcher` y `disambiguator` EN
PARALELO (`Send`), y sus resultados se fusionan antes de que el revisor los
vea -- el mecanismo entero (`graph/state.py::merge_results`, el fan-in en
`graph/builder.py`) se prueba de punta a punta acá."""

from __future__ import annotations

import pytest

from app.agent.contracts import AgentMode, AgentRequest, AgentStatus
from app.agent.graph.schemas import ReviewVerdict
from app.agent.subagents.disambiguator import DisambiguationResult
from app.agent.subagents.history_researcher import HistoryFinding
from tests.agent.conftest import make_test_service
from tests.agent.fakes import FakeOutput, orchestrator_decision


@pytest.mark.asyncio
async def test_investigate_then_plan_runs_both_subagents_in_parallel() -> None:
    service, router, _ = make_test_service()

    router.get("orchestrator").structured_queue = [
        orchestrator_decision(
            "investigate",
            tasks=[
                {"subagent": "history_researcher", "instruction": "¿algo relevante?"},
                {"subagent": "disambiguator", "instruction": "¿está claro el pedido?"},
            ],
        ),
        orchestrator_decision(
            "plan", tasks=[{"subagent": "planner", "instruction": "armá el plan final"}]
        ),
    ]
    router.get("history_researcher").structured_queue = [
        HistoryFinding(has_relevant_history=False, summary="", related_session_ids=[])
    ]
    router.get("disambiguator").structured_queue = [DisambiguationResult(is_ambiguous=False, suggestions=[])]
    router.get("reviewer").structured_queue = [
        ReviewVerdict(ready_to_finish=False, ambiguous=False, issues=[], summary="investigación completa"),
        ReviewVerdict(ready_to_finish=True, ambiguous=False, issues=[], summary="plan listo"),
    ]
    router.get("planner").structured_queue = [FakeOutput(text="plan final", confirmed=True)]

    response = await service.run(
        AgentRequest(user_id="u1", message="quiero organizar un viaje", mode=AgentMode.START)
    )

    assert response.status is AgentStatus.ANSWERED
    assert response.output == {"text": "plan final", "confirmed": True}
    assert response.produced_by == "agent"

    # Los dos subagentes despachados en paralelo corrieron de verdad, y el
    # revisor corrió una vez por cada ciclo (investigar, luego planificar).
    # history_researcher hace 1 turno de tool-calling (sin tools que llamar,
    # en este test) + 1 llamada de salida estructurada.
    assert router.get("history_researcher").calls == ["history_researcher:tool_turn", "history_researcher"]
    assert len(router.get("disambiguator").calls) == 1
    assert len(router.get("reviewer").calls) == 2
    assert response.trace.iterations == 2
