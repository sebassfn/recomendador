"""Esquemas internos del grafo: lo que el orquestador y el revisor emiten
como salida estructurada. Viven acá (no en `contracts.py`) porque son
vocabulario INTERNO del mecanismo LangGraph — el mundo exterior nunca los ve,
sólo el `AgentResponse` final que `nodes/finalize.py` arma a partir de ellos.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from app.agent.llm.tiers import ModelTier


class SubagentName(str, Enum):
    HISTORY_RESEARCHER = "history_researcher"
    DISAMBIGUATOR = "disambiguator"
    PLANNER = "planner"


class SubagentTask(BaseModel):
    """Una instrucción concreta que el orquestador le da a un subagente para
    ESTE ciclo. `instruction` es texto libre. El ruteo agrega conversación y
    plan previo para desambiguador y planificador; ningún subagente recibe
    el estado completo del grafo."""

    subagent: SubagentName
    instruction: str = Field(description="Qué debe averiguar o resolver este subagente, en sus palabras.")


class OrchestratorDecision(BaseModel):
    """Salida del nodo `orchestrator`. `next` es la única señal que
    `graph/routing.py` usa para decidir la próxima arista — el resto es
    contexto para logging/trazabilidad."""

    next: str = Field(description="Uno de: 'investigate', 'plan', 'finish'.")
    tasks: list[SubagentTask] = Field(
        default_factory=list,
        description="Sub-tareas a despachar EN PARALELO. Sólo tiene sentido con next='investigate' "
        "(history_researcher y/o disambiguator) o next='plan' (planner, típicamente una sola tarea).",
    )
    rationale: str = Field(default="", description="Por qué esta decisión, en una frase — para trazabilidad.")


class ReviewIssue(BaseModel):
    """Veredicto del revisor sobre UN subagente que corrió este ciclo."""

    subagent: SubagentName
    ok: bool
    feedback: str = Field(
        default="",
        description="Si ok=False: qué está mal y qué debería hacer distinto el orquestador al "
        "reformular la instrucción. Vacío si ok=True.",
    )
    escalate: bool = Field(
        default=False,
        description="True si el problema parece un límite de razonamiento del modelo estándar, "
        "no de la instrucción -- el orquestador debe reintentar ese subagente en nivel REASONING.",
    )


class ReviewVerdict(BaseModel):
    """Salida del nodo `reviewer`. `ready_to_finish` es la única señal de
    ruteo; `issues` es lo que el orquestador usa para reformular."""

    ready_to_finish: bool
    ambiguous: bool = Field(
        default=False,
        description="True si lo que falta no es un error de un subagente sino que el pedido del "
        "usuario sigue siendo ambiguo -- dispara clarificación humana, no re-planificación.",
    )
    issues: list[ReviewIssue] = Field(default_factory=list)
    summary: str = Field(default="", description="Una frase para el mensaje final al usuario.")
    clarification_question: str = Field(
        default="",
        description="Si ambiguous=True, pregunta directa al usuario por el dato imprescindible que falta. "
        "No un diagnóstico de ambigüedad. Vacío cuando se puede avanzar.",
    )


def tier_for(state_tier_overrides: dict[str, str], role: str) -> ModelTier:
    """Nivel efectivo de `role` para el turno actual. Sin override, STANDARD."""
    raw = state_tier_overrides.get(role)
    return ModelTier(raw) if raw else ModelTier.STANDARD
