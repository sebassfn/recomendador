"""El único punto de extensión de este módulo: `AgentDomain`.

`app/agent` no sabe qué es una "misión de compra", un "ticket de soporte" o
cualquier otra cosa. Sabe orquestar subagentes, checkpointear en un store
intercambiable y desambiguar con HITL. Lo que produce al final —la forma del
`output`— lo define quien lo integra, implementando este `Protocol` en su
propio paquete (en este repo: `app/mission_agent/domain.py`).

Para copiar `app/agent/` a otro proyecto: se escribe un nuevo `AgentDomain` y
nada más de este directorio cambia.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

from app.agent.contracts import AgentRequest


@runtime_checkable
class AgentDomain(Protocol):
    """Lo que un dominio concreto debe declarar.

    - `name` identifica el dominio en prompts y logs.
    - `output_model` es el esquema Pydantic que el subagente `planner` debe
      emitir como salida estructurada. El grafo no conoce sus campos.
    - `prompt_key` selecciona la carpeta bajo `app/agent/prompts/domains/`
      (p. ej. `retail_mission/`) con el brief de negocio y las instrucciones
      del planner para ESTE dominio.
    - `shortcut(request)` es un atajo determinista, sin LLM, para casos
      exactos conocidos de antemano (p. ej. una caché de demo). `None` si no
      aplica: el turno sigue por el grafo completo.
    - `fallback(request)` es la respuesta de último recurso cuando el grafo
      agota reintentos/iteraciones sin una salida válida. A diferencia de
      `shortcut`, SIEMPRE debe devolver algo — nunca `None`.
    - `summarize_snapshot(snapshot)` convierte el snapshot neutral de una
      sesión pasada en una línea de texto legible para el subagente
      investigador de historial.
    """

    name: str
    output_model: type[BaseModel]
    prompt_key: str

    def shortcut(self, request: AgentRequest) -> dict[str, Any] | None: ...

    def fallback(self, request: AgentRequest) -> dict[str, Any]: ...

    def summarize_snapshot(self, snapshot: dict[str, Any]) -> str: ...
