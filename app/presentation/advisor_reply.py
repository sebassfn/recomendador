"""Respuesta conversacional fundada en lo que el catálogo pudo resolver.

No necesita un LLM con acceso a productos: nombra las opciones visibles y
explica faltantes sin convertir datos desconocidos en afirmaciones de stock.
"""

from __future__ import annotations

from app.domain.schema import Basket, ExclusionReason, ResolvedSlot
from app.domain.specifications import definition_for
from app.presentation.cart import pool_of
from app.web.copy import CATEGORY_LABELS


def _join(items: list[str]) -> str:
    if len(items) < 2:
        return "".join(items)
    return ", ".join(items[:-1]) + " y " + items[-1]


def _missing_reply(rs: ResolvedSlot) -> str:
    label = rs.slot.label[:1].lower() + rs.slot.label[1:]
    reason = rs.most_common_rejection_reason
    if reason is ExclusionReason.OUT_OF_STOCK:
        return f"Por ahora no tengo {label} en stock."
    if reason is ExclusionReason.MISSING_REQUIRED_ATTRIBUTE:
        if rs.slot.attribute_requirements:
            requirement = rs.slot.attribute_requirements[0]
            definition = definition_for(requirement.attribute)
            requested = f"{requirement.value} {requirement.unit or definition.unit or ''}".strip()
            return (
                f"No puedo confirmar qué opciones de {label} cumplen con {definition.label} "
                f"{requested}: falta esa información en el catálogo."
            )
        return f"No tengo información suficiente para confirmar qué opciones de {label} cumplen con lo que necesitas."
    if reason in (ExclusionReason.WRONG_REQUIRED_ATTRIBUTE_VALUE, ExclusionReason.INCOMPATIBLE):
        return f"No encontré opciones de {label} que se ajusten a los datos que me diste."
    if reason is ExclusionReason.OVER_BUDGET:
        return f"No encontré {label} dentro de tu presupuesto."
    if reason is ExclusionReason.NOT_IN_SELECTED_STORE:
        return f"Por ahora no tengo {label} disponibles en esa tienda."
    return f"Por ahora no tengo {label} disponibles en el catálogo."


def _brand_not_found_reply(rs: ResolvedSlot) -> str:
    label = rs.slot.label[:1].lower() + rs.slot.label[1:]
    return f"No encontré {_join(rs.slot.preferred_brands)} disponible para {label}; te muestro otras marcas."


def recommendation_reply(basket: Basket) -> str:
    by_category: dict[str, list[str]] = {}
    missing: list[str] = []
    for rs in basket.slots:
        if rs.is_unfulfilled:
            missing.append(_missing_reply(rs))
            continue
        if rs.preferred_brand_found is False:
            missing.append(_brand_not_found_reply(rs))
        count = len(pool_of(rs))
        label = rs.slot.label[:1].lower() + rs.slot.label[1:]
        description = f"{count} opciones de {label}" if count > 1 else label
        category = CATEGORY_LABELS[rs.slot.target_category.value]
        by_category.setdefault(category, []).append(description)
    available = [f"Te muestro {_join(items)} en {category}." for category, items in by_category.items()]
    return " ".join([*available, *missing]) or "No encontré productos para mostrarte con este pedido."
