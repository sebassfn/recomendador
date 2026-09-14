"""Fallback determinista sin red: keyword -> `MissionKind` -> plantilla de
slots pre-escrita. Es el `fallback` de `RetailMissionDomain` -- lo último que
se usa cuando el agente agota iteraciones o las credenciales del LLM fallan,
así que NUNCA puede fallar ni depender de nada externo.

Idéntico en espíritu al Tramo 3 que tenía `app/llm/interpreter.py`: cada
plantilla ya trae `keywords` expandidas con sinónimos (doc 01 §8.4 -- la
expansión de consulta se decide en el origen), mismo estándar que se le pide
al LLM en `prompts/domains/retail_mission/brief.md`.
"""

from __future__ import annotations

from typing import Any

from app.domain.schema import Category, MissionKind, MissionPlanDraft

_KEYWORD_TO_MISSION_KIND: list[tuple[tuple[str, ...], MissionKind]] = [
    (("playa", "feriado", "viaje", "vacaciones", "camping", "excursion"), MissionKind.TRIP),
    (
        ("carro", "auto", "vehiculo", "llanta", "llantas", "neumatico", "aceite", "mantenimiento", "yaris"),
        MissionKind.VEHICLE_MAINTENANCE,
    ),
    (("mudanza", "departamento", "depto", "organizar", "organizacion", "organizarlo"), MissionKind.HOME_SETUP),
    (("cumpleanos", "parrilla", "reunion", "fiesta", "celebracion"), MissionKind.EVENT),
    (("semanal", "despensa", "abastecer", "reponer", "quincena"), MissionKind.RESTOCK),
]

_FALLBACK_TITLES: dict[MissionKind, str] = {
    MissionKind.TRIP: "Viaje",
    MissionKind.VEHICLE_MAINTENANCE: "Mantenimiento del vehículo",
    MissionKind.HOME_SETUP: "Organización del hogar",
    MissionKind.EVENT: "Reunión",
    MissionKind.RESTOCK: "Compra semanal",
    MissionKind.GENERIC: "Misión de compra",
}

_FALLBACK_SLOT_TEMPLATES: dict[MissionKind, list[dict[str, Any]]] = {
    MissionKind.TRIP: [
        dict(
            slot_id="slot-proteccion-solar",
            label="Protección solar",
            target_category=Category.GROCERY,
            keywords=["bloqueador", "protector solar", "filtro solar", "spf", "factor de proteccion", "bronceador"],
            quantity=1,
            priority=1,
        ),
        dict(
            slot_id="slot-hidratacion",
            label="Hidratación",
            target_category=Category.GROCERY,
            keywords=["agua embotellada", "agua mineral", "bebida hidratante", "bidon de agua"],
            quantity=4,
            priority=2,
        ),
        dict(
            slot_id="slot-organizador-viaje",
            label="Dónde llevar todo",
            target_category=Category.HOME,
            keywords=["cooler", "hielera", "organizador de maletera", "bolsa termica", "contenedor plastico"],
            quantity=1,
            priority=3,
        ),
        dict(
            slot_id="slot-revision-vehiculo",
            label="Revisión del vehículo",
            target_category=Category.AUTO,
            keywords=["revision vehicular", "chequeo pre viaje", "presion de llantas", "kit de emergencia"],
            quantity=1,
            priority=3,
            is_optional=True,
        ),
    ],
    MissionKind.VEHICLE_MAINTENANCE: [
        dict(
            slot_id="slot-llantas",
            label="Llantas",
            target_category=Category.AUTO,
            keywords=["llanta", "llantas", "neumatico", "neumaticos", "medida de llanta"],
            quantity=4,
            priority=1,
        ),
        dict(
            slot_id="slot-aceite-filtros",
            label="Aceite y filtros",
            target_category=Category.AUTO,
            keywords=["aceite de motor", "lubricante", "filtro de aceite", "filtro de aire", "cambio de aceite"],
            quantity=1,
            priority=2,
        ),
        dict(
            slot_id="slot-limpiaparabrisas",
            label="Líquido limpiaparabrisas",
            target_category=Category.GROCERY,
            keywords=["liquido limpiaparabrisas", "limpia parabrisas", "aditivo limpiador de vidrios"],
            quantity=1,
            priority=4,
            is_optional=True,
        ),
        dict(
            slot_id="slot-organizador-maletera",
            label="Organizador de maletera",
            target_category=Category.HOME,
            keywords=["organizador de maletera", "caja organizadora para auto", "contenedor de maletera"],
            quantity=1,
            priority=5,
            is_optional=True,
        ),
    ],
    MissionKind.HOME_SETUP: [
        dict(
            slot_id="slot-almacenaje",
            label="Almacenaje",
            target_category=Category.HOME,
            keywords=["organizador", "caja organizadora", "repisa", "estante modular", "contenedor apilable"],
            quantity=2,
            priority=1,
        ),
        dict(
            slot_id="slot-limpieza-inicial",
            label="Limpieza inicial",
            target_category=Category.GROCERY,
            keywords=["limpiador multiuso", "desinfectante", "trapeador", "escoba", "bolsas de basura"],
            quantity=1,
            priority=2,
        ),
        dict(
            slot_id="slot-textil-hogar",
            label="Textil de hogar",
            target_category=Category.HOME,
            keywords=["sabanas", "cortinas", "toallas", "textil hogar"],
            quantity=1,
            priority=3,
            is_optional=True,
        ),
    ],
    MissionKind.EVENT: [
        dict(
            slot_id="slot-bebidas",
            label="Bebidas",
            target_category=Category.GROCERY,
            keywords=["bebidas", "gaseosa", "cerveza", "jugo", "snacks"],
            quantity=1,
            priority=1,
        ),
        dict(
            slot_id="slot-desechables",
            label="Desechables",
            target_category=Category.HOME,
            keywords=["vasos descartables", "platos descartables", "servilletas", "manteles"],
            quantity=1,
            priority=2,
        ),
        dict(
            slot_id="slot-parrilla",
            label="Insumos de parrilla",
            target_category=Category.AUTO,
            keywords=["carbon", "encendedor", "parrilla portatil"],
            quantity=1,
            priority=4,
            is_optional=True,
        ),
    ],
    MissionKind.RESTOCK: [
        dict(
            slot_id="slot-abarrotes",
            label="Abarrotes de la semana",
            target_category=Category.GROCERY,
            keywords=["abarrotes", "despensa", "arroz", "aceite comestible", "menestras"],
            quantity=1,
            priority=1,
        ),
        dict(
            slot_id="slot-limpieza-hogar",
            label="Limpieza del hogar",
            target_category=Category.GROCERY,
            keywords=["limpiador", "detergente", "jabon", "papel higienico"],
            quantity=1,
            priority=2,
        ),
    ],
}


