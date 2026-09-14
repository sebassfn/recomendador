"""Adaptador `CheckpointStore` (nuestro puerto) -> `BaseCheckpointSaver` (LangGraph).

Éste es el ÚNICO lugar donde este proyecto habla el protocolo binario de
checkpoints de LangGraph. Guarda cada checkpoint COMPLETO (con
`channel_values` embebido) como un blob por versión, en vez del esquema de
blobs-por-canal que usan los savers oficiales — es más simple, y
`BaseCheckpointSaver.aget_delta_channel_history` (el método del que depende
`interrupt`/`Command(resume=...)` para reconstruir historial de canales) tiene
un fallback genérico que camina la cadena de padres vía `aget_tuple` y
funciona perfecto contra checkpoints completos: no hay que reimplementarlo.

Es exclusivamente async — este proyecto nunca ejecuta el grafo en modo
síncrono, así que los métodos `get_tuple`/`put`/`list`/`put_writes` heredados
levantan `NotImplementedError` a propósito en vez de fingir soporte.
"""

from __future__ import annotations

import random
from collections.abc import AsyncIterator, Sequence
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    SerializerProtocol,
    get_checkpoint_id,
    get_checkpoint_metadata,
)

from app.agent.persistence.ports import CheckpointStore, StoredCheckpoint, StoredWrite


def _next_version(current: str | None) -> str:
    """Versión monótona con desempate aleatorio — mismo esquema que usan los
    savers oficiales (sqlite/postgres) para el tipo `str`."""
    current_v = 0 if current is None else int(current.split(".")[0])
    return f"{current_v + 1:032}.{random.random():016}"


