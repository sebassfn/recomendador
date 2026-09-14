"""Orquesta un `MissionPlan` resuelto contra el catálogo: consulta SQL por
slot -> filtro duro + ranking (`app.engine.scoring`) -> `Basket`.

Ningún LLM ni HTTP acá: es la capa de negocio determinista (CLAUDE.md regla 6).
"""

from __future__ import annotations

import sqlite3
from collections import Counter

from app.domain.schema import (
    Basket,
    AvailabilityStatus,
    BasketSlot,
    MissionPlan,
    ResolvedSlot,
    ScoredProduct,
    ScoringWeights,
)
from app.engine.scoring import matches_slot_text, score_slot
from app.repositories.catalog_repository import candidates_for_category

MAX_ALTERNATIVES = 3
MAX_REJECTED = 3


def resolve_single_slot(
    conn: sqlite3.Connection, slot: BasketSlot, weights: ScoringWeights
) -> ResolvedSlot:
    candidates = [
        p for p in candidates_for_category(conn, slot.target_category) if matches_slot_text(p, slot)
    ]
    scored = score_slot(candidates, slot, weights)

    recommended = [sp for sp in scored if sp.is_recommended]
    rejected = [sp for sp in scored if not sp.is_recommended]

    picked: ScoredProduct | None = recommended[0] if recommended else None
    alternatives = recommended[1 : 1 + MAX_ALTERNATIVES]

    # Sobre TODOS los descartados, no sólo los `MAX_REJECTED` que se
    # muestran: `rejected[:3]` puede truncar antes de llegar al motivo que
    # realmente predomina (p. ej. 2 out_of_stock listados antes que 39
    # no_text_match, por orden de inserción del motor, no por frecuencia).
    # Si queda algún candidato con stock, el problema no es que TODO esté
    # agotado. Explicamos por qué no podemos ofrecer los que sí quedan.
    diagnostic_candidates = [sp for sp in rejected if sp.product.availability is not AvailabilityStatus.OUT_OF_STOCK] or rejected
    most_common_rejection_reason = (
        Counter(sp.excluded_reason for sp in diagnostic_candidates).most_common(1)[0][0] if diagnostic_candidates else None
    )

    return ResolvedSlot(
        slot=slot,
        picked=picked,
        alternatives=alternatives,
        rejected=rejected[:MAX_REJECTED],
        most_common_rejection_reason=most_common_rejection_reason,
    )


def resolve_mission(
    conn: sqlite3.Connection,
    mission: MissionPlan,
    weights: ScoringWeights | None = None,
) -> Basket:
    weights = weights or ScoringWeights()
    resolved_slots = [resolve_single_slot(conn, slot, weights) for slot in mission.slots]
    return Basket(mission=mission, slots=resolved_slots, weights=weights)
