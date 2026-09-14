"""`LLMRouter`: resuelve qué chat model usa cada rol del grafo, en qué nivel.

Un "rol" es el nombre lógico de quien llama (`"orchestrator"`, `"reviewer"`,
`"planner"`, `"history_researcher"`, `"disambiguator"` en este proyecto,
aunque el router no conoce esa lista — cualquier string sirve). El nivel
(`ModelTier`) es la palanca que el orquestador mueve turno a turno: todos los
roles arrancan en `STANDARD`; el revisor puede pedir que UN rol puntual use
`REASONING` sólo para el siguiente intento (ver `graph/nodes/orchestrator.py`).

Cachea instancias por `(role, tier)`: construir un `ChatAnthropic` abre
conexión HTTP perezosamente, así que vale la pena no reconstruirlo en cada
nodo/turno.
"""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel

from app.agent.config import AgentSettings
from app.agent.llm.providers import build_chat_model
from app.agent.llm.tiers import ModelTier


class LLMRouter:
    def __init__(self, settings: AgentSettings) -> None:
        self._settings = settings
        self._cache: dict[tuple[str, ModelTier], BaseChatModel] = {}

    def _resolve(self, role: str, tier: ModelTier) -> tuple[str, str]:
        """(provider, model) para `role`/`tier`, aplicando `AGENT_LLM_ROLE_OVERRIDES`
        si ese rol tiene una entrada; si no, los defaults globales."""
        overrides = self._settings.llm_role_overrides.get(role, {})
        provider = overrides.get("provider", self._settings.llm_provider)
        default_model = (
            self._settings.llm_standard_model
            if tier is ModelTier.STANDARD
            else self._settings.llm_reasoning_model
        )
        model = overrides.get(tier.value, default_model)
        return provider, model

    def get(self, role: str, tier: ModelTier = ModelTier.STANDARD) -> BaseChatModel:
        key = (role, tier)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        provider, model = self._resolve(role, tier)
        chat_model = build_chat_model(provider, model)
        self._cache[key] = chat_model
        return chat_model

    def model_name(self, role: str, tier: ModelTier = ModelTier.STANDARD) -> str:
        """Sólo el nombre del modelo, para `AgentTrace.models_used` -- no
        construye nada."""
        return self._resolve(role, tier)[1]