class StoreCheckpointSaver(BaseCheckpointSaver[str]):
    """Envuelve cualquier `CheckpointStore` para que LangGraph lo use como
    memoria persistente. `runtime.py` instancia esto una sola vez por proceso
    y se lo pasa a `build_graph`."""

    def __init__(self, store: CheckpointStore, *, serde: SerializerProtocol | None = None) -> None:
        super().__init__(serde=serde)
        self._store = store

    # -- helpers --------------------------------------------------------

    @staticmethod
    def _user_id(config: RunnableConfig) -> str:
        user_id = config["configurable"].get("user_id")
        if not user_id:
            raise ValueError(
                "Falta 'user_id' en config['configurable']: AgentService siempre lo "
                "agrega, así que su ausencia es un bug del llamador."
            )
        return user_id

    def _to_stored(self, config: RunnableConfig, checkpoint: Checkpoint, metadata: CheckpointMetadata) -> StoredCheckpoint:
        checkpoint_type, checkpoint_blob = self.serde.dumps_typed(checkpoint)
        metadata_type, metadata_blob = self.serde.dumps_typed(
            get_checkpoint_metadata(config, metadata)
        )
        return StoredCheckpoint(
            checkpoint_id=checkpoint["id"],
            checkpoint_ns=config["configurable"].get("checkpoint_ns", ""),
            parent_checkpoint_id=config["configurable"].get("checkpoint_id"),
            checkpoint_type=checkpoint_type,
            checkpoint_blob=checkpoint_blob,
            metadata_type=metadata_type,
            metadata_blob=metadata_blob,
        )

    def _from_stored(self, thread_id: str, stored: StoredCheckpoint, pending_writes: list[tuple[str, str, Any]]) -> CheckpointTuple:
        checkpoint: Checkpoint = self.serde.loads_typed((stored.checkpoint_type, stored.checkpoint_blob))
        metadata: CheckpointMetadata = self.serde.loads_typed((stored.metadata_type, stored.metadata_blob))
        parent_config = (
            {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": stored.checkpoint_ns,
                    "checkpoint_id": stored.parent_checkpoint_id,
                }
            }
            if stored.parent_checkpoint_id
            else None
        )
        return CheckpointTuple(
            config={
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": stored.checkpoint_ns,
                    "checkpoint_id": stored.checkpoint_id,
                }
            },
            checkpoint=checkpoint,
            metadata=metadata,
            parent_config=parent_config,
            pending_writes=pending_writes,
        )

    # -- API async --------------------------------------------------------

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = get_checkpoint_id(config)

        stored = await self._store.get_checkpoint(
            thread_id=thread_id, checkpoint_ns=checkpoint_ns, checkpoint_id=checkpoint_id
        )
        if stored is None:
            return None

        raw_writes = await self._store.get_writes(
            thread_id=thread_id, checkpoint_ns=checkpoint_ns, checkpoint_id=stored.checkpoint_id
        )
        pending_writes = [
            (w.task_id, w.channel, self.serde.loads_typed((w.value_type, w.value_blob)))
            for w in sorted(raw_writes, key=lambda w: (w.task_id, w.idx))
        ]
        return self._from_stored(thread_id, stored, pending_writes)

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        if config is None:
            # Listar TODOS los threads de TODOS los usuarios no es una
            # operación que este saver soporte -- el índice por usuario vive
            # en `CheckpointStore.list_threads`, mucho más barato en
            # cualquier backend real. `AgentService.list_sessions` usa eso
            # directamente, nunca este método.
            raise NotImplementedError(
                "StoreCheckpointSaver.alist requiere un config con thread_id; "
                "para listar sesiones de un usuario usá AgentService.list_sessions."
            )

        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        before_id = get_checkpoint_id(before) if before else None

        stored_list = await self._store.list_checkpoints(
            thread_id=thread_id,
            checkpoint_ns=checkpoint_ns,
            before_checkpoint_id=before_id,
            # Si hay filtro de metadata pedimos de más y filtramos abajo:
            # el store no sabe deserializar metadata.
            limit=None if filter else limit,
        )

        yielded = 0
        for stored in stored_list:
            if filter:
                _, metadata = None, self.serde.loads_typed((stored.metadata_type, stored.metadata_blob))
                if not all(metadata.get(k) == v for k, v in filter.items()):
                    continue
            raw_writes = await self._store.get_writes(
                thread_id=thread_id, checkpoint_ns=checkpoint_ns, checkpoint_id=stored.checkpoint_id
            )
            pending_writes = [
                (w.task_id, w.channel, self.serde.loads_typed((w.value_type, w.value_blob)))
                for w in sorted(raw_writes, key=lambda w: (w.task_id, w.idx))
            ]
            yield self._from_stored(thread_id, stored, pending_writes)
            yielded += 1
            if limit is not None and yielded >= limit:
                break

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        stored = self._to_stored(config, checkpoint, metadata)

        await self._store.put_checkpoint(
            thread_id=thread_id,
            user_id=self._user_id(config),
            checkpoint_ns=checkpoint_ns,
            checkpoint=stored,
            thread_title=config["configurable"].get("thread_title"),
            thread_summary=config["configurable"].get("thread_summary"),
        )
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint["id"],
            }
        }

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = config["configurable"]["checkpoint_id"]

        stored_writes: list[StoredWrite] = []
        for idx, (channel, value) in enumerate(writes):
            value_type, value_blob = self.serde.dumps_typed(value)
            stored_writes.append(
                StoredWrite(
                    task_id=task_id,
                    idx=WRITES_IDX_MAP.get(channel, idx),
                    channel=channel,
                    value_type=value_type,
                    value_blob=value_blob,
                    task_path=task_path,
                )
            )
        await self._store.put_writes(
            thread_id=thread_id, checkpoint_ns=checkpoint_ns, checkpoint_id=checkpoint_id, writes=stored_writes
        )

    async def adelete_thread(self, thread_id: str) -> None:
        await self._store.delete_thread(thread_id=thread_id)

    def get_next_version(self, current: str | None, channel: None = None) -> str:
        return _next_version(current)

    # -- sync: este módulo es async-only ------------------------------------

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        raise NotImplementedError("StoreCheckpointSaver es async-only; usá aget_tuple.")

    def list(self, config: RunnableConfig | None, **kwargs: Any) -> Any:
        raise NotImplementedError("StoreCheckpointSaver es async-only; usá alist.")

    def put(self, config: RunnableConfig, checkpoint: Checkpoint, metadata: CheckpointMetadata, new_versions: ChannelVersions) -> RunnableConfig:
        raise NotImplementedError("StoreCheckpointSaver es async-only; usá aput.")

    def put_writes(self, config: RunnableConfig, writes: Sequence[tuple[str, Any]], task_id: str, task_path: str = "") -> None:
        raise NotImplementedError("StoreCheckpointSaver es async-only; usá aput_writes.")

    def delete_thread(self, thread_id: str) -> None:
        raise NotImplementedError("StoreCheckpointSaver es async-only; usá adelete_thread.")
