"""Proyector: dominio -> contrato de UI.

Único módulo que conoce a la vez `app.domain.schema` y
`app.presentation.viewmodel`. Todo lo que hay acá es puro: sin `sqlite3`, sin
`Request`, sin red, sin LLM. Mismo `Basket` + mismo `CartState` = mismo
`AdvisorVM`, siempre. Por eso se testea sin base de datos.

Para adaptar la UI a otro modelo de negocio se reescribe ESTE archivo. Las
plantillas no se tocan.

Qué decide el proyector y qué no
--------------------------------
Decide cosas de PRESENTACIÓN: cómo se formatea un precio, qué etiqueta de rol
lleva una tarjeta, qué chips resumen la misión. Todas son funciones
deterministas de datos que ya existen.

NO decide qué productos existen (la base), ni en qué orden (el motor), ni qué
necesita la misión (el MissionPlan). Respeta el orden que trae el `Basket`.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from app.domain.schema import (
    Basket,
    Currency,
    MissionKind,
    MissionPlan,
    Product,
    ResolvedSlot,
    ScoredProduct,
    SignalSource,
)
from app.presentation.cart import CartState, cheaper_swaps, pool_of
from app.presentation.viewmodel import (
    AdvisorVM,
    BadgeVM,
    BudgetVM,
    CartGroupVM,
    CartLineVM,
    CartVM,
    ChipVM,
    CitationVM,
    ImageVM,
    Money,
    ProductCardVM,
    QuickActionVM,
    ReasonVM,
    RecommendationGroupVM,
    RoleTag,
    TurnVM,
)
from app.web.copy import (
    AVAILABILITY_CSS,
    AVAILABILITY_LABELS,
    BADGE_DERIVED,
    BADGE_SIMULATED,
    CATEGORY_GROUP_CSS,
    CATEGORY_ICON,
    CATEGORY_LABELS,
    CATEGORY_PLACEHOLDER_CLASS,
    CATEGORY_SUBTITLE,
    CURRENCY_SYMBOL,
    MISSION_KIND_LABELS,
    REASON_FROM_LABEL,
    ROLE_CSS,
    ROLE_LABELS,
    product_signal_badge,
)

MAX_CHIPS = 6


# ---------------------------------------------------------------------------
# Primitivas
# ---------------------------------------------------------------------------


def money(amount: Decimal, currency: Currency) -> Money:
    symbol = CURRENCY_SYMBOL.get(currency, currency.value)
    return Money(amount=amount, display=f"{symbol} {amount:,.2f}")


def index_basket(basket: Basket) -> dict[tuple[str, str], tuple[ResolvedSlot, ScoredProduct]]:
    """`(slot_id, product_id)` -> dónde vive ese producto en el `Basket`.

    Es lo que permite que el carrito guarde sólo ids: toda línea se resuelve
    contra el `Basket` vigente de la sesión, sin consultar la base.
    """
    index: dict[tuple[str, str], tuple[ResolvedSlot, ScoredProduct]] = {}
    for rs in basket.slots:
        for sp in pool_of(rs):
            index[(rs.slot.slot_id, sp.product.product_id)] = (rs, sp)
    return index


def _endpoint(mission_id: str, action: str) -> str:
    return f"/mission/{mission_id}/{action}"


def _signal_badges(product: Product) -> tuple[BadgeVM, ...]:
    """Badges de procedencia obligatorios (CLAUDE.md regla 4): SIMULATED ámbar,
    DERIVED gris, REAL sin badge. Sin excepciones."""
    kind = product_signal_badge(product.signals)
    if kind == "simulated":
        text, css, title = BADGE_SIMULATED
        return (BadgeVM(kind="simulated", text=text, css=css, title=title),)
    if kind == "derived" or SignalSource.DERIVED in product.attribute_sources.values():
        text, css, title = BADGE_DERIVED
        return (BadgeVM(kind="derived", text=text, css=css, title=title),)
    return ()


# ---------------------------------------------------------------------------
# Tarjeta de producto
# ---------------------------------------------------------------------------


def derive_role(rs: ResolvedSlot, sp: ScoredProduct) -> RoleTag:
    """Rol del producto dentro de su slot. Precedencia estricta y documentada.

    1. Alternativa (no `picked`) que es la más barata del pool
       -> "Más económico". El `picked` nunca lo es: si fuese el más barato, su
       rol relevante es ser el recomendado.
    2. Cualquier otra alternativa -> "Complementario".
    3. `picked` de un slot opcional o accesorio (priority >= 4) -> "Complementario".
    4. `picked` de un slot imprescindible (priority 1) -> "Esencial".
    5. `picked` -> "Recomendado".

    "Esencial" y "Recomendado" son sólo del `picked`: una alternativa no es
    esencial, es una opción. Todo sale de `picked`/`alternatives`,
    `slot.priority`, `slot.is_optional` y `price.effective_amount`. Nada viene
    del LLM.
    """
    is_picked = rs.picked is not None and sp.product.product_id == rs.picked.product.product_id
    pool = pool_of(rs)

    if not is_picked and len(pool) >= 2:
        # Empate de precio: gana el de mayor score. Si empata con el `picked`,
        # gana el `picked` y esta alternativa no se etiqueta "más económico".
        cheapest = min(pool, key=lambda c: (c.product.price.effective_amount, -c.total_score))
        if cheapest.product.product_id == sp.product.product_id:
            return "cheapest"

    if not is_picked:
        return "complementary"
    if rs.slot.is_optional or rs.slot.priority >= 4:
        return "complementary"
    if rs.slot.priority == 1:
        return "essential"
    return "recommended"


def derive_reason(rs: ResolvedSlot, sp: ScoredProduct) -> ReasonVM:
    """Por qué este ítem está en la canasta, con su procedencia.

    1. `slot.rationale`: lo escribió el LLM SOBRE LA MISIÓN, sin ver productos
       ni precios. Es honesto mostrarlo como "por qué lo necesitas".
    2. Si no hay, plantilla fija con el label del slot.

    La cita va aparte y nunca se fusiona con la razón: es el texto literal del
    documento indexado (CLAUDE.md regla 5), o el estado explícito "sin respaldo
    documental".
    """
    if rs.slot.rationale:
        text, source = rs.slot.rationale, "slot_rationale"
    else:
        text, source = REASON_FROM_LABEL.format(label=rs.slot.label), "slot_label"

    docs = sp.product.documents
    if docs:
        c = docs[0]
        citation = CitationVM(
            has_support=True, snippet=c.snippet, doc_title=c.doc_title, locator=c.locator
        )
    else:
        citation = CitationVM(has_support=False)

    return ReasonVM(text=text, source=source, citation=citation)  # type: ignore[arg-type]


def project_card(
    rs: ResolvedSlot, sp: ScoredProduct, cart: CartState, mission_id: str
) -> ProductCardVM:
    product = sp.product
    price = product.price
    category = product.category.value
    role = derive_role(rs, sp)
    qty = next(
        (
            line.quantity
            for line in cart.lines
            if line.key == (rs.slot.slot_id, product.product_id)
        ),
        0,
    )

    return ProductCardVM(
        key=f"{rs.slot.slot_id}:{product.product_id}",
        slot_id=rs.slot.slot_id,
        product_id=product.product_id,
        name=product.name,
        brand=product.brand,
        price=money(price.effective_amount, price.currency),
        price_before=money(price.amount, price.currency) if price.has_promo else None,
        image=ImageVM(
            url=product.image_url,
            initial=product.name[:1].upper(),
            css=CATEGORY_PLACEHOLDER_CLASS.get(category, CATEGORY_PLACEHOLDER_CLASS["unknown"]),
        ),
        role=role,
        role_label=ROLE_LABELS[role],
        role_css=ROLE_CSS[role],
        reason=derive_reason(rs, sp),
        availability_label=AVAILABILITY_LABELS[product.availability],
        availability_css=AVAILABILITY_CSS[product.availability],
        add_endpoint=_endpoint(mission_id, "cart/add"),
        badges=_signal_badges(product),
        in_cart=qty > 0,
        cart_quantity=qty,
        requested_brand=sp.matches_preferred_brand is True,
    )


# ---------------------------------------------------------------------------
# Grupos de recomendación
# ---------------------------------------------------------------------------


def _category_order(basket: Basket) -> list[str]:
    """Orden de las categorías = orden de primera aparición en los slots del
    plan. Respeta la prioridad con que la misión declaró sus necesidades en vez
    de imponer un orden alfabético o fijo."""
    seen: list[str] = []
    for rs in basket.slots:
        value = rs.slot.target_category.value
        if value not in seen:
            seen.append(value)
    return seen


def project_groups(
    basket: Basket, cart: CartState, mission_id: str
) -> tuple[RecommendationGroupVM, ...]:
    groups: list[RecommendationGroupVM] = []
    for category in _category_order(basket):
        slots = [rs for rs in basket.slots if rs.slot.target_category.value == category]
        cards: list[ProductCardVM] = []
        for rs in slots:
            if rs.is_unfulfilled:
                continue
            for sp in pool_of(rs):
                cards.append(project_card(rs, sp, cart, mission_id))

        if not cards:
            continue
        groups.append(
            RecommendationGroupVM(
                category_value=category,
                title=CATEGORY_LABELS.get(category, category),
                subtitle=CATEGORY_SUBTITLE.get(category, ""),
                icon=CATEGORY_ICON.get(category, "📦"),
                css=CATEGORY_GROUP_CSS.get(category, CATEGORY_GROUP_CSS["unknown"]),
                cards=tuple(cards),
            )
        )
    return tuple(groups)


# ---------------------------------------------------------------------------
# Carrito y presupuesto
# ---------------------------------------------------------------------------


def project_budget(mission: MissionPlan, spent: Decimal) -> BudgetVM:
    currency = mission.constraints.currency
    budget = mission.constraints.budget_total
    spent_m = money(spent, currency)

    # Ausente != cero (CLAUDE.md regla 3): sin presupuesto declarado no hay
    # barra ni "te quedan S/ 0". Se dice explícitamente.
    if budget is None:
        return BudgetVM(has_budget=False, spent=spent_m, message="Sin presupuesto declarado.")

    remaining = budget - spent
    is_over = remaining < 0
    percent = 100 if budget == 0 else max(0, min(100, int(spent * 100 / budget)))

    if is_over:
        message = f"Te pasaste por {money(-remaining, currency).display} de tu presupuesto de {money(budget, currency).display}."
        short_message = f"Excede {money(-remaining, currency).display}"
        bar_css = "bg-red-500"
    else:
        message = f"Te quedan {money(remaining, currency).display} de tu presupuesto de {money(budget, currency).display}."
        short_message = f"Quedan {money(remaining, currency).display}"
        bar_css = "bg-amber-500" if percent >= 90 else "bg-emerald-500"

    return BudgetVM(
        has_budget=True,
        spent=spent_m,
        message=message,
        short_message=short_message,
        total=money(budget, currency),
        remaining=money(max(remaining, Decimal("0")), currency),
        is_over=is_over,
        percent=percent,
        bar_css=bar_css,
    )


def project_cart(basket: Basket, cart: CartState, mission_id: str) -> CartVM:
    index = index_basket(basket)
    currency = basket.mission.constraints.currency
    by_category: dict[str, list[CartLineVM]] = {}
    subtotals: dict[str, Decimal] = {}
    total = Decimal("0")
    items = 0

    for line in cart.lines:
        hit = index.get(line.key)
        if hit is None:
            # Línea huérfana: la ruta debió podarla con `cart.prune` y avisar.
            # Si igual llega acá, no se inventa un precio: se omite.
            continue
        _, sp = hit
        product = sp.product
        unit = product.price.effective_amount
        line_total = unit * line.quantity
        category = product.category.value

        by_category.setdefault(category, []).append(
            CartLineVM(
                key=f"{line.slot_id}:{line.product_id}",
                slot_id=line.slot_id,
                product_id=line.product_id,
                name=product.name,
                unit_price=money(unit, product.price.currency),
                quantity=line.quantity,
                line_total=money(line_total, product.price.currency),
                inc_endpoint=_endpoint(mission_id, "cart/inc"),
                dec_endpoint=_endpoint(mission_id, "cart/dec"),
                remove_endpoint=_endpoint(mission_id, "cart/remove"),
                badges=_signal_badges(product),
            )
        )
        subtotals[category] = subtotals.get(category, Decimal("0")) + line_total
        total += line_total
        items += line.quantity

    # Mismo orden que los grupos de recomendación, para que la columna
    # izquierda y el carrito se lean en paralelo.
    order = _category_order(basket) + [c for c in by_category if c not in _category_order(basket)]
    groups = tuple(
        CartGroupVM(
            category_value=c,
            title=CATEGORY_LABELS.get(c, c),
            icon=CATEGORY_ICON.get(c, "📦"),
            lines=tuple(by_category[c]),
            subtotal=money(subtotals[c], currency),
        )
        for c in order
        if c in by_category
    )

    return CartVM(
        is_empty=not groups,
        items_count=items,
        subtotal=money(total, currency),
        budget=project_budget(basket.mission, total),
        groups=groups,
    )


# ---------------------------------------------------------------------------
# Chips "Entendí tu necesidad"
# ---------------------------------------------------------------------------


def _cap(value: object) -> str:
    text = str(value).strip()
    return text[:1].upper() + text[1:] if text else text


def project_chips(mission: MissionPlan) -> tuple[ChipVM, ...]:
    """Resumen verificable de lo que el sistema entendió.

    Orden fijo y sin LLM: todo sale del `MissionPlan` que ya existe. Una
    restricción ausente no genera chip (nunca "0 personas" ni "Presupuesto: —").
    """
    c = mission.constraints
    e = mission.entities or {}
    chips: list[ChipVM] = []

    if c.group_size is not None:
        noun = "persona" if c.group_size == 1 else "personas"
        chips.append(ChipVM(text=f"{c.group_size} {noun}", kind="group", icon="👥"))

    if c.budget_total is not None:
        symbol = CURRENCY_SYMBOL.get(c.currency, c.currency.value)
        amount = c.budget_total
        shown = f"{amount:,.0f}" if amount == amount.to_integral_value() else f"{amount:,.2f}"
        chips.append(ChipVM(text=f"Presupuesto {symbol} {shown}", kind="budget", icon="💰"))

    # Las exclusiones van antes del contexto: casi siempre son un ajuste que el
    # usuario ACABA de pedir, y es lo primero que querrá verificar. Si fueran
    # al final, el tope de chips las cortaría.
    for category in c.excluded_categories:
        label = CATEGORY_LABELS.get(category.value, category.value)
        chips.append(ChipVM(text=f"Sin {label.lower()}", kind="exclusion", icon="🚫"))

    # Igual que las exclusiones: es algo que el cliente dijo explícitamente.
    brands = dict.fromkeys(b for s in mission.slots for b in s.preferred_brands)
    for brand in brands:
        chips.append(ChipVM(text=f"Marca: {brand}", kind="brand", icon="🏷️"))

    destination = e.get("destination")
    if destination:
        text = (
            f"Viaje a {destination}"
            if mission.mission_kind is MissionKind.TRIP
            else _cap(destination)
        )
        chips.append(ChipVM(text=text, kind="context", icon="📍"))

    if e.get("occasion"):
        chips.append(ChipVM(text=_cap(e["occasion"]), kind="context", icon="🎯"))

    if e.get("transport"):
        chips.append(ChipVM(text=f"En {e['transport']}", kind="context", icon="🚗"))

    if c.has_children is True:
        chips.append(ChipVM(text="Con niños", kind="group", icon="🧒"))

    if c.vehicle:
        chips.append(
            ChipVM(text=" ".join(str(v) for v in c.vehicle.values() if v), kind="vehicle", icon="🚙")
        )

    if not chips:
        chips.append(
            ChipVM(text=MISSION_KIND_LABELS[mission.mission_kind], kind="kind", icon="🎯")
        )

    return tuple(chips[:MAX_CHIPS])


# ---------------------------------------------------------------------------
# Acciones
# ---------------------------------------------------------------------------


def build_wow_actions(
    basket: Basket, cart: CartState, mission_id: str
) -> tuple[QuickActionVM, ...]:
    """"Optimizar precio" y "Mejorar calidad".

    Se deshabilitan explicando por qué, en lugar de ocultarse: un botón que
    desaparece confunde más que uno que dice "ya es lo más barato".
    """
    has_cheaper = bool(cheaper_swaps(cart, basket))
    pure_relevance = basket.weights.relevance >= 0.999

    return (
        QuickActionVM(
            action_id="optimize_price",
            label="Optimizar precio",
            icon="🏷️",
            endpoint=_endpoint(mission_id, "optimize-price"),
            hint="Cambia cada ítem por la alternativa más barata que ya te mostré.",
            enabled=has_cheaper,
            disabled_reason=None if has_cheaper else "Ya tienes la opción más económica de cada ítem.",
        ),
        QuickActionVM(
            action_id="improve_quality",
            label="Mejorar calidad",
            icon="⭐",
            endpoint=_endpoint(mission_id, "improve-quality"),
            hint="Reordena por relevancia pura a tu necesidad, sin peso comercial.",
            enabled=not pure_relevance,
            disabled_reason="Ya está ordenado por relevancia pura." if pure_relevance else None,
        ),
    )


def build_refine_actions(basket: Basket, mission_id: str) -> tuple[QuickActionVM, ...]:
    """Chips de "¿Quieres que lo ajuste?".

    `action_id` es lo que viaja al endpoint `/turn` junto con el label como
    texto: el LLM re-interpreta el label, y si no puede, el `action_id` elige el
    fallback determinista. Con `drop_category:<valor>` la categoría va en el id.
    """
    endpoint = _endpoint(mission_id, "turn")
    actions = [
        QuickActionVM(
            action_id="cheaper", label="Quiero opciones más baratas", icon="💲", endpoint=endpoint
        ),
    ]

    # Una por categoría presente, pero sólo si queda al menos otra: quitar la
    # única categoría vaciaría la canasta.
    covered = _category_order(basket)
    if len(covered) >= 2:
        for category in covered:
            label = CATEGORY_LABELS.get(category, category).lower()
            actions.append(
                QuickActionVM(
                    action_id=f"drop_category:{category}",
                    label=f"Quita productos de {label}",
                    icon=CATEGORY_ICON.get(category, "📦"),
                    endpoint=endpoint,
                )
            )

    actions.append(
        QuickActionVM(action_id="add_drinks", label="Agrega bebidas", icon="🥤", endpoint=endpoint)
    )
    # "Solo marcas premium" del mockup: el dominio no tiene señal de calidad ni
    # tier. Lo único honesto es "de marca" (brand no nulo).
    actions.append(
        QuickActionVM(
            action_id="branded_only", label="Sólo productos de marca", icon="⭐", endpoint=endpoint
        )
    )
    return tuple(actions)


# ---------------------------------------------------------------------------
# Pantalla completa
# ---------------------------------------------------------------------------


def project_advisor(
    basket: Basket,
    cart: CartState,
    conversation: Sequence[TurnVM],
    *,
    mission_id: str,
    notices: Sequence[str] = (),
) -> AdvisorVM:
    mission = basket.mission
    cart_vm = project_cart(basket, cart, mission_id)
    return AdvisorVM(
        mission_id=mission_id,
        title=mission.title or MISSION_KIND_LABELS[mission.mission_kind],
        cart=cart_vm,
        currency_symbol=CURRENCY_SYMBOL.get(mission.constraints.currency, "$"),
        conversation=tuple(conversation),
        chips=project_chips(mission),
        groups=project_groups(basket, cart, mission_id),
        wow_actions=build_wow_actions(basket, cart, mission_id),
        refine_actions=build_refine_actions(basket, mission_id),
        notices=tuple(notices),
        covered_categories=tuple(g.category_value for g in cart_vm.groups),
    )
