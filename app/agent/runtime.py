"""`AgentRuntime`: las dependencias vivas que el grafo compilado necesita.

Es el "pool de conexión" del que habla el enunciado: `AgentService.create`
lo arma UNA vez por proceso (un `CheckpointStore`, su `StoreCheckpointSaver`,
un `LLMRouter`) y lo pasa a `build_graph` como `context_schema`. A partir de
ahí, cada nodo lo recibe inyectado por LangGraph (`runtime: Runtime[AgentRuntime]`)
y lo usa de forma async sin volver a abrir conexiones. Nunca viaja dentro del
`AgentState` — el estado se checkpointea, el runtime no.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.agent.config import AgentSettings
from app.agent.domain import AgentDomain
from app.agent.llm.router import LLMRouter
from app.agent.persistence.checkpointer import StoreCheckpointSaver
from app.agent.persistence.ports import CheckpointStore


@dataclass
class AgentRuntime:
    store: CheckpointStore
    checkpointer: StoreCheckpointSaver
    llm_router: LLMRouter
    domain: AgentDomain
    settings: AgentSettings
