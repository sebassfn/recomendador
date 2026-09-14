"""Backend de producción: Cloud Firestore.

Layout de colecciones (todas bajo el prefijo `AGENT_FIRESTORE_COLLECTION_PREFIX`,
default `agent`):

    {prefix}_threads/{thread_id}                        -> ThreadRecord
        checkpoints/{checkpoint_ns}:{checkpoint_id}      -> StoredCheckpoint
        writes/{checkpoint_ns}:{checkpoint_id}:{task_id}:{idx} -> StoredWrite

`thread_id` es el `session_id` del agente. Listar las sesiones de un usuario
(`list_threads`) es una query indexada por `user_id` + `updated_at desc` sobre
la colección de threads — necesita un índice compuesto en Firestore (ver
`app/agent/README.md`).

Un solo `AsyncClient` (un solo canal gRPC) se crea en `runtime.py` y se
comparte entre todas las corridas del grafo — es el "pool de conexión" que el
resto del módulo nunca ve directamente.

Reintentos: cada llamada de red pasa por un `AsyncRetry` configurado con los
`AGENT_RETRY_*` de `AgentSettings`, con la misma noción de "transitorio" que
`app.agent.llm.errors` (429/408/5xx, no 4xx de negocio) — Firestore expresa
eso como `ResourceExhausted`, `ServiceUnavailable`, `DeadlineExceeded` y
`Aborted` (contención de transacción).
"""

from __future__ import annotations

from google.api_core import exceptions as gexc
from google.api_core.retry_async import AsyncRetry
from google.cloud.firestore import AsyncClient  # type: ignore[import-untyped]

from app.agent.config import AgentSettings
from app.agent.persistence.ports import StoredCheckpoint, StoredWrite, ThreadRecord

_TRANSIENT_EXCEPTIONS = (
    gexc.ResourceExhausted,  # 429
    gexc.ServiceUnavailable,  # 503
    gexc.DeadlineExceeded,  # 504
    gexc.Aborted,  # transacción en contención, reintentable
    gexc.InternalServerError,  # 500
)


def _is_transient(exc: Exception) -> bool:
    return isinstance(exc, _TRANSIENT_EXCEPTIONS)


def _checkpoint_doc_id(checkpoint_ns: str, checkpoint_id: str) -> str:
    return f"{checkpoint_ns}:{checkpoint_id}"


def _write_doc_id(checkpoint_ns: str, checkpoint_id: str, task_id: str, idx: int) -> str:
    return f"{checkpoint_ns}:{checkpoint_id}:{task_id}:{idx}"


def _checkpoint_to_doc(checkpoint: StoredCheckpoint) -> dict:
    return {
        "checkpoint_id": checkpoint.checkpoint_id,
        "checkpoint_ns": checkpoint.checkpoint_ns,
        "parent_checkpoint_id": checkpoint.parent_checkpoint_id,
        "checkpoint_type": checkpoint.checkpoint_type,
        "checkpoint_blob": checkpoint.checkpoint_blob,
        "metadata_type": checkpoint.metadata_type,
        "metadata_blob": checkpoint.metadata_blob,
    }


def _doc_to_checkpoint(doc: dict) -> StoredCheckpoint:
    return StoredCheckpoint(
        checkpoint_id=doc["checkpoint_id"],
        checkpoint_ns=doc["checkpoint_ns"],
        parent_checkpoint_id=doc.get("parent_checkpoint_id"),
        checkpoint_type=doc["checkpoint_type"],
        checkpoint_blob=bytes(doc["checkpoint_blob"]),
        metadata_type=doc["metadata_type"],
        metadata_blob=bytes(doc["metadata_blob"]),
    )


