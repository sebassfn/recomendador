"""Reintentos ante fallas de red (429 con `Retry-After`, luego éxito) y
re-planificación (no reintento ciego) ante un 400. Un 401 va directo al
fallback determinista del dominio."""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from app.agent.contracts import AgentMode, AgentRequest, AgentStatus
from app.agent.graph.schemas import ReviewVerdict
from tests.agent.conftest import make_test_service
from tests.agent.fakes import FakeOutput, orchestrator_decision


def _http_error(status: int, retry_after: str | None = None) -> Exception:
    headers = {"retry-after": retry_after} if retry_after else {}
    response = SimpleNamespace(status_code=status, headers=headers)
    exc = Exception(f"HTTP {status}")
    exc.status_code = status  # type: ignore[attr-defined]
    exc.response = response  # type: ignore[attr-defined]
    return exc


@pytest.mark.asyncio
async def test_429_with_retry_after_is_retried_and_succeeds() -> None:
    service, router, _ = make_test_service(retry_max_attempts=3)

    router.get("orchestrator").structured_queue = [
        orchestrator_decision("plan", tasks=[{"subagent": "planner", "instruction": "armá el plan"}])
    ]
    router.get("planner").structured_queue = [
        _http_error(429, retry_after="0.01"),
        FakeOutput(text="plan final", confirmed=True),
    ]
    router.get("reviewer").structured_queue = [ReviewVerdict(ready_to_finish=True, ambiguous=False, summary="ok")]
    router.requested_tiers.clear()

    started = time.monotonic()
    response = await service.run(AgentRequest(user_id="u1", message="pedido", mode=AgentMode.START))
    elapsed = time.monotonic() - started

    assert response.status is AgentStatus.ANSWERED
    assert response.output == {"text": "plan final", "confirmed": True}
    assert elapsed >= 0.01  # respetó el Retry-After antes de reintentar


@pytest.mark.asyncio
async def test_400_triggers_replanning_not_blind_retry() -> None:
    service, router, _ = make_test_service(max_iterations=3)

    router.get("orchestrator").structured_queue = [
        orchestrator_decision("plan", tasks=[{"subagent": "planner", "instruction": "instrucción v1 (mal formada)"}]),
        orchestrator_decision("plan", tasks=[{"subagent": "planner", "instruction": "instrucción v2 (corregida)"}]),
    ]
    router.get("planner").structured_queue = [
        _http_error(400),
        FakeOutput(text="plan corregido", confirmed=True),
    ]
    from app.agent.graph.schemas import ReviewIssue

    router.get("reviewer").structured_queue = [
        ReviewVerdict(
            ready_to_finish=False,
            ambiguous=False,
            issues=[ReviewIssue(subagent="planner", ok=False, feedback="la instrucción estaba mal formada")],
            summary="hay que reformular",
        ),
        ReviewVerdict(ready_to_finish=True, ambiguous=False, summary="ok, se recuperó"),
    ]
    router.requested_tiers.clear()

    response = await service.run(AgentRequest(user_id="u1", message="pedido", mode=AgentMode.START))

    assert response.status is AgentStatus.ANSWERED
    assert response.output == {"text": "plan corregido", "confirmed": True}
    # El planner sólo se llamó 2 veces -- el 400 NO se reintentó ciegamente
    # (si se hubiera reintentado igual, el queue se habría vaciado antes).
    assert router.get("planner").calls == ["planner", "planner"]


@pytest.mark.asyncio
async def test_401_goes_straight_to_fallback() -> None:
    service, router, _ = make_test_service(max_iterations=3)

    router.get("orchestrator").structured_queue = [
        orchestrator_decision("plan", tasks=[{"subagent": "planner", "instruction": "armá el plan"}])
    ]
    router.get("planner").structured_queue = [_http_error(401)]
    router.requested_tiers.clear()

    response = await service.run(AgentRequest(user_id="u1", message="pedido sin credenciales", mode=AgentMode.START))

    assert response.status is AgentStatus.PARTIAL
    assert response.produced_by == "fallback"
    assert response.output == {"text": "fallback:pedido sin credenciales", "confirmed": False}
