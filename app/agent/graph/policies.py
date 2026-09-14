"""Política de reintentos de red para los nodos que llaman a un LLM o a una
tool externa (Firestore). Un solo lugar decide "vale la pena reintentar esto":
`app.agent.llm.errors.is_transient` clasifica la excepción, `RetryPolicy` de
LangGraph reintenta el nodo completo con backoff exponencial y jitter.

Esto es DISTINTO del control de iteraciones de negocio
(`AGENT_MAX_ITERATIONS`/`AGENT_MAX_SUBAGENT_ATTEMPTS` en `routing.py`): acá se
reintenta la MISMA llamada porque el servidor dijo "ocupado, probá de nuevo"
(429/5xx/timeout); allá se decide si vale la pena pedirle al orquestador que
REFORMULE la instrucción porque la llamada anterior fue mal (400) o el modelo
se equivocó.
"""

from __future__ import annotations

from langgraph.types import RetryPolicy

from app.agent.config import AgentSettings
from app.agent.llm.errors import is_transient


def network_retry_policy(settings: AgentSettings) -> RetryPolicy:
    return RetryPolicy(
        initial_interval=settings.retry_initial_interval,
        backoff_factor=settings.retry_backoff_factor,
        max_interval=settings.retry_max_interval,
        max_attempts=settings.retry_max_attempts,
        jitter=True,
        retry_on=is_transient,
    )