def _strip_accents(text: str) -> str:
    return text.translate(str.maketrans("áéíóúñÁÉÍÓÚÑ", "aeiounAEIOUN"))


# Palabras vacías de más de 3 letras (las de 3 o menos ya las saca el filtro
# de longitud) que aparecen seguido en un pedido en lenguaje natural y no
# aportan nada como término de búsqueda -- sin esto, "útiles de aseo PARA mi
# bebé" terminaba encontrando "Parrilla portátil PARA camping". Sin tildes:
# el texto ya pasa por `_strip_accents` antes de compararse acá.
_STOPWORDS = frozenset(
    {
        "para", "este", "esta", "esto", "esos", "esas", "ese", "esa",
        "como", "cuando", "donde", "porque", "pero", "sobre", "entre", "hasta", "desde",
        "todo", "toda", "todos", "todas", "unos", "unas",
        "algo", "alguna", "algun", "algunas", "algunos",
        "necesito", "necesita", "necesitamos", "quiero", "quiere", "queremos",
        "tengo", "tiene", "tenemos", "estoy", "estamos", "somos", "vamos",
        "hacer", "hace", "puedo", "puede", "podemos", "poder",
        "solo", "muy", "mas", "tambien", "ademas",
        "nuestro", "nuestra", "nuestros", "nuestras", "usted", "ustedes",
    }
)


def _classify(text: str) -> MissionKind:
    normalized = _strip_accents(text.lower())
    for keywords, kind in _KEYWORD_TO_MISSION_KIND:
        if any(kw in normalized for kw in keywords):
            return kind
    return MissionKind.GENERIC


def fallback_plan(text: str) -> dict:
    """Nunca falla, nunca depende de red. Devuelve un `MissionPlanDraft`
    (serializado) -- lo mismo que produciría el subagente `planner`, pero
    determinista. No detecta marcas: sin el agente no hay `preferred_brands`."""
    from app.domain.schema import BasketSlot

    kind = _classify(text)
    templates = _FALLBACK_SLOT_TEMPLATES.get(kind)

    if templates:
        slots = [BasketSlot(**kwargs) for kwargs in templates]
    else:
        words = [w for w in _strip_accents(text.lower()).split() if len(w) > 3 and w not in _STOPWORDS]
        slots = [
            BasketSlot(
                slot_id="slot-generico",
                label="Necesidad general",
                target_category=Category.UNKNOWN,
                keywords=words[:6],
            )
        ]

    draft = MissionPlanDraft(mission_kind=kind, title=_FALLBACK_TITLES[kind], slots=slots)
    return draft.model_dump(mode="json")
