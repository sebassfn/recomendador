"""`AGENT_STORE_BACKEND` -> instancia de `CheckpointStore`.

Mismo patrón que `app.llm.factory` en el proyecto anfitrión: un nombre de
config elige un backend concreto, e importa su SDK de forma perezosa. Con
`AGENT_STORE_BACKEND=memory` (el default) el paquete `google-cloud-firestore`
ni se importa.
"""

from __future__ import annotations

from app.agent.config import AgentSettings
from app.agent.persistence.ports import CheckpointStore


async def build_store(settings: AgentSettings) -> CheckpointStore:
    if settings.store_backend == "memory":
        from app.agent.persistence.backends.memory import InMemoryCheckpointStore

        return InMemoryCheckpointStore()

    if settings.store_backend == "firestore":
        from app.agent.persistence.backends.firestore import FirestoreCheckpointStore

        return FirestoreCheckpointStore.from_settings(settings)

    raise ValueError(f"AGENT_STORE_BACKEND={settings.store_backend!r} no está soportado.")
