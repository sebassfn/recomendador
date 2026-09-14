"""Registro de sesiones en memoria (doc 03 §10.4)."""

from __future__ import annotations

from app.domain.schema import MissionPlan
from app.presentation.cart import CartState
from app.web import session as sessions
from tests.test_projector import basket


def _session(mid: str) -> sessions.MissionSession:
    b = basket()
    return sessions.MissionSession(
        mission_id=mid, mission=b.mission, basket=b, cart=CartState(), agent_session_id=mid, user_id="u-test"
    )


def test_ttl_expira_con_reloj_inyectado():
    sessions.clear()
    s = _session("m1")
    sessions.put(s)
    assert sessions.get("m1", now=s.last_seen + 10) is s
    assert sessions.get("m1", now=s.last_seen + 10 + sessions.TTL_SECONDS + 1) is None


def test_id_de_semilla_es_recuperable_y_no_colisiona():
    text = next(iter(sessions.SEED_TEXT_BY_STEM.values()))
    plan = MissionPlan(raw_input=text, interpreted_by="cached_seed")
    a, b = sessions.new_mission_id(plan), sessions.new_mission_id(plan)
    assert a != b  # dos personas con la misma semilla no comparten carrito
    assert sessions.seed_text_for(a) == text


def test_id_opaco_no_es_recuperable():
    plan = MissionPlan(raw_input="algo libre", interpreted_by="llm")
    assert sessions.seed_text_for(sessions.new_mission_id(plan)) is None
