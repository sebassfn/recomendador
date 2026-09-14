"""Dobles de prueba para el módulo de agente.

`app.agent.llm.router.LLMRouter` sólo se usa por duck-typing (`.get(role,
tier)`, `.model_name(role, tier)`), así que un doble de test no necesita
heredar de nada de LangChain: alcanza con imitar `bind_tools`/
`with_structured_output` como los usa `subagents/base.py`.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage
from pydantic import BaseModel

from app.agent.contracts import AgentRequest
from app.agent.llm.tiers import ModelTier


class _ScriptedStructured:
    def __init__(self, queue: list[Any], calls: list[str], tag: str, inputs: list[Any]) -> None:
        self._queue = queue
        self._calls = calls
        self._tag = tag
        self._inputs = inputs

    async def ainvoke(self, messages: Any) -> Any:
        self._calls.append(self._tag)
        self._inputs.append(list(messages))
        if not self._queue:
            raise AssertionError(f"FakeChatModel[{self._tag}] se quedó sin respuestas guionadas")
        value = self._queue.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class FakeChatModel:
    """Un `BaseChatModel` de mentira para un (rol, tier) puntual.

    `structured_queue`: lista de instancias Pydantic (o `Exception` para
    simular una falla) que se devuelven EN ORDEN cada vez que algo llama
    `.with_structured_output(...).ainvoke(...)`, sin importar qué schema se
    pidió -- el test es responsable de encolar el tipo correcto.

    `tool_turns`: para subagentes que usan tools (`history_researcher`), la
    secuencia de `AIMessage` que devuelve el loop de tool-calling ANTES de la
    llamada final de salida estructurada. Vacío = sin tool calls, un solo
    mensaje final sin tools.
    """

    def __init__(self, tag: str) -> None:
        self.tag = tag
        self.structured_queue: list[Any] = []
        self.tool_turns: list[AIMessage] = []
        self.calls: list[str] = []
        self.inputs: list[Any] = []

    def bind_tools(self, tools: list[Any], **kwargs: Any) -> "FakeChatModel":
        return self

    async def ainvoke(self, messages: Any, **kwargs: Any) -> AIMessage:
        self.calls.append(f"{self.tag}:tool_turn")
        if self.tool_turns:
            return self.tool_turns.pop(0)
        return AIMessage(content="(sin más tool calls)", tool_calls=[])

    def with_structured_output(self, schema: type[BaseModel], **kwargs: Any) -> _ScriptedStructured:
        return _ScriptedStructured(self.structured_queue, self.calls, self.tag, self.inputs)


class FakeLLMRouter:
    """Un modelo fresco por `role` (no por `(role, tier)`): el mismo objeto
    contesta sin importar el tier, así el test puede inspeccionar
    `models[role].calls` para verificar CUÁNTAS veces se llamó, y guardar en
    el propio test qué tier se le pidió mirando `AgentRuntime`/el estado."""

    def __init__(self) -> None:
        self.models: dict[str, FakeChatModel] = {}
        self.requested_tiers: list[tuple[str, ModelTier]] = []

    def get(self, role: str, tier: ModelTier = ModelTier.STANDARD) -> FakeChatModel:
        self.requested_tiers.append((role, tier))
        return self.models.setdefault(role, FakeChatModel(role))

    def model_name(self, role: str, tier: ModelTier = ModelTier.STANDARD) -> str:
        return f"fake-{role}-{tier.value}"


class FakeOutput(BaseModel):
    """`output_model` de un dominio de prueba: no representa nada de negocio
    real, sólo necesita ser un `BaseModel` con algo que validar."""

    text: str
    confirmed: bool = False


class FakeDomain:
    """`AgentDomain` mínimo para tests que no necesitan semántica de negocio.
    Reutiliza los prompts de `retail_mission` (el planner de prueba ignora su
    contenido igual, `FakeChatModel` no lee prompts) para no tener que
    empaquetar prompts sólo-de-test dentro de `app/agent/prompts/`."""

    name = "fake"
    output_model = FakeOutput
    prompt_key = "retail_mission"

    def __init__(self, *, shortcut_hit: dict | None = None) -> None:
        self._shortcut_hit = shortcut_hit

    def shortcut(self, request: AgentRequest) -> dict | None:
        return self._shortcut_hit

    def fallback(self, request: AgentRequest) -> dict:
        return {"text": f"fallback:{request.message}", "confirmed": False}

    def summarize_snapshot(self, snapshot: dict) -> str:
        return str(snapshot)


def orchestrator_decision(next: str, tasks: list[dict] | None = None, rationale: str = "") -> dict:
    """Construye el dict crudo que el `_ScriptedStructured` de orchestrator
    debe devolver -- se valida como `OrchestratorDecision` dentro del nodo,
    así que alcanza con un dict con la forma correcta."""
    from app.agent.graph.schemas import OrchestratorDecision

    return OrchestratorDecision(next=next, tasks=tasks or [], rationale=rationale)
