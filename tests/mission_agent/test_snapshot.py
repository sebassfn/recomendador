"""Snapshot neutral de una `MissionSession`: la única memoria de largo plazo
que el agente puede guardar (CLAUDE.md regla 6: nunca precios)."""

from __future__ import annotations

from app.mission_agent.snapshot import build_snapshot, summarize_snapshot
from app.presentation.cart import default_from_basket
from app.web.session import MissionSession
from tests.test_projector import basket, product, resolved, scored, slot


def _session() -> MissionSession:
    b = basket(
        resolved(slot("slot-sol", category="grocery"), scored(product("P1", "24.90"), 0.9)),
        mission_kind="trip",
        title="Viaje a la playa",
    )
    cart = default_from_basket(b)
    return MissionSession(
        mission_id="m1", mission=b.mission, basket=b, cart=cart, agent_session_id="a1", user_id="u1"
    )


def test_snapshot_has_no_prices_or_amounts() -> None:
    snapshot = build_snapshot(_session())
    serialized = str(snapshot)
    assert "24.90" not in serialized
    assert "amount" not in serialized


def test_snapshot_has_product_names_categories_and_needs() -> None:
    snapshot = build_snapshot(_session())
    assert snapshot["mission_title"] == "Viaje a la playa"
    assert snapshot["product_names"] == ["Producto P1"]
    assert snapshot["needs"] == ["Slot slot-sol"]
    assert snapshot["categories"] == ["grocery"]


def test_summarize_is_a_readable_line() -> None:
    text = summarize_snapshot(build_snapshot(_session()))
    assert "Viaje a la playa" in text
    assert "Producto P1" in text
