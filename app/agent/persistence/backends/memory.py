"""Backend en memoria de proceso: implementa `CheckpointStore` con `dict` +
`asyncio.Lock`. Es el backend de tests y de desarrollo local sin credenciales
de Firebase (`AGENT_STORE_BACKEND=memory`, el default). Nunca usar en
producción con más de una instancia — como el resto de la app (CLAUDE.md:
"carrito no persistente" era la misma restricción), el estado muere con el
proceso.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict

from app.agent.persistence.ports import StoredCheckpoint, StoredWrite, ThreadRecord


def _now() -> str:
    return f"{time.time():.6f}"


class InMemoryCheckpointStore:
    """`CheckpointStore` de referencia. Ver `ports.py` para el contrato."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._threads: dict[str, ThreadRecord] = {}
        # (thread_id, checkpoint_ns) -> {checkpoint_id: StoredCheckpoint}
        self._checkpoints: dict[tuple[str, str], dict[str, StoredCheckpoint]] = defaultdict(dict)
        # (thread_id, checkpoint_ns, checkpoint_id) -> [StoredWrite]
        self._writes: dict[tuple[str, str, str], list[StoredWrite]] = defaultdict(list)

    async def put_checkpoint(
        self,
        *,
        thread_id: str,
        user_id: str,
        checkpoint_ns: str,
        checkpoint: StoredCheckpoint,
        thread_title: str | None = None,
        thread_summary: str | None = None,
    ) -> None:
        async with self._lock:
            self._checkpoints[(thread_id, checkpoint_ns)][checkpoint.checkpoint_id] = checkpoint
            existing = self._threads.get(thread_id)
            self._threads[thread_id] = ThreadRecord(
                thread_id=thread_id,
                user_id=user_id,
                created_at=existing.created_at if existing else _now(),
                updated_at=_now(),
                title=thread_title if thread_title is not None else (existing.title if existing else None),
                summary=thread_summary if thread_summary is not None else (existing.summary if existing else None),
            )

    async def get_checkpoint(
        self, *, thread_id: str, checkpoint_ns: str, checkpoint_id: str | None
    ) -> StoredCheckpoint | None:
        async with self._lock:
            bucket = self._checkpoints.get((thread_id, checkpoint_ns), {})
            if checkpoint_id is not None:
                return bucket.get(checkpoint_id)
            if not bucket:
                return None
            return max(bucket.values(), key=lambda c: c.checkpoint_id)

    async def list_checkpoints(
        self,
        *,
        thread_id: str,
        checkpoint_ns: str,
        before_checkpoint_id: str | None = None,
        limit: int | None = None,
    ) -> list[StoredCheckpoint]:
        async with self._lock:
            bucket = self._checkpoints.get((thread_id, checkpoint_ns), {})
            items = sorted(bucket.values(), key=lambda c: c.checkpoint_id, reverse=True)
        if before_checkpoint_id is not None:
            items = [c for c in items if c.checkpoint_id < before_checkpoint_id]
        if limit is not None:
            items = items[:limit]
        return items

    async def put_writes(
        self,
        *,
        thread_id: str,
        checkpoint_ns: str,
        checkpoint_id: str,
        writes: list[StoredWrite],
    ) -> None:
        async with self._lock:
            existing = self._writes[(thread_id, checkpoint_ns, checkpoint_id)]
            index = {(w.task_id, w.idx): i for i, w in enumerate(existing)}
            for write in writes:
                key = (write.task_id, write.idx)
                # Mismo criterio de idempotencia que los savers oficiales:
                # un índice ya escrito por esa tarea no se pisa, salvo los
                # canales especiales (idx negativo en WRITES_IDX_MAP).
                if write.idx >= 0 and key in index:
                    continue
                existing.append(write)

    async def get_writes(
        self, *, thread_id: str, checkpoint_ns: str, checkpoint_id: str
    ) -> list[StoredWrite]:
        async with self._lock:
            return list(self._writes.get((thread_id, checkpoint_ns, checkpoint_id), []))

    async def delete_thread(self, *, thread_id: str) -> None:
        async with self._lock:
            self._threads.pop(thread_id, None)
            for key in [k for k in self._checkpoints if k[0] == thread_id]:
                del self._checkpoints[key]
            for key in [k for k in self._writes if k[0] == thread_id]:
                del self._writes[key]

    async def list_threads(self, *, user_id: str, limit: int | None = None) -> list[ThreadRecord]:
        async with self._lock:
            threads = [t for t in self._threads.values() if t.user_id == user_id]
        threads.sort(key=lambda t: t.updated_at, reverse=True)
        return threads[:limit] if limit is not None else threads

    async def aclose(self) -> None:
        return None
