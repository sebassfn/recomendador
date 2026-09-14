"""Proveedor OpenRouter (API compatible con OpenAI chat completions).

Variables de entorno propias de este proveedor:
    OPENROUTER_API_KEY    obligatoria.
    OPENROUTER_MODEL      opcional, default "openai/gpt-4o-mini".
    OPENROUTER_BASE_URL   opcional, default "https://openrouter.ai/api/v1".
    OPENROUTER_SITE_URL   opcional. Header HTTP-Referer que OpenRouter usa
                          para atribuir uso en su ranking público.
    OPENROUTER_APP_NAME   opcional. Header X-Title, mismo propósito.

Implementado con `urllib` de la stdlib a propósito: es una sola llamada
HTTP síncrona con forma de "OpenAI chat completions + tool_choice forzado",
y no vale la pena una dependencia nueva (`httpx`/`requests`) sólo para eso.
Cero paquetes adicionales -> este proveedor siempre está disponible, no hace
falta ningún extra de `pyproject.toml` para habilitarlo.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Mapping

from app.llm.contracts import LLMProvider, StructuredCompletionRequest, StructuredCompletionResult
from app.llm.errors import LLMConfigError, LLMOutputError, LLMRequestError

PROVIDER_NAME = "openrouter"
DEFAULT_MODEL = "openai/gpt-4o-mini"
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
_TIMEOUT_SECONDS = 30


class OpenRouterProvider(LLMProvider):
    name = PROVIDER_NAME

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = DEFAULT_BASE_URL,
        site_url: str | None = None,
        app_name: str | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._site_url = site_url
        self._app_name = app_name

    def complete_structured(self, request: StructuredCompletionRequest) -> StructuredCompletionResult:
        # Este proveedor no implementa prompt caching (endpoint OpenAI-
        # compatible, sin cache_control): `cacheable_prefix` simplemente se
        # antepone al mensaje. La salida es idéntica a la de un proveedor que
        # sí cachea; lo único que se pierde es el ahorro de costo/latencia.
        user_content = request.user_message
        if request.cacheable_prefix:
            user_content = f"{request.cacheable_prefix}\n\n{request.user_message}"

        payload = {
            "model": self._model,
            "max_tokens": request.max_tokens,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": user_content},
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": request.schema_name,
                        "description": request.schema_description,
                        "parameters": request.json_schema,
                    },
                }
            ],
            "tool_choice": {"type": "function", "function": {"name": request.schema_name}},
        }
        body = self._post("/chat/completions", payload)

        try:
            tool_calls = body["choices"][0]["message"]["tool_calls"]
            arguments = tool_calls[0]["function"]["arguments"]
            data: dict[str, Any] = json.loads(arguments) if isinstance(arguments, str) else arguments
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise LLMOutputError(
                f"OpenRouter ({self._model}) no devolvió un tool_call válido: {exc}"
            ) from exc

        return StructuredCompletionResult(data=data, provider=self.name, model=self._model)

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        if self._site_url:
            headers["HTTP-Referer"] = self._site_url
        if self._app_name:
            headers["X-Title"] = self._app_name

        http_request = urllib.request.Request(
            f"{self._base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(http_request, timeout=_TIMEOUT_SECONDS) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise LLMRequestError(f"OpenRouter ({self._model}) respondió {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise LLMRequestError(f"OpenRouter ({self._model}) no se pudo contactar: {exc.reason}") from exc
        except (TimeoutError, json.JSONDecodeError) as exc:
            raise LLMRequestError(f"OpenRouter ({self._model}) falló: {exc}") from exc


def create_provider(env: Mapping[str, str]) -> OpenRouterProvider:
    api_key = env.get("OPENROUTER_API_KEY")
    if not api_key:
        raise LLMConfigError("Falta OPENROUTER_API_KEY. Es obligatoria para LLM_PROVIDER=openrouter.")

    return OpenRouterProvider(
        api_key=api_key,
        model=env.get("OPENROUTER_MODEL") or DEFAULT_MODEL,
        base_url=env.get("OPENROUTER_BASE_URL") or DEFAULT_BASE_URL,
        site_url=env.get("OPENROUTER_SITE_URL") or None,
        app_name=env.get("OPENROUTER_APP_NAME") or None,
    )
