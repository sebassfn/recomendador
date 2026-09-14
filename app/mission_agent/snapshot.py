"""Snapshot neutral de una `MissionSession`: lo único que el agente puede
llevarse a memoria de largo plazo (checkpointeado por `app/agent/`) y lo
único que el subagente investigador de historial puede leer de sesiones
pasadas.

**Nunca precios ni montos** (CLAUDE.md regla 6: el agente no ve precios) --
sólo la forma de la necesidad y nombres de producto, que es lo que hace falta
para que una sesión futura pueda decir "la vez pasada compraste X". Categoría
y título sí importan para que el investigador de historial pueda decidir
rápido, sin tener que leer el detalle, si una sesión vieja es relevante.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.web.session import MissionSession


def _product_name(session: "MissionSession", product_id: str) -> str | None:
    for resolved_slot in session.basket.slots:
        candidates = ([resolved_slot.picked] if resolved_slot.picked else []) + list(resolved_slot.alternatives)
        for scored in candidates:
            if scored.product.product_id == product_id:
                return scored.product.name
    return None


def build_snapshot(session: "MissionSession") -> dict[str, Any]:
    """Se llama al cierre de cada turno (`advisor_service`) y viaja como
    `AgentRequest.snapshot` en el turno SIGUIENTE de la misma sesión, y queda
    checkpointeado para que otra sesión del mismo usuario lo lea después."""
    product_names = sorted(
        {name for line in session.cart.lines if (name := _product_name(session, line.product_id))}
    )
    return {
        "mission_title": session.mission.title,
        "mission_kind": session.mission.mission_kind.value,
        "categories": sorted({c.value for c in session.mission.spanned_categories}),
        "needs": [s.label for s in session.mission.slots],
        "product_names": product_names,
    }


def summarize_snapshot(snapshot: dict[str, Any]) -> str:
    """`AgentDomain.summarize_snapshot`: una línea legible, usada tanto para
    el `thread_summary` que ve `list_sessions` como para lo que el subagente
    investigador de historial recibe de `get_session_digest`."""
    title = snapshot.get("mission_title") or "Misión sin título"
    needs = ", ".join(snapshot.get("needs", [])) or "sin necesidades registradas"
    products = ", ".join(snapshot.get("product_names", [])) or "sin productos en el carrito"
    return f"{title} -- necesidades: {needs}. Carrito: {products}."
