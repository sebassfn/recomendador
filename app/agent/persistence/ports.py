"""Puerto de persistencia: lo único que un backend de checkpoints debe saber hacer.

Este `Protocol` es deliberadamente más chico y más plano que
`langgraph.checkpoint.base.BaseCheckpointSaver` — es KV puro sobre bytes, sin
tipos de LangGraph (`Checkpoint`, `CheckpointMetadata`...). Eso es lo que
permite desacoplar "qué base de datos" de "cómo LangGraph checkpointea":
`persistence/checkpointer.py` es el único módulo que traduce entre ambos
mundos. Escribir un backend nuevo (Postgres, Redis, un archivo...) es
implementar este `Protocol`, nada más.

Modelo de datos, en términos neutros:
- Un **thread** (`thread_id` = `session_id` del agente) tiene metadatos
  (`ThreadRecord`: quién es su dueño, cuándo se tocó por última vez) y una
  lista ordenada de **checkpoints**, cada uno con su blob serializado.
- Cada checkpoint puede tener **writes pendientes** asociados (resultados de
  pasos en curso que LangGraph no ha consolidado en un checkpoint todavía).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ThreadRecord:
    """Metadatos de una sesión, para listarlas por usuario sin deserializar
    checkpoints. `title`/`summary` son opcionales y los llena el dominio."""

    thread_id: str
    user_id: str
    created_at: str
    updated_at: str
    title: str | None = None
    summary: str | None = None


@dataclass(frozen=True)
class StoredCheckpoint:
    """Un checkpoint tal cual vive en el backend: bytes opacos + metadata.

    `checkpoint_ns` es el namespace de LangGraph (subgrafos); vacío en el uso
    normal de este proyecto. `checkpoint_blob`/`metadata_blob` son el
    resultado de `serde.dumps_typed` — este puerto nunca los interpreta.
    """

    checkpoint_id: str
    checkpoint_ns: str
    parent_checkpoint_id: str | None
    checkpoint_type: str
    checkpoint_blob: bytes
    metadata_type: str
    metadata_blob: bytes


@dataclass(frozen=True)
class StoredWrite:
    task_id: str
    idx: int
    channel: str
    value_type: str
    value_blob: bytes
    task_path: str = ""


class CheckpointStore(Protocol):
    """Puerto async que cada backend concreto implementa.

    Todos los métodos son idempotentes y seguros de reintentar: una escritura
    duplicada (mismo `checkpoint_id`) sobrescribe, nunca duplica.
    """

    async def put_checkpoint(
        self,
        *,
        thread_id: str,
        user_id: str,
        checkpoint_ns: str,
        checkpoint: StoredCheckpoint,
        thread_title: str | None = None,
        thread_summary: str | None = None,
    ) -> None: ...

    async def get_checkpoint(
        self, *, thread_id: str, checkpoint_ns: str, checkpoint_id: str | None
    ) -> StoredCheckpoint | None:
        """`checkpoint_id=None` devuelve el más reciente del thread/ns."""
        ...

    async def list_checkpoints(
        self,
        *,
        thread_id: str,
        checkpoint_ns: str,
        before_checkpoint_id: str | None = None,
        limit: int | None = None,
    ) -> list[StoredCheckpoint]:
        """Orden descendente (más reciente primero)."""
        ...

    async def put_writes(
        self,
        *,
        thread_id: str,
        checkpoint_ns: str,
        checkpoint_id: str,
        writes: list[StoredWrite],
    ) -> None: ...

    async def get_writes(
        self, *, thread_id: str, checkpoint_ns: str, checkpoint_id: str
    ) -> list[StoredWrite]: ...

    async def delete_thread(self, *, thread_id: str) -> None: ...

    async def list_threads(
        self, *, user_id: str, limit: int | None = None
    ) -> list[ThreadRecord]:
        """Sesiones de `user_id`, más recientes primero por `updated_at`."""
        ...

    async def aclose(self) -> None: ...
