"""Round-trip del checkpointer contra un grafo LangGraph real y mínimo.

Si esto falla, ningún nodo del agente real (que es mucho más complejo) va a
persistir memoria correctamente — es la red de seguridad de todo `persistence/`.
"""

from __future__ import annotations

from typing import TypedDict

import pytest
from langgraph.graph import END, START, StateGraph

from app.agent.persistence.backends.memory import InMemoryCheckpointStore
from app.agent.persistence.checkpointer import StoreCheckpointSaver


class _State(TypedDict):
    count: int
    log: list[str]


def _make_graph(saver: StoreCheckpointSaver):
    def step(state: _State) -> _State:
        return {"count": state["count"] + 1, "log": [*state["log"], f"step@{state['count']}"]}

    builder = StateGraph(_State)
    builder.add_node("step", step)
    builder.add_edge(START, "step")
    builder.add_edge("step", END)
    return builder.compile(checkpointer=saver)


@pytest.mark.asyncio
async def test_round_trip_persists_and_resumes_state() -> None:
    store = InMemoryCheckpointStore()
    saver = StoreCheckpointSaver(store)
    graph = _make_graph(saver)
    config = {"configurable": {"thread_id": "t1", "user_id": "u1"}}

    result = await graph.ainvoke({"count": 0, "log": []}, config)
    assert result["count"] == 1

    # Un grafo NUEVO sobre el MISMO store recupera el estado: la memoria vive
    # en el store, no en el proceso ni en el objeto `graph`.
    saver2 = StoreCheckpointSaver(store)
    graph2 = _make_graph(saver2)
    state = await graph2.aget_state(config)
    assert state.values["count"] == 1
    assert state.values["log"] == ["step@0"]

    result2 = await graph2.ainvoke(state.values, config)
    assert result2["count"] == 2
    assert result2["log"] == ["step@0", "step@1"]


@pytest.mark.asyncio
async def test_list_threads_filters_by_user() -> None:
    store = InMemoryCheckpointStore()
    saver = StoreCheckpointSaver(store)
    graph = _make_graph(saver)

    await graph.ainvoke({"count": 0, "log": []}, {"configurable": {"thread_id": "a", "user_id": "u1"}})
    await graph.ainvoke({"count": 0, "log": []}, {"configurable": {"thread_id": "b", "user_id": "u1"}})
    await graph.ainvoke({"count": 0, "log": []}, {"configurable": {"thread_id": "c", "user_id": "u2"}})

    u1_threads = await store.list_threads(user_id="u1")
    assert {t.thread_id for t in u1_threads} == {"a", "b"}
    u2_threads = await store.list_threads(user_id="u2")
    assert {t.thread_id for t in u2_threads} == {"c"}


@pytest.mark.asyncio
async def test_history_walk_across_multiple_checkpoints() -> None:
    store = InMemoryCheckpointStore()
    saver = StoreCheckpointSaver(store)
    graph = _make_graph(saver)
    config = {"configurable": {"thread_id": "t1", "user_id": "u1"}}

    state = {"count": 0, "log": []}
    for _ in range(3):
        state = await graph.ainvoke(state, config)

    history = [h async for h in graph.aget_state_history(config)]
    assert len(history) > 3  # cada ainvoke deja más de un checkpoint interno
    assert history[0].values["count"] == 3
    assert history[-1].values == {}  # el checkpoint raíz, antes del primer paso
