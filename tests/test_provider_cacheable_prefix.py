"""Tests de `StructuredCompletionRequest.cacheable_prefix` por proveedor.

`app.llm.citation` (Tramo A, doc 01 §8.3) depende de que al menos un
proveedor traduzca `cacheable_prefix` a caché real (`AnthropicProvider`, con
`cache_control: ephemeral`); el resto debe seguir produciendo una llamada
válida aunque no cachee nada. Este archivo prueba esa traducción en cada
proveedor, con dobles que no tocan la red.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.llm.contracts import StructuredCompletionRequest
from app.llm.providers.anthropic_provider import AnthropicProvider
from app.llm.providers.openrouter_provider import OpenRouterProvider

_REQUEST_WITH_PREFIX = StructuredCompletionRequest(
    system_prompt="sistema",
    user_message="necesidad a respaldar",
    cacheable_prefix="corpus completo de documentos",
    schema_name="emitir_cita",
    schema_description="descripcion",
    json_schema={"type": "object", "properties": {}},
)

_REQUEST_WITHOUT_PREFIX = StructuredCompletionRequest(
    system_prompt="sistema",
    user_message="texto libre",
    schema_name="emitir_cita",
    schema_description="descripcion",
    json_schema={"type": "object", "properties": {}},
)


# ---------------------------------------------------------------------------
# Anthropic: cacheable_prefix -> bloque con cache_control ephemeral real
# ---------------------------------------------------------------------------


class _FakeToolUseBlock:
    type = "tool_use"

    def __init__(self, input_data: dict) -> None:
        self.input = input_data


class _FakeAnthropicResponse:
    def __init__(self, input_data: dict) -> None:
        self.content = [_FakeToolUseBlock(input_data)]


class _FakeAnthropicMessages:
    def __init__(self) -> None:
        self.last_call_kwargs: dict[str, Any] | None = None

    def create(self, **kwargs: Any) -> _FakeAnthropicResponse:
        self.last_call_kwargs = kwargs
        return _FakeAnthropicResponse({"found": False})


class _FakeAnthropicClient:
    def __init__(self) -> None:
        self.messages = _FakeAnthropicMessages()


def test_anthropic_cacheable_prefix_becomes_ephemeral_cache_block() -> None:
    fake_client = _FakeAnthropicClient()
    provider = AnthropicProvider(api_key="sk-test", model="claude-opus-5", client=fake_client)

    provider.complete_structured(_REQUEST_WITH_PREFIX)

    content = fake_client.messages.last_call_kwargs["messages"][0]["content"]
    assert isinstance(content, list)
    assert content[0]["text"] == "corpus completo de documentos"
    assert content[0]["cache_control"] == {"type": "ephemeral"}
    assert content[1] == {"type": "text", "text": "necesidad a respaldar"}


def test_anthropic_without_cacheable_prefix_sends_plain_string_content() -> None:
    fake_client = _FakeAnthropicClient()
    provider = AnthropicProvider(api_key="sk-test", model="claude-opus-5", client=fake_client)

    provider.complete_structured(_REQUEST_WITHOUT_PREFIX)

    content = fake_client.messages.last_call_kwargs["messages"][0]["content"]
    assert content == "texto libre"


# ---------------------------------------------------------------------------
# OpenRouter: sin cache_control nativo -> el prefijo se antepone al mensaje
# ---------------------------------------------------------------------------


def test_openrouter_folds_cacheable_prefix_into_user_message(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = OpenRouterProvider(api_key="or-test", model="openai/gpt-4o-mini")
    captured: dict[str, Any] = {}

    def fake_post(self: OpenRouterProvider, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        captured["payload"] = payload
        return {"choices": [{"message": {"tool_calls": [{"function": {"arguments": "{}"}}]}}]}

    monkeypatch.setattr(OpenRouterProvider, "_post", fake_post)

    provider.complete_structured(_REQUEST_WITH_PREFIX)

    user_message = captured["payload"]["messages"][1]
    assert user_message["role"] == "user"
    assert user_message["content"] == "corpus completo de documentos\n\nnecesidad a respaldar"


def test_openrouter_without_cacheable_prefix_sends_plain_user_message(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = OpenRouterProvider(api_key="or-test", model="openai/gpt-4o-mini")
    captured: dict[str, Any] = {}

    def fake_post(self: OpenRouterProvider, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        captured["payload"] = payload
        return {"choices": [{"message": {"tool_calls": [{"function": {"arguments": "{}"}}]}}]}

    monkeypatch.setattr(OpenRouterProvider, "_post", fake_post)

    provider.complete_structured(_REQUEST_WITHOUT_PREFIX)

    assert captured["payload"]["messages"][1]["content"] == "texto libre"
