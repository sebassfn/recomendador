"""Tools que el subagente `history_researcher` puede invocar.

Se construyen por request (no son globales) porque cada una necesita cerrar
sobre el `user_id` que pregunta y la sesión actual (para no "encontrarse a sí
misma" al listar el historial). Ambas leen del mismo `CheckpointStore`/
`StoreCheckpointSaver` que ya vive en `AgentRuntime` — no abren conexión
nueva, y la memoria de otra sesión se lee EXACTAMENTE como LangGraph la
guardó (un checkpoint), nunca de una tabla paralela.
"""

from __future__ import annotations

from langchain_core.tools import BaseTool, tool

from app.agent.runtime import AgentRuntime


def build_history_tools(runtime: AgentRuntime, *, user_id: str, current_session_id: str) -> list[BaseTool]:
    @tool
    async def list_user_sessions(limit: int = 5) -> list[dict]:
        """Lista las sesiones anteriores de ESTE usuario, más recientes primero.
        Cada una trae `session_id`, `title`, `summary` (puede ser None si esa
        sesión no dejó un resumen) y `updated_at`. Usala primero para ver QUÉ
        sesiones existen antes de pedir el detalle de una en particular."""
        threads = await runtime.store.list_threads(user_id=user_id, limit=limit + 1)
        return [
            {
                "session_id": t.thread_id,
                "title": t.title,
                "summary": t.summary,
                "updated_at": t.updated_at,
            }
            for t in threads
            if t.thread_id != current_session_id
        ][:limit]

    @tool
    async def get_session_digest(session_id: str) -> dict:
        """Devuelve el resumen neutral guardado de una sesión anterior
        puntual (necesidades, categorías, nombres de producto -- NUNCA
        precios). `session_id` viene de `list_user_sessions`."""
        tup = await runtime.checkpointer.aget_tuple({"configurable": {"thread_id": session_id}})
        if tup is None:
            return {"error": "Esa sesión no existe o no dejó estado guardado."}
        snapshot = tup.checkpoint.get("channel_values", {}).get("snapshot")
        if not snapshot:
            return {"session_id": session_id, "digest": None, "note": "Sin snapshot guardado en esa sesión."}
        return {"session_id": session_id, "digest": runtime.domain.summarize_snapshot(snapshot)}

    return [list_user_sessions, get_session_digest]
