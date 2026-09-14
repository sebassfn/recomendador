"""Registro perezoso de proveedores de chat model, uno por SDK.

Mismo patrón que `app.llm.factory` del proyecto anfitrión (y a propósito: es
un patrón que se repite bien) — el módulo de un proveedor sólo se importa
cuando `AGENT_LLM_PROVIDER` lo pide, así que un despliegue con
`AGENT_LLM_PROVIDER=anthropic` nunca necesita `langchain-google-genai`
instalado.

`max_retries=0` en todos los clientes es deliberado: los reintentos ante
errores transitorios los maneja el `RetryPolicy` del NODO del grafo
(`graph/policies.py`), no el SDK por debajo — así hay un solo lugar que
decide cuántas veces reintentar y con qué backoff, y `app.agent.llm.errors`
ve la excepción original en vez de una ya consumida por un retry interno.
"""

from __future__ import annotations

import os
from typing import Protocol

from langchain_core.language_models import BaseChatModel


class _ProviderFactory(Protocol):
    def __call__(self, *, model: str) -> BaseChatModel: ...


def _anthropic_factory(*, model: str) -> BaseChatModel:
    from langchain_anthropic import ChatAnthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("Falta ANTHROPIC_API_KEY para AGENT_LLM_PROVIDER=anthropic.")
    return ChatAnthropic(model=model, api_key=api_key, max_retries=0, max_tokens=4096)


def _google_factory(*, model: str) -> BaseChatModel:
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError as exc:  # pragma: no cover - depende de un extra opcional
        raise ImportError(
            "langchain-google-genai no está instalado. Es un extra opcional "
            "(`uv sync --extra agent-google`) para AGENT_LLM_PROVIDER=google."
        ) from exc

    api_key = os.environ.get("GOOGLE_CLOUD_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("Falta GOOGLE_CLOUD_API_KEY/GOOGLE_API_KEY para AGENT_LLM_PROVIDER=google.")
    return ChatGoogleGenerativeAI(model=model, google_api_key=api_key, max_retries=0)


def _openrouter_factory(*, model: str) -> BaseChatModel:
    """OpenRouter expone una API compatible con OpenAI, así que se instancia
    con `ChatOpenAI` apuntando a su `base_url` -- no existe un SDK propio de
    LangChain para OpenRouter. `model` viaja con el prefijo que OpenRouter
    espera (p. ej. `anthropic/claude-sonnet-5`), tal como llega de
    `AGENT_LLM_STANDARD_MODEL`/`AGENT_LLM_REASONING_MODEL`."""
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:  # pragma: no cover - depende de un extra opcional
        raise ImportError(
            "langchain-openai no está instalado. Es un extra opcional "
            "(`uv sync --extra agent-openrouter`) para AGENT_LLM_PROVIDER=openrouter."
        ) from exc

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("Falta OPENROUTER_API_KEY para AGENT_LLM_PROVIDER=openrouter.")
    base_url = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    return ChatOpenAI(model=model, api_key=api_key, base_url=base_url, max_retries=0)


_FACTORIES: dict[str, _ProviderFactory] = {
    "anthropic": _anthropic_factory,
    "google": _google_factory,
    "openrouter": _openrouter_factory,
}


def build_chat_model(provider: str, model: str) -> BaseChatModel:
    factory = _FACTORIES.get(provider)
    if factory is None:
        raise ValueError(f"AGENT_LLM_PROVIDER={provider!r} no está soportado. Disponibles: {sorted(_FACTORIES)}.")
    return factory(model=model)
