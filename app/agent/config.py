"""Configuración del agente, leída de `.env` con el prefijo `AGENT_`.

Todo lo que el grafo necesita para correr vive acá — nada de variables de
entorno leídas sueltas en otros módulos. Reutiliza las credenciales de
proveedor que ya existen en el `.env` del proyecto anfitrión (p. ej.
`ANTHROPIC_API_KEY`), que son "de infraestructura", no del agente en sí; lo
que SÍ es de este módulo (qué modelo, qué backend de memoria, cuántos
reintentos) lleva prefijo `AGENT_`.
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

StoreBackend = Literal["memory", "firestore"]
LLMProviderName = Literal["anthropic", "google", "openrouter"]


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AGENT_",
        env_file=None,  # el anfitrión decide cómo cargar el .env (uv --env-file, etc.)
        extra="ignore",
    )

    # -- Persistencia de checkpoints -----------------------------------
    store_backend: StoreBackend = "memory"
    firestore_project: str | None = None
    firestore_database: str = "(default)"
    firestore_collection_prefix: str = "agent"

    # -- LLM --------------------------------------------------------------
    llm_provider: LLMProviderName = "anthropic"
    llm_standard_model: str = "claude-sonnet-5"
    llm_reasoning_model: str = "claude-opus-5"
    # JSON opcional: {"planner": {"standard": "...", "reasoning": "..."}, ...}
    # Permite, por ejemplo, que un subagente puntual use otro proveedor/modelo
    # sin tocar código.
    llm_role_overrides_raw: str | None = Field(default=None, alias="AGENT_LLM_ROLE_OVERRIDES")
    llm_max_retries: int = 0  # los reintentos los maneja RetryPolicy del grafo, no el SDK

    # -- Control de loop / HITL --------------------------------------------
    max_iterations: int = 3
    max_subagent_attempts: int = 2
    max_clarifications: int = 2
    recursion_limit: int = 40
    max_messages_in_state: int = 40

    # -- Reintentos de red (LLM y tools externas) --------------------------
    retry_max_attempts: int = 4
    retry_initial_interval: float = 0.5
    retry_backoff_factor: float = 2.0
    retry_max_interval: float = 20.0
    retry_after_cap: float = 30.0

    @field_validator("llm_role_overrides_raw")
    @classmethod
    def _validate_json(cls, value: str | None) -> str | None:
        if value:
            json.loads(value)  # levanta ValueError temprano si está mal formado
        return value

    @property
    def llm_role_overrides(self) -> dict[str, dict[str, str]]:
        if not self.llm_role_overrides_raw:
            return {}
        return json.loads(self.llm_role_overrides_raw)
