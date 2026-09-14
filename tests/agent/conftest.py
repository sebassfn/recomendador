from __future__ import annotations

from app.agent.config import AgentSettings
from app.agent.graph.builder import build_graph
from app.agent.persistence.backends.memory import InMemoryCheckpointStore
from app.agent.persistence.checkpointer import StoreCheckpointSaver
from app.agent.runtime import AgentRuntime
from app.agent.service import AgentService
from tests.agent.fakes import FakeDomain, FakeLLMRouter


def make_test_service(*, domain=None, **settings_overrides) -> tuple[AgentService, FakeLLMRouter, AgentRuntime]:
    settings = AgentSettings(
        max_iterations=settings_overrides.pop("max_iterations", 3),
        max_subagent_attempts=settings_overrides.pop("max_subagent_attempts", 2),
        max_clarifications=settings_overrides.pop("max_clarifications", 2),
        retry_max_attempts=settings_overrides.pop("retry_max_attempts", 3),
        retry_initial_interval=settings_overrides.pop("retry_initial_interval", 0.001),
        retry_max_interval=settings_overrides.pop("retry_max_interval", 0.01),
        recursion_limit=settings_overrides.pop("recursion_limit", 60),
        **settings_overrides,
    )
    router = FakeLLMRouter()
    runtime = AgentRuntime(
        store=InMemoryCheckpointStore(),
        checkpointer=None,  # se completa abajo, necesita el store ya creado
        llm_router=router,
        domain=domain or FakeDomain(),
        settings=settings,
    )
    runtime.checkpointer = StoreCheckpointSaver(runtime.store)
    graph = build_graph(runtime)
    service = AgentService(runtime=runtime, graph=graph)
    return service, router, runtime
