"""Traducciones fijas de enums a lenguaje humano (doc 03 §3.2). Sin LLM: son
tablas, y viven acá para que las plantillas no embeban lógica de negocio."""

from __future__ import annotations

from app.domain.schema import (
    AvailabilityStatus,
    BusinessSignals,
    Currency,
    ExclusionReason,
    MissionKind,
    SignalSource,
)

EXCLUSION_REASON_LABELS: dict[ExclusionReason, str] = {
    ExclusionReason.OUT_OF_STOCK: "Sin stock en este momento",
    ExclusionReason.NOT_IN_SELECTED_STORE: "No disponible en la tienda seleccionada",
    ExclusionReason.OVER_BUDGET: "Excede el presupuesto asignado a este ítem",
    ExclusionReason.INCOMPATIBLE: "No compatible con el vehículo indicado",
    ExclusionReason.WRONG_CATEGORY: "No corresponde a esta necesidad",
    ExclusionReason.MISSING_REQUIRED_ATTRIBUTE: "Le falta un atributo que la necesidad exige",
    ExclusionReason.WRONG_REQUIRED_ATTRIBUTE_VALUE: "No es la talla/medida/tipo que la necesidad pide",
    ExclusionReason.DISCONTINUED: "Producto descontinuado",
    ExclusionReason.NO_PRICE: "Sin precio publicado",
    ExclusionReason.NO_TEXT_MATCH: "No coincide con lo que pidió el cliente",
}

AVAILABILITY_LABELS: dict[AvailabilityStatus, str] = {
    AvailabilityStatus.IN_STOCK: "En stock",
    AvailabilityStatus.LOW_STOCK: "Pocas unidades",
    AvailabilityStatus.OUT_OF_STOCK: "Sin stock",
    AvailabilityStatus.UNKNOWN: "Disponibilidad no verificada",
}

CATEGORY_LABELS: dict[str, str] = {
    "grocery": "Supermercado",
    "auto": "Autos",
    "home": "Hogar y almacenaje",
    "unknown": "Otros",
}

CATEGORY_ICON: dict[str, str] = {
    "grocery": "🛒",
    "auto": "🚗",
    "home": "🏠",
    "unknown": "📦",
}

# Placeholder CSS por categoría (doc 03 §10.3: sin imágenes externas).
CATEGORY_PLACEHOLDER_CLASS: dict[str, str] = {
    "grocery": "bg-emerald-100 text-emerald-800",
    "auto": "bg-blue-100 text-blue-800",
    "home": "bg-amber-100 text-amber-800",
    "unknown": "bg-slate-200 text-slate-700",
}


AVAILABILITY_CSS: dict[AvailabilityStatus, str] = {
    AvailabilityStatus.IN_STOCK: "bg-emerald-100 text-emerald-800",
    AvailabilityStatus.LOW_STOCK: "bg-amber-100 text-amber-800",
    AvailabilityStatus.OUT_OF_STOCK: "bg-red-100 text-red-800",
    AvailabilityStatus.UNKNOWN: "bg-slate-200 text-slate-600",
}

CATEGORY_SUBTITLE: dict[str, str] = {
    "grocery": "Alimentos, bebidas y cuidado personal.",
    "auto": "Para el cuidado y mantenimiento de tu vehículo.",
    "home": "Para equipar y organizar tu hogar.",
    "unknown": "Otros productos para tu misión.",
}

# Fondo suave de cada grupo de recomendación, como en el mockup.
CATEGORY_GROUP_CSS: dict[str, str] = {
    "grocery": "bg-emerald-50/60 border-emerald-100",
    "auto": "bg-blue-50/60 border-blue-100",
    "home": "bg-amber-50/60 border-amber-100",
    "unknown": "bg-slate-50 border-slate-200",
}

CURRENCY_SYMBOL: dict[Currency, str] = {
    Currency.DOLLAR: "$",
    Currency.PEN: "S/",
    Currency.USD: "$",
    Currency.COP: "$",
    Currency.MXN: "$",
    Currency.CLP: "$",
}

MISSION_KIND_LABELS: dict[MissionKind, str] = {
    MissionKind.TRIP: "Viaje",
    MissionKind.VEHICLE_MAINTENANCE: "Mantenimiento del vehículo",
    MissionKind.HOME_SETUP: "Organizar el hogar",
    MissionKind.EVENT: "Evento o reunión",
    MissionKind.RESTOCK: "Compra de reposición",
    MissionKind.GENERIC: "Compra general",
}

# Rol de un producto dentro de su slot (derivado en el proyector, nunca por el
# LLM). Texto y CSS de la píldora del mockup.
ROLE_LABELS: dict[str, str] = {
    "essential": "Esencial",
    "recommended": "Recomendado",
    "cheapest": "Más económico",
    "complementary": "Complementario",
}

ROLE_CSS: dict[str, str] = {
    "essential": "bg-emerald-100 text-emerald-800",
    "recommended": "bg-green-100 text-green-800",
    "cheapest": "bg-sky-100 text-sky-800",
    "complementary": "bg-violet-100 text-violet-800",
}

# Razón de respaldo cuando el slot no trae `rationale`. Plantilla fija: habla de
# la misión, no del producto, y no la redacta nadie.
REASON_FROM_LABEL = "Cubre «{label}» de tu misión."

BADGE_SIMULATED = (
    "señal simulada",
    "bg-amber-100 text-amber-800",
    "Dato sintético: no viene del dataset, se generó para que la feature no muera.",
)
BADGE_DERIVED = (
    "estimado",
    "bg-slate-200 text-slate-600",
    "Calculada a partir de otros campos reales.",
)


def product_signal_badge(signals: BusinessSignals) -> str | None:
    """'simulated' | 'derived' | None, para el badge de ProductRow (doc 03
    §3.1, CLAUDE.md regla 4). SIMULATED manda sobre DERIVED si coexisten."""
    sources = [getattr(signals, name).source for name in signals.available_signals]
    if SignalSource.SIMULATED in sources:
        return "simulated"
    if SignalSource.DERIVED in sources:
        return "derived"
    return None
