"""El plugin de dominio: la única pieza que le enseña a `app/agent/` (genérico,
copiable) qué es una "misión de compra" de este retailer.

Reemplaza a `app/llm/interpreter.py`: el subagente `planner` de `app/agent/`
es ahora la única llamada a un LLM para interpretar la necesidad -- este
módulo sólo declara CÓMO ese subagente debe comportarse (`output_model`,
`prompt_key`) y los dos casos que no necesitan LLM en absoluto (`shortcut`,
`fallback`), exactamente como antes.
"""

from __future__ import annotations

from typing import Any

from app.agent.contracts import AgentMode, AgentRequest
from app.domain.schema import MissionPlanDraft
from app.mission_agent import keyword_fallback, seeds, snapshot


class RetailMissionDomain:
    """Implementa `app.agent.domain.AgentDomain` (Protocol -- no hace falta
    heredar, sólo tener esta forma)."""

    name = "retail_mission"
    output_model = MissionPlanDraft
    prompt_key = "retail_mission"

    def shortcut(self, request: AgentRequest) -> dict[str, Any] | None:
        return seeds.load_cached_seed(request.message)

    def fallback(self, request: AgentRequest) -> dict[str, Any]:
        if request.mode is AgentMode.REVISE and request.previous_output is not None:
            # Un ajuste que no se pudo interpretar de ninguna manera es
            # exactamente "no toqués nada" -- devolver un plan genérico
            # nuevo (ignorando el previo) sería peor que no cambiar nada.
            return request.previous_output
        return keyword_fallback.fallback_plan(request.message)

    def summarize_snapshot(self, snapshot_data: dict[str, Any]) -> str:
        return snapshot.summarize_snapshot(snapshot_data)
