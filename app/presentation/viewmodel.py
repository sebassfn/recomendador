"""EL CONTRATO DE LA UI.

Este módulo es a las plantillas lo que `app/domain/schema.py` es al motor: la
única cosa que conocen. Una plantilla que necesite un dato que no está acá está
mal escrita — el dato se agrega a un view-model y lo llena el proyector.

Por qué existe
--------------
Hoy las plantillas consumen `Basket`/`ScoredProduct`/`Product` directamente. Eso
las ata al modelo de negocio: un retailer con otra taxonomía, otra moneda u otro
concepto de "slot" obliga a reescribir Jinja. Con esta capa la dirección de
dependencia es una sola:

    Basket + CartState + Conversation --[projector puro]--> AdvisorVM --> Jinja

Cambiar de modelo de negocio = reescribir `projector.py`. Las plantillas no se
tocan.

Dos reglas que se sostienen solas
---------------------------------
1. **Cero imports de `app.domain`.** Si este módulo no puede nombrar un enum del
   dominio, una plantilla tampoco puede recibirlo. `Decimal` es la única
   excepción y está confinado dentro de `Money` (ver su docstring).
2. **Dataclasses frozen, no Pydantic.** No hay nada que validar: esto es salida
   interna, construida por código nuestro, no entrada de un insumo externo. Y
   deja visualmente obvio que no pertenece al dominio.

Todo lo que una plantilla renderiza ya viene formateado como `str`: los precios
son `Money.display`, los enums son labels humanos, las clases CSS vienen
resueltas. Jinja no decide nada.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

# ---------------------------------------------------------------------------
# Vocabularios cerrados de la UI
# ---------------------------------------------------------------------------

# El papel que un producto juega dentro de su slot. Se deriva de forma
# determinista en el proyector (precio, priority, is_optional) — NUNCA lo dice
# el LLM, que no ve productos ni precios (CLAUDE.md regla 6).
RoleTag = Literal["essential", "recommended", "cheapest", "complementary"]

# De dónde salió el texto de `ReasonVM`. Es un campo de auditoría: permite
# responderle al jurado "¿esto lo inventó la IA?" con un dato, no con una
# promesa.
ReasonSource = Literal["slot_rationale", "slot_label"]

BadgeKind = Literal["simulated", "derived", "availability", "promo"]

TurnRole = Literal["user", "assistant"]


@dataclass(frozen=True)
class Money:
    """Un monto y su representación.

    `display` es lo ÚNICO que una plantilla debe imprimir. `amount` existe para
    que el proyector compare y sume sin reparsear strings, y es el único
    `Decimal` que cruza hacia esta capa: se mira, no se formatea en Jinja.
    """

    amount: Decimal
    display: str


@dataclass(frozen=True)
class BadgeVM:
    """Una píldora de la tarjeta, con su CSS y su tooltip ya resueltos.

    `kind` cubre los badges de procedencia que CLAUDE.md regla 4 hace
    obligatorios (`simulated` ámbar, `derived` gris) además de disponibilidad y
    promoción.
    """

    kind: BadgeKind
    text: str
    css: str
    title: str | None = None


@dataclass(frozen=True)
class CitationVM:
    """Respaldo documental de una recomendación.

    `has_support=False` NO es un estado de error: es el estado explícito "sin
    respaldo documental" que CLAUDE.md regla 5 exige mostrar. El snippet, cuando
    existe, es substring literal del documento indexado — recortado, jamás
    redactado.
    """

    has_support: bool
    snippet: str | None = None
    doc_title: str | None = None
    locator: str | None = None


@dataclass(frozen=True)
class ReasonVM:
    """Por qué este ítem está en la canasta.

    Se enmarca como "por qué lo necesitas" (habla de la misión), nunca como "por
    qué este producto" (hablaría del catálogo, que el LLM no vio). `source` deja
    trazable de dónde salió la frase.
    """

    text: str
    source: ReasonSource
    citation: CitationVM


@dataclass(frozen=True)
class ImageVM:
    """Imagen del producto o su placeholder.

    Sin imágenes externas (CLAUDE.md): si `url` es None se pinta `initial` sobre
    `css`, el color por categoría. Si hay `url`, la plantilla la usa con un
    `onerror` que cae al mismo placeholder.
    """

    url: str | None
    initial: str
    css: str


@dataclass(frozen=True)
class ProductCardVM:
    """Una tarjeta de recomendación: la unidad visual del mockup."""

    key: str  # f"{slot_id}:{product_id}" — id DOM estable entre swaps de HTMX
    slot_id: str
    product_id: str
    name: str
    brand: str | None
    price: Money
    price_before: Money | None  # sólo si hay promo vigente; si no, None
    image: ImageVM
    role: RoleTag
    role_label: str
    role_css: str
    reason: ReasonVM
    availability_label: str
    availability_css: str
    add_endpoint: str
    badges: tuple[BadgeVM, ...] = ()
    in_cart: bool = False
    cart_quantity: int = 0
    requested_brand: bool = False  # es de la marca que el cliente nombró para este slot

    # Hueco reservado para el Modo Negocio (punto 2 del orden de construcción de
    # CLAUDE.md). Cada entrada es (label, css_del_badge, valor_0_1) sacado de
    # `ScoredProduct.component_scores`. Existe desde ahora para que activar el
    # Modo Negocio sea escribir una plantilla, no rehacer este contrato.
    breakdown: tuple[tuple[str, str, float], ...] = ()


@dataclass(frozen=True)
class RecommendationGroupVM:
    """Una categoría del retailer con sus tarjetas. El cross-selling hecho UI."""

    category_value: str  # "grocery" — sólo para ids y CSS, nunca para mostrar
    title: str
    subtitle: str
    icon: str
    css: str = ""  # fondo/borde del grupo, ya resuelto
    cards: tuple[ProductCardVM, ...] = ()


@dataclass(frozen=True)
class ChipVM:
    """Un chip de "Entendí tu necesidad".

    Es la verificación que el usuario hace de un vistazo y, para el jurado, la
    prueba visible de que el sistema extrae variables estructuradas de una
    conversación.
    """

    text: str
    kind: str  # group | budget | context | vehicle | exclusion | brand | kind
    icon: str | None = None


@dataclass(frozen=True)
class TurnVM:
    """Un turno de la conversación ya listo para pintar."""

    role: TurnRole
    text: str
    detail: str | None = None  # p.ej. "interpretado desde caché de semillas"


@dataclass(frozen=True)
class CartLineVM:
    """Una línea del carrito, con sus tres endpoints de mutación resueltos."""

    key: str
    slot_id: str
    product_id: str
    name: str
    unit_price: Money
    quantity: int
    line_total: Money
    inc_endpoint: str
    dec_endpoint: str
    remove_endpoint: str
    badges: tuple[BadgeVM, ...] = ()


@dataclass(frozen=True)
class CartGroupVM:
    """Las líneas del carrito de una categoría, con su subtotal."""

    category_value: str
    title: str
    icon: str
    lines: tuple[CartLineVM, ...]
    subtotal: Money


@dataclass(frozen=True)
class BudgetVM:
    """Estado del presupuesto declarado.

    `has_budget=False` es normal y frecuente: el presupuesto es opcional en
    `MissionConstraints`. En ese caso la UI muestra el subtotal sin marco de
    cumplimiento, nunca un 0 ni una barra vacía (ausente != cero, CLAUDE.md
    regla 3).
    """

    has_budget: bool
    spent: Money
    message: str
    short_message: str = ""  # "Quedan S/ 7.30" — para la barra inferior del móvil
    total: Money | None = None
    remaining: Money | None = None
    is_over: bool = False
    percent: int = 0  # 0-100 ya clampeado, para el ancho de la barra
    bar_css: str = ""


@dataclass(frozen=True)
class CartVM:
    is_empty: bool
    items_count: int
    subtotal: Money
    budget: BudgetVM
    groups: tuple[CartGroupVM, ...] = ()


@dataclass(frozen=True)
class QuickActionVM:
    """Un botón de acción: las WOW (optimizar/mejorar) y las de refinamiento.

    `enabled=False` con `disabled_reason` es preferible a ocultar el botón
    cuando la acción no aplica: un control que desaparece confunde más que uno
    que explica por qué no se puede.
    """

    action_id: str
    label: str
    endpoint: str
    icon: str | None = None
    hint: str | None = None
    enabled: bool = True
    disabled_reason: str | None = None


@dataclass(frozen=True)
class AdvisorVM:
    """La pantalla entera, en un objeto.

    `advisor_body.html` recibe exactamente esto y nada más. Que sea un único
    argumento no es cosmético: es lo que permite que TODA mutación de HTMX
    devuelva el mismo partial y sea imposible desincronizar dos regiones.
    """

    mission_id: str
    title: str
    cart: CartVM
    currency_symbol: str
    conversation: tuple[TurnVM, ...] = ()
    chips: tuple[ChipVM, ...] = ()
    groups: tuple[RecommendationGroupVM, ...] = ()
    wow_actions: tuple[QuickActionVM, ...] = ()
    refine_actions: tuple[QuickActionVM, ...] = ()

    # Avisos honestos al usuario: sesión recuperada desde caché, líneas de
    # carrito descartadas tras re-interpretar, etc.
    notices: tuple[str, ...] = ()

    # Hueco reservado para el Modo Negocio, igual que `ProductCardVM.breakdown`.
    business_mode: bool = False

    # Categorías realmente cubiertas por el carrito. Es el argumento central de
    # la propuesta (cross-categoría) hecho dato visible.
    covered_categories: tuple[str, ...] = field(default_factory=tuple)
