"""Puente de vuelta, catálogo -> agente, para slots obligatorios sin producto.

`app.engine.scoring` y `app.services.basket_service` ya deciden qué existe y
en qué orden (CLAUDE.md regla 6); esto no cambia. Lo único que se agrega acá
es una segunda oportunidad: si el filtro duro deterministic dejó un slot NO
opcional sin `picked`, se lo contamos al planner en texto libre -- sólo
`slot_id`, `label`, las keywords que el propio LLM ya había propuesto y el
motivo estructural del descarte (`ExclusionReason`, un enum) -- para que
proponga otras palabras o categoría. Nunca un producto, nunca un precio,
nunca el catálogo: eso seguiría violando la regla 1/6 si viajara.
"""

from __future__ import annotations

from app.domain.schema import Basket


def build_retry_hint(basket: Basket) -> str | None:
    """`None` si no hay nada que reintentar (todo resuelto, o lo que falta es
    opcional -- un acompañamiento sin match no amerita gastar un turno de
    agente)."""
    unresolved = [rs for rs in basket.slots if rs.is_unfulfilled and not rs.slot.is_optional]
    if not unresolved:
        return None

    lines = [
        "[instrucción interna, no es un mensaje del cliente] Estos slots obligatorios "
        "no encontraron ningún producto en el catálogo con las keywords actuales:"
    ]
    for rs in unresolved:
        reason = rs.most_common_rejection_reason.value if rs.most_common_rejection_reason else "sin_candidatos"
        lines.append(f"- slot_id={rs.slot.slot_id!r} label={rs.slot.label!r} keywords_probadas={rs.slot.keywords!r} motivo={reason}")
    lines.append(
        "Para esos slots, proponé keywords alternativas (sinónimos más genéricos, sin "
        "adjetivos raros) o un target_category distinto si corresponde. No cambies "
        "ningún otro slot ni ninguna otra parte del plan."
    )
    return "\n".join(lines)
