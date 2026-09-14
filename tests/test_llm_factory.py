"""Tests de la fábrica de proveedores LLM (app/llm/factory.py) y del
contrato de intercambiabilidad: cada proveedor valida su propia
configuración y levanta `LLMConfigError` con un mensaje claro, sin tocar
ningún SDK opcional que no esté instalado.
"""

from __future__ import annotations

import pytest

from app.llm.errors import LLMConfigError
from app.llm.factory import build_provider, get_provider_safe, reset_provider_cache


def test_unsupported_provider_lists_available_names() -> None:
    with pytest.raises(LLMConfigError, match="anthropic"):
        build_provider({"LLM_PROVIDER": "made_up_provider"})


def test_default_provider_is_openrouter_when_unset() -> None:
    with pytest.raises(LLMConfigError, match="OPENROUTER_API_KEY"):
        build_provider({})


def test_anthropic_requires_api_key() -> None:
    with pytest.raises(LLMConfigError, match="ANTHROPIC_API_KEY"):
        build_provider({"LLM_PROVIDER": "anthropic"})


def test_anthropic_builds_with_key() -> None:
    provider = build_provider({"LLM_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "sk-test"})
    assert provider.name == "anthropic"


def test_openrouter_requires_api_key() -> None:
    with pytest.raises(LLMConfigError, match="OPENROUTER_API_KEY"):
        build_provider({"LLM_PROVIDER": "openrouter"})


def test_openrouter_builds_with_key_and_defaults() -> None:
    provider = build_provider({"LLM_PROVIDER": "openrouter", "OPENROUTER_API_KEY": "or-test"})
    assert provider.name == "openrouter"


def test_google_requires_api_key_or_project() -> None:
    with pytest.raises(LLMConfigError, match="GOOGLE_CLOUD_API_KEY"):
        build_provider({"LLM_PROVIDER": "google"})


@pytest.mark.parametrize(
    "env",
    [
        {"LLM_PROVIDER": "google", "GOOGLE_CLOUD_PROJECT": "some-project"},
        {"LLM_PROVIDER": "google", "GOOGLE_CLOUD_API_KEY": "test-key"},
    ],
    ids=["project-mode", "api-key-mode"],
)
def test_google_without_optional_extra_gives_clear_error(env: dict[str, str]) -> None:
    # google-genai no está instalado por defecto (es un extra:
    # pyproject.toml [project.optional-dependencies] google). Esto confirma
    # que el proveedor no usado no impide construir la fábrica ni la app,
    # tanto en modo estándar (project) como en modo express (api_key).
    with pytest.raises(LLMConfigError, match="uv sync --extra google"):
        build_provider(env)


def test_get_provider_safe_degrades_instead_of_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    reset_provider_cache()

    assert get_provider_safe() is None
    reset_provider_cache()