class FirestoreCheckpointStore:
    """`CheckpointStore` sobre Cloud Firestore. Ver el docstring del módulo."""

    def __init__(self, client: AsyncClient, settings: AgentSettings, *, owns_client: bool = True) -> None:
        self._client = client
        self._owns_client = owns_client
        self._prefix = settings.firestore_collection_prefix
        self._retry = AsyncRetry(
            predicate=_is_transient,
            initial=settings.retry_initial_interval,
            maximum=settings.retry_max_interval,
            multiplier=settings.retry_backoff_factor,
            timeout=settings.retry_initial_interval * (2**settings.retry_max_attempts) + 5,
        )

    @classmethod
    def from_settings(cls, settings: AgentSettings) -> "FirestoreCheckpointStore":
        client = AsyncClient(project=settings.firestore_project, database=settings.firestore_database)
        return cls(client, settings, owns_client=True)

    def _threads(self):
        return self._client.collection(f"{self._prefix}_threads")

    def _thread_doc(self, thread_id: str):
        return self._threads().document(thread_id)

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
        from google.cloud.firestore import SERVER_TIMESTAMP  # type: ignore[import-untyped]

        thread_doc = self._thread_doc(thread_id)
        thread_fields: dict = {"user_id": user_id, "updated_at": SERVER_TIMESTAMP}
        if thread_title is not None:
            thread_fields["title"] = thread_title
        if thread_summary is not None:
            thread_fields["summary"] = thread_summary

        existing = await self._retry(thread_doc.get)()
        if not existing.exists:
            thread_fields["created_at"] = SERVER_TIMESTAMP
        await self._retry(thread_doc.set)(thread_fields, merge=True)

        checkpoint_doc = thread_doc.collection("checkpoints").document(
            _checkpoint_doc_id(checkpoint.checkpoint_ns, checkpoint.checkpoint_id)
        )
        await self._retry(checkpoint_doc.set)(_checkpoint_to_doc(checkpoint))

    async def get_checkpoint(
        self, *, thread_id: str, checkpoint_ns: str, checkpoint_id: str | None
    ) -> StoredCheckpoint | None:
        checkpoints = self._thread_doc(thread_id).collection("checkpoints")
        if checkpoint_id is not None:
            snapshot = await self._retry(checkpoints.document(_checkpoint_doc_id(checkpoint_ns, checkpoint_id)).get)()
            if not snapshot.exists:
                return None
            return _doc_to_checkpoint(snapshot.to_dict())

        query = checkpoints.where("checkpoint_ns", "==", checkpoint_ns).order_by(
            "checkpoint_id", direction="DESCENDING"
        ).limit(1)
        docs = await self._retry(query.get)()
        return _doc_to_checkpoint(docs[0].to_dict()) if docs else None

    async def list_checkpoints(
        self,
        *,
        thread_id: str,
        checkpoint_ns: str,
        before_checkpoint_id: str | None = None,
        limit: int | None = None,
    ) -> list[StoredCheckpoint]:
        query = self._thread_doc(thread_id).collection("checkpoints").where(
            "checkpoint_ns", "==", checkpoint_ns
        ).order_by("checkpoint_id", direction="DESCENDING")
        if before_checkpoint_id is not None:
            query = query.where("checkpoint_id", "<", before_checkpoint_id)
        if limit is not None:
            query = query.limit(limit)
        docs = await self._retry(query.get)()
        return [_doc_to_checkpoint(d.to_dict()) for d in docs]

    async def put_writes(
        self,
        *,
        thread_id: str,
        checkpoint_ns: str,
        checkpoint_id: str,
        writes: list[StoredWrite],
    ) -> None:
        writes_col = self._thread_doc(thread_id).collection("writes")
        batch = self._client.batch()
        for write in writes:
            doc_id = _write_doc_id(checkpoint_ns, checkpoint_id, write.task_id, write.idx)
            doc_ref = writes_col.document(doc_id)
            if write.idx >= 0:
                # Idempotencia: un índice ya escrito por esa tarea no se pisa
                # (mismo criterio que los backends oficiales). Los canales
                # especiales (idx negativo) sí se sobrescriben siempre.
                existing = await self._retry(doc_ref.get)()
                if existing.exists:
                    continue
            batch.set(
                doc_ref,
                {
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": checkpoint_id,
                    "task_id": write.task_id,
                    "idx": write.idx,
                    "channel": write.channel,
                    "value_type": write.value_type,
                    "value_blob": write.value_blob,
                    "task_path": write.task_path,
                },
            )
        await self._retry(batch.commit)()

    async def get_writes(
        self, *, thread_id: str, checkpoint_ns: str, checkpoint_id: str
    ) -> list[StoredWrite]:
        query = (
            self._thread_doc(thread_id)
            .collection("writes")
            .where("checkpoint_ns", "==", checkpoint_ns)
            .where("checkpoint_id", "==", checkpoint_id)
        )
        docs = await self._retry(query.get)()
        return [
            StoredWrite(
                task_id=d.get("task_id"),
                idx=d.get("idx"),
                channel=d.get("channel"),
                value_type=d.get("value_type"),
                value_blob=bytes(d.get("value_blob")),
                task_path=d.get("task_path") or "",
            )
            for d in (doc.to_dict() for doc in docs)
        ]

    async def delete_thread(self, *, thread_id: str) -> None:
        thread_doc = self._thread_doc(thread_id)
        for sub in ("checkpoints", "writes"):
            async for doc in thread_doc.collection(sub).stream(retry=self._retry):
                await self._retry(doc.reference.delete)()
        await self._retry(thread_doc.delete)()

    async def list_threads(self, *, user_id: str, limit: int | None = None) -> list[ThreadRecord]:
        query = self._threads().where("user_id", "==", user_id).order_by("updated_at", direction="DESCENDING")
        if limit is not None:
            query = query.limit(limit)
        docs = await self._retry(query.get)()

        def _iso(value) -> str:
            return value.isoformat() if value is not None else ""

        return [
            ThreadRecord(
                thread_id=doc.id,
                user_id=data["user_id"],
                created_at=_iso(data.get("created_at")),
                updated_at=_iso(data.get("updated_at")),
                title=data.get("title"),
                summary=data.get("summary"),
            )
            for doc, data in ((d, d.to_dict()) for d in docs)
        ]

    async def aclose(self) -> None:
        if self._owns_client:
            self._client.close()
