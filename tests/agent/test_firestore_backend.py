"""Mismo contrato que `test_checkpointer.py`, pero contra Cloud Firestore de
verdad (vía el emulador). No corre en CI sin el emulador levantado -- ver
`app/agent/README.md` para el comando de `gcloud emulators firestore start`.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.firestore

if not os.environ.get("FIRESTORE_EMULATOR_HOST"):
    pytest.skip(
        "Requiere FIRESTORE_EMULATOR_HOST (gcloud emulators firestore start). Ver app/agent/README.md.",
        allow_module_level=True,
    )

from app.agent.config import AgentSettings  # noqa: E402
from app.agent.persistence.backends.firestore import FirestoreCheckpointStore  # noqa: E402
from app.agent.persistence.checkpointer import StoreCheckpointSaver  # noqa: E402


def _settings() -> AgentSettings:
    return AgentSettings(
        store_backend="firestore",
        firestore_project=os.environ.get("GOOGLE_CLOUD_PROJECT", "test-project"),
        firestore_collection_prefix="agent_test",
    )


@pytest.mark.asyncio
async def test_round_trip_against_the_emulator() -> None:
    settings = _settings()
    store = FirestoreCheckpointStore.from_settings(settings)
    saver = StoreCheckpointSaver(store)

    from langgraph.graph import END, START, StateGraph
    from typing import TypedDict

    class S(TypedDict, total=False):
        count: int

    def step(state: S) -> S:
        return {"count": state["count"] + 1}

    builder = StateGraph(S)
    builder.add_node("step", step)
    builder.add_edge(START, "step")
    builder.add_edge("step", END)
    graph = builder.compile(checkpointer=saver)

    config = {"configurable": {"thread_id": "fs-t1", "user_id": "fs-u1"}}
    result = await graph.ainvoke({"count": 0}, config)
    assert result["count"] == 1

    threads = await store.list_threads(user_id="fs-u1")
    assert any(t.thread_id == "fs-t1" for t in threads)

    await store.delete_thread(thread_id="fs-t1")
    await store.aclose()
