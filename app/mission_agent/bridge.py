"""El único módulo que traduce entre el lenguaje de `app/agent/` (genérico:
`AgentRequest`/`AgentResponse`) y el de este proyecto (`MissionPlan`).
`app/services/advisor_service.py` habla con esto, nunca directo con
`AgentService` ni con `app.domain.schema.MissionPlanDraft`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.agent import (
    AgentMode,
    AgentRequest,
    AgentResponse,
    AgentService,
    AgentStatus,
    ClarificationAnswer,
    ClarificationRequest,
)
from app.domain.schema import MissionPlan, MissionPlanDraft
from app.mission_agent.attributes import normalize_requirements

# `AgentResponse.produced_by` -> `MissionPlan.interpreted_by` (mismo
# vocabulario que ya usaba `app/llm/interpreter.py`, así que
# `advisor_service.INTERPRETED_BY_DETAIL` no necesita cambiar).
_INTERPRETED_BY = {"shortcut": "cached_seed", "agent": "llm", "fallback": "keyword_fallback"}


@dataclass
class BridgeResult:
    status: AgentStatus
    agent_session_id: str
    plan: MissionPlan | None = None
    clarification: ClarificationRequest | None = None
    warnings: list[str] = field(default_factory=list)


def _draft_to_plan(raw_input: str, draft: dict, interpreted_by: str) -> MissionPlan:
    parsed = MissionPlanDraft.model_validate(draft)
    return normalize_requirements(MissionPlan(
        raw_input=raw_input,
        mission_kind=parsed.mission_kind,
        title=parsed.title,
        slots=parsed.slots,
        constraints=parsed.constraints,
        entities=parsed.entities,
        interpreted_by=interpreted_by,
    ))


def _plan_to_draft(plan: MissionPlan) -> dict:
    return MissionPlanDraft(
        mission_kind=plan.mission_kind,
        title=plan.title,
        slots=plan.slots,
        constraints=plan.constraints,
        entities=plan.entities,
    ).model_dump(mode="json")


def _to_result(raw_input: str, response: AgentResponse) -> BridgeResult:
    plan = None
    if response.output is not None:
        plan = _draft_to_plan(raw_input, response.output, _INTERPRETED_BY[response.produced_by])
    return BridgeResult(
        status=response.status,
        agent_session_id=response.session_id,
        plan=plan,
        clarification=response.clarification,
        warnings=list(response.trace.warnings),
    )


async def start_mission(agent: AgentService, text: str, *, user_id: str) -> BridgeResult:
    response = await agent.run(AgentRequest(user_id=user_id, message=text, mode=AgentMode.START))
    return _to_result(text, response)


async def revise_mission(
    agent: AgentService,
    *,
    user_id: str,
    agent_session_id: str,
    previous_plan: MissionPlan,
    text: str,
    snapshot: dict | None,
) -> BridgeResult:
    response = await agent.run(
        AgentRequest(
            user_id=user_id,
            session_id=agent_session_id,
            message=text,
            mode=AgentMode.REVISE,
            previous_output=_plan_to_draft(previous_plan),
            snapshot=snapshot,
        )
    )
    return _to_result(f"{previous_plan.raw_input}\n{text}", response)


async def resume_clarification(
    agent: AgentService,
    *,
    user_id: str,
    agent_session_id: str,
    raw_input: str,
    answer: ClarificationAnswer,
) -> BridgeResult:
    response = await agent.run(
        AgentRequest(
            user_id=user_id,
            session_id=agent_session_id,
            message="",
            mode=AgentMode.REVISE,
            resume=answer,
        )
    )
    clarified_input = f"{raw_input}\nAclaración: {answer.free_text}" if answer.free_text else raw_input
    return _to_result(clarified_input, response)
