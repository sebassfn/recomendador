"""Fábrica de proveedores LLM: `LLM_PROVIDER` -> instancia de `LLMProvider`.

Selecciona e importa el módulo del proveedor de forma perezosa (`importlib`),
nunca en el import de este archivo ni de `app.llm` en general. Es lo que
garantiza que un proveedor no usado —ni su SDK, ni sus credenciales— nunca se
toca: con `LLM_PROVIDER=anthropic`, el módulo de Google ni se importa, y si
`google-auth` no está instalado la app arranca igual.

**Agregar un proveedor nuevo**, sin tocar nada de lo que ya funciona:
1. Un módulo en `app.llm.providers` con una clase que implemente `LLMProvider`
   y una función `create_provider(env: Mapping[str, str]) -> LLMProvider` que
   lea las variables de entorno propias de ese proveedor y levante
   `LLMConfigError` si falta alguna obligatoria.
2. Una línea en `_PROVIDER_MODULES` de este archivo.
Nada más cambia: ni `app.llm.citation`, ni `app.web.routes`.
"""

from __future__ import annotations

import importlib
import logging
import os
from typing import Mapping

from app.llm.contracts import LLMProvider
from app.llm.errors import LLMConfigError

logger = logging.getLogger(__name__)

ENV_VAR = "LLM_PROVIDER"
DEFAULT_PROVIDER = "openrouter"

# proveedor (valor de LLM_PROVIDER) -> módulo que lo implementa.
_PROVIDER_MODULES: dict[str, str] = {
    "anthropic": "app.llm.providers.anthropic_provider",
    "openrouter": "app.llm.providers.openrouter_provider",
    "google": "app.llm.providers.google_provider",
}

_provider_singleton: LLMProvider | None = None
_provider_singleton_key: tuple[str, ...] | None = None


def build_provider(env: Mapping[str, str] | None = None) -> LLMProvider:
    """Lee `LLM_PROVIDER` (default `anthropic`) e instancia ese proveedor.

    Levanta `LLMConfigError` si el nombre no está registrado, o si al
    proveedor elegido le falta configuración obligatoria (delegado a
    `create_provider` de cada módulo). Nunca devuelve `None`: quien quiera
    degradar sin excepción usa `get_provider_safe`.
    """
    env = env if env is not None else os.environ
    name = (env.get(ENV_VAR) or DEFAULT_PROVIDER).strip().lower()

    module_path = _PROVIDER_MODULES.get(name)
    if module_path is None:
        available = ", ".join(sorted(_PROVIDER_MODULES))
        raise LLMConfigError(
            f"{ENV_VAR}={name!r} no es un proveedor soportado. Disponibles: {available}."
        )

    module = importlib.import_module(module_path)
    return module.create_provider(env)


def get_provider() -> LLMProvider:
    """`build_provider` cacheado: un proceso construye cada proveedor una
    sola vez (evita reabrir un cliente HTTP/SDK por request). El caché se
    invalida solo si `LLM_PROVIDER` cambia en caliente (útil en tests);
    `reset_provider_cache` lo fuerza explícitamente.
    """
    global _provider_singleton, _provider_singleton_key

    cache_key = (os.environ.get(ENV_VAR, DEFAULT_PROVIDER),)
    if _provider_singleton is None or _provider_singleton_key != cache_key:
        _provider_singleton = build_provider()
        _provider_singleton_key = cache_key
    return _provider_singleton


def get_provider_safe() -> LLMProvider | None:
    """Versión de `get_provider` que nunca levanta: `None` si la
    configuración falta o es inválida. Es la dependencia de FastAPI
    (`Depends(get_provider_safe)`) y lo que usa `interpret_mission` cuando no
    se le inyecta un proveedor explícito — en ambos casos, un LLM mal
    configurado debe degradar a `keyword_fallback`, nunca tumbar la request.

    El fallo se cachea igual que el éxito (misma `cache_key`): sin esto, cada
    request sin credenciales reintentaría construir el proveedor y volvería a
    loguear la misma `LLMConfigError`.
    """
    global _provider_singleton, _provider_singleton_key

    cache_key = (os.environ.get(ENV_VAR, DEFAULT_PROVIDER),)
    if _provider_singleton_key == cache_key:
        return _provider_singleton

    try:
        provider: LLMProvider | None = build_provider()
    except LLMConfigError as exc:
        logger.warning("Proveedor LLM mal configurado (%s); se usará keyword_fallback.", exc)
        provider = None

    _provider_singleton = provider
    _provider_singleton_key = cache_key
    return provider


def reset_provider_cache() -> None:
    """Sólo para tests: fuerza a reconstruir el proveedor en la próxima
    llamada a `get_provider`/`get_provider_safe` (p. ej. tras cambiar
    variables de entorno con `monkeypatch`).
    """
    global _provider_singleton, _provider_singleton_key
    _provider_singleton = None
    _provider_singleton_key = None
