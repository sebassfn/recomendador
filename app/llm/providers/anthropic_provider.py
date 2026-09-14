"""Proveedor Anthropic — el default del stack (CLAUDE.md: `claude-opus-5`).

Variables de entorno propias de este proveedor:
    ANTHROPIC_API_KEY   obligatoria.
    ANTHROPIC_MODEL     opcional, default "claude-opus-5".

El SDK `anthropic` se importa dentro de `__init__`, no en el tope del
módulo: este módulo sólo se importa cuando `LLM_PROVIDER=anthropic` (o el
default), así que un despliegue que use otro proveedor nunca paga el costo
—ni el requisito— de tenerlo instalado.
"""

from __future__ import annotations

from typing import Any, Mapping

from app.llm.contracts import LLMProvider, StructuredCompletionRequest, StructuredCompletionResult
from app.llm.errors import LLMConfigError, LLMOutputError, LLMRequestError

PROVIDER_NAME = "anthropic"
DEFAULT_MODEL = "claude-opus-5"


class AnthropicProvider(LLMProvider):
    name = PROVIDER_NAME

    def __init__(self, api_key: str, model: str, client: Any | None = None) -> None:
        if client is not None:
            self._client = client
        else:
            try:
                import anthropic
            except ImportError as exc:
                raise LLMConfigError(
                    "El paquete 'anthropic' no está instalado. Es una dependencia "
                    "base del proyecto (pyproject.toml); revisá el entorno con `uv sync`."
                ) from exc

            self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def complete_structured(self, request: StructuredCompletionRequest) -> StructuredCompletionResult:
        tool: dict[str, Any] = {
            "name": request.schema_name,
            "description": request.schema_description,
            "input_schema": request.json_schema,
        }
        if request.cacheable_prefix:
            # El prefijo va en su propio bloque con cache_control: la
            # primera llamada de la sesión lo escribe en caché, el resto lo
            # lee a ~0.1x (doc 01 §8.3). `user_message` es el bloque volátil
            # que cambia en cada llamada, así que va aparte y sin cachear.
            content: Any = [
                {
                    "type": "text",
                    "text": request.cacheable_prefix,
                    "cache_control": {"type": "ephemeral"},
                },
                {"type": "text", "text": request.user_message},
            ]
        else:
            content = request.user_message

        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=request.max_tokens,
                system=request.system_prompt,
                messages=[{"role": "user", "content": content}],
                tools=[tool],
                tool_choice={"type": "tool", "name": request.schema_name},
            )
        except Exception as exc:
            raise LLMRequestError(f"Anthropic ({self._model}) falló: {exc}") from exc

        tool_use = next((block for block in response.content if block.type == "tool_use"), None)
        if tool_use is None:
            raise LLMOutputError(f"Anthropic ({self._model}) no devolvió un bloque tool_use.")

        return StructuredCompletionResult(data=tool_use.input, provider=self.name, model=self._model)


def create_provider(env: Mapping[str, str]) -> AnthropicProvider:
    api_key = env.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise LLMConfigError("Falta ANTHROPIC_API_KEY. Es obligatoria para LLM_PROVIDER=anthropic.")

    model = env.get("ANTHROPIC_MODEL") or DEFAULT_MODEL
    return AnthropicProvider(api_key=api_key, model=model)
