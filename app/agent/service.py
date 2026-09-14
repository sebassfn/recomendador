"""`AgentService`: la fachada pública de todo el módulo.

Es lo único que un anfitrión instancia. Por dentro arma el "pool de
conexión" (`AgentRuntime`: el `CheckpointStore`, su `StoreCheckpointSaver`, el
`LLMRouter`) UNA sola vez con `create()` y compila el grafo sobre eso — desde
ahí, cada llamada a `run()` es async y no vuelve a abrir nada.

`run()` es el único punto de entrada de negocio: decide sola si el turno es
un arranque normal o la reanudación de una clarificación pendiente
(`request.resume`), traduce `interrupt()`/`GraphRecursionError` a los
`AgentStatus` del contrato, y nunca deja escapar un tipo de LangGraph hacia
el anfitrión.
"""

from __future__ import annotations

from uuid import uuid4

from langgraph.errors import GraphRecursionError
from langgraph.types import Command

from app.agent.config import AgentSettings
from app.agent.contracts import (
    AgentMode,
    AgentRequest,
    AgentResponse,
    AgentStatus,
    AgentTrace,
    ClarificationRequest,
    SessionSummary,
)
from app.agent.domain import AgentDomain
from app.agent.graph.builder import build_graph
from app.agent.llm.router import LLMRouter
from app.agent.persistence.checkpointer import StoreCheckpointSaver
from app.agent.persistence.factory import build_store
from app.agent.runtime import AgentRuntime


class AgentService:
    def __init__(self, *, runtime: AgentRuntime, graph) -> None:
        self._runtime = runtime
        self._graph = graph

    @classmethod
    async def create(cls, domain: AgentDomain, settings: AgentSettings | None = None) -> "AgentService":
        settings = settings or AgentSettings()
        store = await build_store(settings)
        checkpointer = StoreCheckpointSaver(store)
        runtime = AgentRuntime(
            store=store,
            checkpointer=checkpointer,
            llm_router=LLMRouter(settings),
            domain=domain,
            settings=settings,
        )
        graph = build_graph(runtime)
        return cls(runtime=runtime, graph=graph)

    async def aclose(self) -> None:
        await self._runtime.store.aclose()

    def _config(self, request: AgentRequest, session_id: str) -> dict:
        configurable: dict = {
            "thread_id": session_id,
            "user_id": request.user_id,
            "checkpoint_ns": "",
        }
        if request.mode is AgentMode.START:
            configurable["thread_title"] = request.message[:80]
        if request.snapshot is not None:
            configurable["thread_summary"] = self._runtime.domain.summarize_snapshot(request.snapshot)
        return {"configurable": configurable, "recursion_limit": self._runtime.settings.recursion_limit}

    async def run(self, request: AgentRequest) -> AgentResponse:
        session_id = request.session_id or uuid4().hex
        if request.session_id is None:
            request = request.model_copy(update={"session_id": session_id})
        config = self._config(request, session_id)

        try:
            if request.resume is not None:
                result = await self._graph.ainvoke(
                    Command(resume=request.resume.model_dump(mode="json")), config, context=self._runtime
                )
            else:
                graph_input: dict = {
                    "request": request.model_dump(mode="json"),
                    "user_id": request.user_id,
                }
                if request.snapshot is not None:
                    graph_input["snapshot"] = request.snapshot
                result = await self._graph.ainvoke(graph_input, config, context=self._runtime)
        except GraphRecursionError:
            return await self._error_fallback(request, session_id, config, "Se alcanzó AGENT_RECURSION_LIMIT.")
        except Exception as exc:  # noqa: BLE001 - último resguardo, ver docstring
            return await self._error_fallback(
                request, session_id, config, f"Fallo no clasificado del agente: {exc}"
            )

        interrupts = result.get("__interrupt__")
        if interrupts:
            payload = interrupts[0].value
            return AgentResponse(
                session_id=session_id,
                status=AgentStatus.NEEDS_CLARIFICATION,
                message=payload["question"],
                clarification=ClarificationRequest.model_validate(payload),
                produced_by="agent",
                trace=AgentTrace(
                    iterations=result.get("iteration", 0),
                    models_used=result.get("models_used", {}),
                ),
            )

        return AgentResponse(
            session_id=session_id,
            status=AgentStatus(result["status"]),
            output=result.get("domain_output"),
            message=result.get("message_out", ""),
            produced_by=result.get("produced_by") or "agent",
            trace=AgentTrace(
                iterations=result.get("iteration", 0),
                models_used=result.get("models_used", {}),
                warnings=result.get("warnings", []),
            ),
        )

    async def _error_fallback(self, request: AgentRequest, session_id: str, config: dict, reason: str) -> AgentResponse:
        """Backstop final: NINGUNA excepción del grafo debe llegarle al
        anfitrión. `GraphRecursionError` es el caso esperado (un bug de ruteo
        haría reciclar pasos por encima de `AGENT_MAX_ITERATIONS`, que
        debería haber cortado antes vía `fallback`); cualquier otra excepción
        no clasificada (config rota, un bug real) cae acá igual -- siempre se
        responde con el fallback determinista del dominio en vez de
        propagar."""
        try:
            state = await self._graph.aget_state(config)
            iteration = state.values.get("iteration", 0)
        except Exception:  # noqa: BLE001 - ni siquiera leer el estado puede tumbar esto
            iteration = 0
        output = self._runtime.domain.fallback(request)
        return AgentResponse(
            session_id=session_id,
            status=AgentStatus.PARTIAL,
            output=output,
            message="Tuve un problema interno resolviendo tu pedido; devolví una respuesta de resguardo.",
            produced_by="fallback",
            trace=AgentTrace(iterations=iteration, warnings=[reason]),
        )

    async def list_sessions(self, user_id: str, *, limit: int | None = None) -> list[SessionSummary]:
        threads = await self._runtime.store.list_threads(user_id=user_id, limit=limit)
        return [
            SessionSummary(
                session_id=t.thread_id,
                title=t.title,
                summary=t.summary,
                created_at=t.created_at,
                updated_at=t.updated_at,
            )
            for t in threads
        ]

    async def record_snapshot(self, *, session_id: str, user_id: str, snapshot: dict) -> None:
        """Actualiza el snapshot de una sesión SIN correr el grafo -- útil
        cuando el anfitrión quiere dejar memoria de algo que pasó fuera de un
        turno del agente (p. ej. el carrito cambió por una acción determinista)."""
        config = {
            "configurable": {
                "thread_id": session_id,
                "user_id": user_id,
                "checkpoint_ns": "",
                "thread_summary": self._runtime.domain.summarize_snapshot(snapshot),
            }
        }
        await self._graph.aupdate_state(config, {"snapshot": snapshot})
