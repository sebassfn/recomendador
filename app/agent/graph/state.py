"""El estado del grafo: lo único que LangGraph checkpointea.

Dos ciclos de vida conviven en el mismo `TypedDict`:

- **De sesión** (sobrevive entre turnos): `user_id`, `messages` (historial
  completo, vía el reducer estándar `add_messages`) y `snapshot` (el resumen
  neutral más reciente que el anfitrión mandó). `intake`, `clarify` y
  `finalize` registran mensajes; `AgentService.record_snapshot` actualiza
  el resumen del anfitrión.
- **De turno** (reseteado por `nodes/intake.py` al principio de cada turno):
  todo lo demás — contadores de iteración/intentos, qué nivel de modelo usa
  cada rol este turno, los resultados de los subagentes, errores acumulados,
  el veredicto del revisor y la clarificación pendiente.

`results` y `errors` necesitan un reducer propio porque el orquestador puede
despachar `history_researcher` y `disambiguator` EN PARALELO (`Send`): ambos
escriben en el mismo superstep, y sin un reducer que sepa fusionar dicts/listas
LangGraph rechaza la escritura ("can receive only one value per step"). El
mismo reducer soporta un "reset" explícito (`{"__reset__": True}` /
`["__reset__"]`) para que `intake` pueda vaciarlos sin que la semántica de
merge se lo impida (un merge nunca puede borrar, sólo agregar).
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


def merge_results(current: dict[str, Any] | None, update: dict[str, Any]) -> dict[str, Any]:
    if update.get("__reset__"):
        return {}
    return {**(current or {}), **update}


def merge_errors(current: list[dict[str, Any]] | None, update: list[Any]) -> list[dict[str, Any]]:
    if update == ["__reset__"]:
        return []
    return [*(current or []), *update]


def merge_dicts(current: dict[str, Any] | None, update: dict[str, Any]) -> dict[str, Any]:
    """Unión simple, sin reset -- para `models_used`, que un `intake` puede
    vaciar de un solo saque (sobreescribiendo, no en paralelo con nadie) pero
    que `history_researcher`/`disambiguator` SÍ pueden escribir en el mismo
    superstep vía `Send`."""
    return {**(current or {}), **update}


RESET_RESULTS: dict[str, Any] = {"__reset__": True}
RESET_ERRORS: list[Any] = ["__reset__"]


class AgentState(TypedDict, total=False):
    # -- de sesión ----------------------------------------------------------
    user_id: str
    messages: Annotated[list[BaseMessage], add_messages]
    snapshot: dict[str, Any] | None

    # -- de turno -------------------------------------------------------
    request: dict[str, Any]
    """`AgentRequest.model_dump()` del turno en curso."""

    iteration: int
    tier_overrides: dict[str, str]
    """rol -> "reasoning" para ESTE turno. Vacío = todos en STANDARD."""
    attempts: dict[str, int]
    """subagente -> veces que corrió este turno (guarda de reintento de negocio,
    distinta de `RetryPolicy`, que es reintento de RED)."""
    decision: dict[str, Any] | None
    """Última `OrchestratorDecision` ya validada/filtrada por el nodo
    `orchestrator` -- `routing.py` sólo la lee, nunca reinterpreta al LLM."""
    last_dispatch: list[str]
    """Nombres de los subagentes despachados en el ciclo más reciente -- así
    `reviewer` sabe cuáles de `results` son frescos de ESTE ciclo y no
    sobrantes de un ciclo anterior dentro del mismo turno."""
    task: dict[str, Any]
    """Sólo presente en el `state` que recibe un subagente despachado vía
    `Send`: la tarea puntual que le tocó. Nunca se persiste -- ningún nodo lo
    devuelve como parte de su actualización."""

    results: Annotated[dict[str, Any], merge_results]
    """subagente -> su salida cruda de este ciclo de investigación/planificación."""
    errors: Annotated[list[dict[str, Any]], merge_errors]
    """errores clasificados (`app.agent.llm.errors`) de este ciclo, para que
    el revisor y el orquestador los vean."""

    review: dict[str, Any] | None
    """Último `ReviewVerdict.model_dump()`."""
    clarifications_used: int
    """Respuestas a aclaraciones del pedido actual. Se conserva en resume;
    intake lo reinicia al abrir un pedido nuevo en la misma sesión."""

    domain_output: dict[str, Any] | None
    status: str
    produced_by: str
    message_out: str
    warnings: list[str]
    models_used: Annotated[dict[str, str], merge_dicts]
    retries: int


def fresh_turn_fields(request: dict[str, Any]) -> dict[str, Any]:
    """Lo que `nodes/intake.py` escribe para abrir un turno nuevo."""
    return {
        "request": request,
        "iteration": 0,
        "tier_overrides": {},
        "attempts": {},
        "decision": None,
        "last_dispatch": [],
        "results": RESET_RESULTS,
        "errors": RESET_ERRORS,
        "review": None,
        "clarifications_used": 0,
        "domain_output": None,
        "status": None,
        "produced_by": None,
        "message_out": "",
        "warnings": [],
        "models_used": {},
        "retries": 0,
    }
