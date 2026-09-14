"""Contrato común de proveedores LLM.

Quien use esta capa (hoy `app.llm.citation`) depende ÚNICAMENTE de
`LLMProvider` y de los dos dataclasses de este módulo. La interpretación de la
necesidad ya no pasa por acá: la hace el agente (`app/agent/`), con sus
propios proveedores en `app/agent/llm/`. Ningún detalle de un proveedor concreto —forma de su
respuesta cruda, nombre de sus endpoints, sus excepciones nativas— cruza esta
frontera: cada proveedor en `app.llm.providers` traduce lo suyo a
`StructuredCompletionResult` o a uno de los errores de `app.llm.errors`.

Es deliberadamente genérico: no menciona `MissionPlan` en ningún campo. Hoy lo
usa la extracción de citas; mañana podría usarlo cualquier otra feature que
necesite "texto -> JSON estructurado" de un LLM intercambiable.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StructuredCompletionRequest:
    """Lo único que un proveedor necesita para responder.

    `cacheable_prefix` es opcional y marca contenido que se repite igual
    entre muchas llamadas (p. ej. el corpus completo de documentos del
    Tramo A de citas, doc 01 §8.3): un proveedor que sepa cachear prompts
    (hoy sólo `AnthropicProvider`, con `cache_control: ephemeral`) lo hace
    con esto; el resto simplemente lo antepone a `user_message` como texto
    normal. En ambos casos el resultado semántico es idéntico — lo único
    que cambia es si la llamada paga o no el costo de ese prefijo de nuevo.
    """

    system_prompt: str
    user_message: str
    schema_name: str
    schema_description: str
    json_schema: dict[str, Any]
    max_tokens: int = 2048
    cacheable_prefix: str | None = None


@dataclass(frozen=True)
class StructuredCompletionResult:
    """Lo que todo proveedor devuelve, sin importar cómo lo obtuvo.

    `data` ya es un `dict` parseado (no una respuesta cruda del SDK); el
    llamador lo valida contra su propio modelo Pydantic. `provider` y `model`
    son metadatos de auditoría (para logs y, eventualmente, un badge en la
    pantalla de diagnóstico).
    """

    data: dict[str, Any]
    provider: str
    model: str


class LLMProvider(ABC):
    """Contrato que cualquier proveedor debe cumplir para ser intercambiable.

    `name` identifica al proveedor y coincide con el valor de `LLM_PROVIDER`
    que lo selecciona en `app.llm.factory`. `complete_structured` es el único
    método que la aplicación llama: recibe el pedido genérico y devuelve la
    respuesta parseada, o levanta una subclase de `app.llm.errors.LLMError`
    — nunca la excepción nativa del SDK/HTTP del proveedor.
    """

    name: str

    @abstractmethod
    def complete_structured(self, request: StructuredCompletionRequest) -> StructuredCompletionResult:
        raise NotImplementedError
