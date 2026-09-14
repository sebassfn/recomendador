"""Proveedor Google Cloud — Vertex AI (modelos Gemini), vía el SDK `google-genai`.

Variables de entorno propias de este proveedor:
    GOOGLE_CLOUD_API_KEY        modo "express". Si está presente, se usa esta
                                 (autenticación por API key, sin proyecto ni
                                 credenciales de service account).
    GOOGLE_CLOUD_PROJECT        modo estándar (OAuth2 / ADC). Obligatoria si
                                 no hay `GOOGLE_CLOUD_API_KEY`.
    GOOGLE_CLOUD_LOCATION       opcional, sólo aplica al modo estándar.
                                 Default "global".
    GOOGLE_MODEL                opcional, default "gemini-2.0-flash-001".
    GOOGLE_APPLICATION_CREDENTIALS   estándar de Google (ruta a un JSON de
                                 service account), sólo relevante en modo
                                 estándar. No se lee acá directamente: el SDK
                                 delega en `google.auth.default()`, que ya la
                                 respeta sola. En Cloud Run no hace falta —
                                 usa la cuenta de servicio adjunta al servicio.

Al menos una de `GOOGLE_CLOUD_API_KEY` / `GOOGLE_CLOUD_PROJECT` es
obligatoria.

**Por qué el SDK y no REST a mano (como en una versión anterior de este
archivo):** Vertex AI tiene dos formas de autenticarse, y cada una resuelve a
una URL distinta (una lleva `projects/.../locations/...`, la otra no; y
`location="global"` no sigue el patrón `{location}-aiplatform...` de las
regiones). Construir esa URL a mano es frágil y es exactamente el tipo de
detalle que el SDK ya resuelve — mezclar API key con la URL de proyecto da
`401 UNAUTHENTICATED`. Dejamos que `genai.Client` elija la URL correcta según
qué credencial le pasamos, igual que en cualquier otro proveedor de este
paquete: el punto de la abstracción es no reinventar eso.

El SDK se importa dentro de `__init__`, no en el tope del módulo: este
proveedor sólo se toca si `LLM_PROVIDER=google`, y si `google-genai` no está
instalado (es un extra: `uv sync --extra google`) la app entera arranca igual.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from app.llm.contracts import LLMProvider, StructuredCompletionRequest, StructuredCompletionResult
from app.llm.errors import LLMConfigError, LLMOutputError, LLMRequestError

PROVIDER_NAME = "google"
DEFAULT_LOCATION = "global"
DEFAULT_MODEL = "gemini-2.0-flash-001"

# JSON Schema (lo que genera Pydantic) -> tipos que acepta `response_schema`
# de Gemini (subconjunto de OpenAPI 3.0).
_TYPE_MAP = {
    "object": "OBJECT",
    "string": "STRING",
    "integer": "INTEGER",
    "number": "NUMBER",
    "boolean": "BOOLEAN",
    "array": "ARRAY",
}


class GoogleVertexProvider(LLMProvider):
    name = PROVIDER_NAME

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        project: str | None = None,
        location: str = DEFAULT_LOCATION,
    ) -> None:
        try:
            from google import genai
            from google.genai import types
            from google.genai.errors import APIError
        except ImportError as exc:
            raise LLMConfigError(
                "El paquete 'google-genai' no está instalado. Instalá el extra con "
                "`uv sync --extra google` para usar LLM_PROVIDER=google."
            ) from exc

        # Modo express (api_key) vs. modo estándar (project + location con
        # OAuth2/ADC) — el SDK arma la URL y la autenticación correctas según
        # cuál de los dos le pasemos; nunca se mezclan.
        if api_key:
            self._client = genai.Client(vertexai=True, api_key=api_key)
        else:
            self._client = genai.Client(vertexai=True, project=project, location=location)

        self._types = types
        self._api_error = APIError
        self._model = model

    def complete_structured(self, request: StructuredCompletionRequest) -> StructuredCompletionResult:
        config = self._types.GenerateContentConfig(
            system_instruction=request.system_prompt,
            response_mime_type="application/json",
            response_schema=_to_gemini_schema(request.json_schema),
            max_output_tokens=request.max_tokens,
        )
        # Este proveedor no implementa el context caching explícito de Vertex
        # AI (requiere un paso aparte para crear el cache): `cacheable_prefix`
        # simplemente se antepone al contenido, igual que en OpenRouter.
        contents = request.user_message
        if request.cacheable_prefix:
            contents = f"{request.cacheable_prefix}\n\n{request.user_message}"

        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=contents,
                config=config,
            )
        except self._api_error as exc:
            raise LLMRequestError(f"Vertex AI ({self._model}) falló: {exc}") from exc
        except Exception as exc:  # credenciales/ADC: no hay un tipo único
            raise LLMRequestError(
                f"No se pudo llamar a Vertex AI ({self._model}): {exc}. En local, "
                "configurá GOOGLE_CLOUD_API_KEY o GOOGLE_APPLICATION_CREDENTIALS; en "
                "Cloud Run, la cuenta de servicio necesita el rol de Vertex AI User."
            ) from exc

        text = response.text
        if not text:
            raise LLMOutputError(f"Vertex AI ({self._model}) no devolvió contenido.")

        try:
            data: dict[str, Any] = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMOutputError(
                f"Vertex AI ({self._model}) no devolvió JSON estructurado válido: {exc}"
            ) from exc

        return StructuredCompletionResult(data=data, provider=self.name, model=self._model)


def _to_gemini_schema(schema: dict[str, Any], defs: dict[str, Any] | None = None) -> dict[str, Any]:
    """Convierte un JSON Schema (el que genera `model_json_schema()` de
    Pydantic) al subconjunto de OpenAPI 3.0 que exige `response_schema` de
    Gemini: sin `$ref`/`$defs` (se resuelven inline), tipos en mayúsculas,
    `anyOf: [X, null]` (los `Optional[X]` de Pydantic) -> `nullable: true`.

    Best-effort deliberado: cubre lo que necesita el contrato de
    `MissionPlan` (objetos anidados, arrays, enums, opcionales, dicts libres).
    No es un conversor de JSON Schema genérico — una unión real de tipos no
    nulos (poco común en este contrato) se aproxima con la primera rama.
    """
    defs = defs if defs is not None else schema.get("$defs", {})

    if "$ref" in schema:
        key = schema["$ref"].rsplit("/", 1)[-1]
        return _to_gemini_schema(defs[key], defs)

    if "anyOf" in schema:
        branches = [b for b in schema["anyOf"] if b.get("type") != "null"]
        nullable = len(branches) != len(schema["anyOf"])
        converted = _to_gemini_schema(branches[0], defs) if branches else {"type": "STRING"}
        if nullable:
            converted["nullable"] = True
        return converted

    if "enum" in schema:
        return {"type": "STRING", "enum": list(schema["enum"])}

    json_type = schema.get("type")

    if json_type == "object":
        result: dict[str, Any] = {"type": "OBJECT"}
        properties = schema.get("properties")
        if properties:
            result["properties"] = {
                prop_name: _to_gemini_schema(prop_schema, defs)
                for prop_name, prop_schema in properties.items()
            }
            if schema.get("required"):
                result["required"] = list(schema["required"])
        return result

    if json_type == "array":
        items = schema.get("items")
        return {"type": "ARRAY", "items": _to_gemini_schema(items, defs) if items else {"type": "STRING"}}

    result = {"type": _TYPE_MAP.get(json_type, "STRING")}
    if schema.get("description"):
        result["description"] = schema["description"]
    return result


def create_provider(env: Mapping[str, str]) -> GoogleVertexProvider:
    api_key = env.get("GOOGLE_CLOUD_API_KEY")
    project = env.get("GOOGLE_CLOUD_PROJECT")
    if not api_key and not project:
        raise LLMConfigError(
            "Falta GOOGLE_CLOUD_API_KEY (modo express) o GOOGLE_CLOUD_PROJECT "
            "(modo OAuth2/ADC). Al menos una es obligatoria para LLM_PROVIDER=google."
        )

    return GoogleVertexProvider(
        model=env.get("GOOGLE_MODEL") or DEFAULT_MODEL,
        api_key=api_key,
        project=project,
        location=env.get("GOOGLE_CLOUD_LOCATION") or DEFAULT_LOCATION,
    )
