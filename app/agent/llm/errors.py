"""Clasificación uniforme de fallas de red — LLM y cualquier tool externa
(Firestore incluido, ver `persistence/backends/firestore.py`).

Ningún nodo del grafo debe mirar el tipo de excepción nativo de un SDK
concreto (`anthropic.RateLimitError`, `httpx.TimeoutException`...). Todo pasa
por `classify()`, que lo traduce a una de estas cuatro categorías — es lo que
permite que `graph/policies.py` decida reintentar o no sin conocer qué
proveedor falló:

- `TransientError`: 429, 408, 5xx, timeouts, errores de conexión. Vale la
  pena reintentar la MISMA llamada (con backoff). Trae `retry_after` cuando
  el servidor lo indicó explícitamente (`Retry-After`).
- `BadRequestError`: 400/404/409/413/422. La llamada está mal formada para
  ESE input — reintentar igual no cambia nada; hace falta reformular la
  instrucción (el revisor + orquestador se encargan).
- `FatalError`: 401/403, credenciales o configuración. Ni reintentar ni
  reformular sirve — al fallback de dominio directo.
- `OutputError`: la llamada fue exitosa pero la salida no sirve (no valida
  contra el schema pedido, o el modelo no llamó a la tool esperada). Se trata
  como `BadRequestError` a efectos de ruteo (re-planificar, no reintentar).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass


class AgentLLMError(Exception):
    """Raíz de la jerarquía clasificada. No se levanta directamente."""


@dataclass
class TransientError(AgentLLMError):
    message: str
    retry_after: float | None = None

    def __str__(self) -> str:
        return self.message


@dataclass
class BadRequestError(AgentLLMError):
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass
class FatalError(AgentLLMError):
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass
class OutputError(AgentLLMError):
    message: str

    def __str__(self) -> str:
        return self.message


_TRANSIENT_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}
_FATAL_STATUS = {401, 403}


def _status_code(exc: Exception) -> int | None:
    code = getattr(exc, "status_code", None)
    if isinstance(code, int):
        return code
    response = getattr(exc, "response", None)
    code = getattr(response, "status_code", None)
    return code if isinstance(code, int) else None


def _retry_after(exc: Exception) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    value = headers.get("retry-after")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# Nombres de excepción que indican timeout/conexión sin necesariamente traer
# un status_code (p. ej. `anthropic.APITimeoutError`, `httpx.ConnectError`,
# `asyncio.TimeoutError`). Se matchea por nombre de clase, no por import
# directo del SDK -- ver docstring de `app.agent` sobre no acoplarse a un
# proveedor puntual.
_CONNECTIVITY_NAMES = {"APITimeoutError", "APIConnectionError", "TimeoutError", "ConnectError", "ConnectTimeout"}


def classify(exc: Exception) -> AgentLLMError:
    """Traduce cualquier excepción de un proveedor LLM (o de una tool externa
    HTTP) a una de las cuatro categorías de arriba. Nunca levanta: si no
    reconoce nada, degrada a `FatalError` (más seguro que reintentar algo
    desconocido en loop)."""
    status = _status_code(exc)
    if status in _TRANSIENT_STATUS:
        return TransientError(str(exc), retry_after=_retry_after(exc))
    if status in _FATAL_STATUS:
        return FatalError(str(exc))
    if status is not None and 400 <= status < 500:
        return BadRequestError(str(exc))

    if type(exc).__name__ in _CONNECTIVITY_NAMES:
        return TransientError(str(exc))

    return FatalError(f"Error no reconocido ({type(exc).__name__}): {exc}")


async def respect_retry_after(exc: Exception, *, cap: float) -> None:
    """Si `exc` es transitorio y el servidor mandó `Retry-After`, espera esa
    cantidad de tiempo (recortada a `cap`) ANTES de que el llamador re-levante
    la excepción para que `RetryPolicy` del nodo la reintente. El backoff
    exponencial de `RetryPolicy` sigue aplicando encima — esto respeta al pie
    de la letra lo que el proveedor pidió, sin reemplazar el mecanismo
    genérico de reintento del grafo."""
    classified = classify(exc)
    if isinstance(classified, TransientError) and classified.retry_after is not None:
        await asyncio.sleep(min(classified.retry_after, cap))


_KIND_BY_TYPE = {FatalError: "fatal", BadRequestError: "bad_request", OutputError: "output"}


def error_kind(err: AgentLLMError) -> str:
    """`"fatal"` / `"bad_request"` / `"output"` -- lo que
    `graph/nodes/reviewer.py` mira para decidir si un error de un subagente
    admite re-planificación o corta directo al fallback. Nunca se llama con
    un `TransientError`: ésos nunca llegan a anotarse como error de negocio,
    el `RetryPolicy` del nodo los reintenta antes de que el nodo termine."""
    return _KIND_BY_TYPE.get(type(err), "fatal")


def is_transient(exc: BaseException) -> bool:
    """Predicado para `langgraph.types.RetryPolicy.retry_on`."""
    if isinstance(exc, TransientError):
        return True
    if isinstance(exc, AgentLLMError):
        return False
    return isinstance(classify(exc), TransientError)  # type: ignore[arg-type]
