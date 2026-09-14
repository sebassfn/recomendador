"""Proyector dominio -> AdvisorVM. Todo con `Basket` armados a mano: el
proyector es puro y no debe necesitar la base para probarse."""

from __future__ import annotations

from decimal import Decimal

from app.domain.schema import (
    Basket,
    BasketSlot,
    BusinessSignals,
    Category,
    Citation,
    ExclusionReason,
    MissionConstraints,
    MissionKind,
    MissionPlan,
    Price,
    Product,
    ResolvedSlot,
    ScoredProduct,
    Signal,
    SignalSource,
)
from app.presentation.cart import CartState, default_from_basket
from app.presentation.projector import (
    derive_reason,
    derive_role,
    project_advisor,
    project_budget,
    project_chips,
    project_groups,
)


def product(pid: str, price: str, category=Category.GROCERY, **kw) -> Product:
    return Product(
        product_id=pid, name=f"Producto {pid}", category=category, price=Price(amount=Decimal(price)), **kw
    )


def scored(p: Product, score: float) -> ScoredProduct:
    return ScoredProduct(product=p, total_score=score)


def slot(sid="s1", category=Category.GROCERY, priority=3, optional=False, rationale="Porque sí.", qty=1):
    return BasketSlot(
        slot_id=sid, label=f"Slot {sid}", rationale=rationale, target_category=category,
        priority=priority, is_optional=optional, quantity=qty,
    )


def resolved(s: BasketSlot, picked: ScoredProduct | None, *alts: ScoredProduct, reason=None) -> ResolvedSlot:
    return ResolvedSlot(slot=s, picked=picked, alternatives=list(alts), most_common_rejection_reason=reason)


def basket(*slots: ResolvedSlot, budget: str | None = None, **mission_kw) -> Basket:
    mission = MissionPlan(
        raw_input="x",
        slots=[rs.slot for rs in slots],
        constraints=MissionConstraints(budget_total=Decimal(budget) if budget else None),
        **mission_kw,
    )
    return Basket(mission=mission, slots=list(slots))


# --- el contrato mínimo ------------------------------------------------------


def test_producto_con_solo_los_4_campos_obligatorios_se_proyecta():
    b = basket(resolved(slot(), scored(product("P1", "10"), 0.9)))
    vm = project_advisor(b, default_from_basket(b), [], mission_id="m")

    card = vm.groups[0].cards[0]
    assert card.name == "Producto P1"
    assert card.price.display == "$ 10.00"
    assert card.price_before is None
    assert card.brand is None
    assert card.badges == ()  # sin señales -> sin badge de procedencia
    assert card.reason.citation.has_support is False  # "sin respaldo documental"
    assert card.image.url is None and card.image.initial == "P"


def test_promo_muestra_precio_efectivo_y_tachado():
    p = Product(
        product_id="P", name="Promo", category=Category.GROCERY,
        price=Price(amount=Decimal("20"), promo_amount=Decimal("15")),
    )
    b = basket(resolved(slot(), scored(p, 0.9)))
    card = project_groups(b, CartState(), "m")[0].cards[0]
    assert card.price.display == "$ 15.00"
    assert card.price_before.display == "$ 20.00"


def test_badges_de_procedencia_simulated_manda_sobre_derived():
    sim = BusinessSignals(
        margin_pct=Signal(value=0.3, source=SignalSource.SIMULATED),
        turnover_index=Signal(value=2.0, source=SignalSource.DERIVED),
    )
    der = BusinessSignals(margin_pct=Signal(value=0.3, source=SignalSource.DERIVED))
    real = BusinessSignals(margin_pct=Signal(value=0.3, source=SignalSource.REAL))
    b = basket(
        resolved(
            slot(), scored(product("A", "10", signals=sim), 0.9),
            scored(product("B", "11", signals=der), 0.8), scored(product("C", "12", signals=real), 0.7),
        )
    )
    cards = project_groups(b, CartState(), "m")[0].cards
    assert [c.badges[0].kind if c.badges else None for c in cards] == ["simulated", "derived", None]


def test_cita_es_el_snippet_literal_del_producto():
    cite = Citation(doc_id="d", doc_title="Guía", snippet="Texto literal exacto.", locator="p. 4")
    b = basket(resolved(slot(), scored(product("A", "10", documents=[cite]), 0.9)))
    reason = project_groups(b, CartState(), "m")[0].cards[0].reason
    assert reason.citation.has_support is True
    assert reason.citation.snippet == "Texto literal exacto."
    assert reason.citation.locator == "p. 4"


def test_slot_sin_candidato_se_omite_de_las_recomendaciones():
    b = basket(
        resolved(slot("ok"), scored(product("A", "10"), 0.9)),
        resolved(slot("vacio"), None, reason=ExclusionReason.OUT_OF_STOCK),
    )
    group = project_groups(b, CartState(), "m")[0]
    assert len(group.cards) == 1
    assert all(card.slot_id != "vacio" for card in group.cards)


def test_no_se_proyectan_categorias_vacias():
    b = basket(
        resolved(slot("auto", Category.AUTO), None, reason=ExclusionReason.OUT_OF_STOCK),
        resolved(slot("grocery"), scored(product("A", "10"), 0.9)),
    )
    assert [g.category_value for g in project_groups(b, CartState(), "m")] == ["grocery"]
    assert project_groups(basket(resolved(slot(), None)), CartState(), "m") == ()


def test_grupos_en_orden_de_aparicion_de_los_slots():
    b = basket(
        resolved(slot("a", Category.AUTO), scored(product("A", "1", Category.AUTO), 0.9)),
        resolved(slot("g", Category.GROCERY), scored(product("G", "1"), 0.9)),
        resolved(slot("a2", Category.AUTO), scored(product("A2", "1", Category.AUTO), 0.9)),
    )
    groups = project_groups(b, CartState(), "m")
    assert [g.category_value for g in groups] == ["auto", "grocery"]
    assert len(groups[0].cards) == 2


def test_pool_visible_se_trunca_a_tres_tarjetas_por_slot():
    b = basket(resolved(slot(), *[scored(product(f"P{i}", "10"), 0.9 - i / 10) for i in range(4)]))
    assert len(project_groups(b, CartState(), "m")[0].cards) == 3


# --- roles ---------------------------------------------------------------------


def _roles(rs: ResolvedSlot) -> list[str]:
    return [derive_role(rs, sp) for sp in [rs.picked, *rs.alternatives]]


def test_rol_picked_recomendado_alternativa_barata_mas_economico():
    rs = resolved(slot(), scored(product("A", "20"), 0.9), scored(product("B", "10"), 0.8), scored(product("C", "30"), 0.7))
    assert _roles(rs) == ["recommended", "cheapest", "complementary"]


def test_rol_esencial_solo_para_el_picked_de_priority_1():
    rs = resolved(slot(priority=1), scored(product("A", "10"), 0.9), scored(product("B", "20"), 0.8))
    assert _roles(rs) == ["essential", "complementary"]


def test_rol_picked_de_slot_opcional_es_complementario():
    rs = resolved(slot(optional=True), scored(product("A", "10"), 0.9))
    assert _roles(rs) == ["complementary"]


def test_picked_mas_barato_no_deja_mas_economico_a_nadie():
    rs = resolved(slot(), scored(product("A", "5"), 0.9), scored(product("B", "10"), 0.8))
    assert _roles(rs) == ["recommended", "complementary"]


def test_empate_de_precio_con_picked_gana_el_picked():
    rs = resolved(slot(), scored(product("A", "10"), 0.9), scored(product("B", "10"), 0.8))
    assert "cheapest" not in _roles(rs)


# --- razón ---------------------------------------------------------------------


def test_razon_viene_del_rationale_del_slot_o_de_plantilla_fija():
    p = scored(product("A", "10"), 0.9)
    with_rat = resolved(slot(rationale="Van con niños."), p)
    without = resolved(slot(rationale=None), p)
    assert derive_reason(with_rat, p).text == "Van con niños."
    assert derive_reason(with_rat, p).source == "slot_rationale"
    assert derive_reason(without, p).text == "Cubre «Slot s1» de tu misión."
    assert derive_reason(without, p).source == "slot_label"


# --- chips ---------------------------------------------------------------------


def test_chips_de_la_mision_de_playa():
    m = MissionPlan(
        raw_input="x",
        mission_kind=MissionKind.TRIP,
        constraints=MissionConstraints(group_size=4, has_children=True, budget_total=Decimal("100")),
        entities={"transport": "carro", "destination": "playa", "occasion": "feriado largo"},
    )
    assert [c.text for c in project_chips(m)] == [
        "4 personas", "Presupuesto $ 100", "Viaje a playa", "Feriado largo", "En carro", "Con niños",
    ]


def test_restriccion_ausente_no_genera_chip_y_plan_vacio_usa_el_tipo():
    m = MissionPlan(raw_input="x", mission_kind=MissionKind.GENERIC)
    assert [c.text for c in project_chips(m)] == ["Compra general"]


def test_exclusion_no_se_pierde_por_el_tope_de_chips():
    m = MissionPlan(
        raw_input="x",
        mission_kind=MissionKind.TRIP,
        constraints=MissionConstraints(
            group_size=4, has_children=True, budget_total=Decimal("100"), excluded_categories=[Category.AUTO]
        ),
        entities={"transport": "carro", "destination": "playa", "occasion": "feriado"},
    )
    assert "Sin autos" in [c.text for c in project_chips(m)]


# --- presupuesto ---------------------------------------------------------------


def test_sin_presupuesto_no_hay_barra_ni_cero():
    b = project_budget(MissionPlan(raw_input="x"), Decimal("50"))
    assert b.has_budget is False
    assert b.remaining is None
    assert b.message == "Sin presupuesto declarado."


def test_dentro_del_presupuesto_dice_el_restante_exacto():
    m = MissionPlan(raw_input="x", constraints=MissionConstraints(budget_total=Decimal("100")))
    b = project_budget(m, Decimal("92.70"))
    assert b.is_over is False
    assert b.percent == 92
    assert b.message == "Te quedan $ 7.30 de tu presupuesto de $ 100.00."
    assert b.short_message == "Quedan $ 7.30"


def test_sobregiro_clampa_la_barra():
    m = MissionPlan(raw_input="x", constraints=MissionConstraints(budget_total=Decimal("100")))
    b = project_budget(m, Decimal("130"))
    assert b.is_over is True
    assert b.percent == 100
    assert "$ 30.00" in b.message


# --- carrito proyectado ----------------------------------------------------------


def test_carrito_agrupa_por_categoria_y_suma_cantidades():
    b = basket(
        resolved(slot("g", qty=4), scored(product("G", "1.20"), 0.9)),
        resolved(slot("a", Category.AUTO), scored(product("A", "24.90", Category.AUTO), 0.9)),
        budget="100",
    )
    vm = project_advisor(b, default_from_basket(b), [], mission_id="m")
    assert vm.cart.items_count == 5
    assert vm.cart.subtotal.display == "$ 29.70"
    assert [(g.title, g.subtotal.display) for g in vm.cart.groups] == [("Supermercado", "$ 4.80"), ("Autos", "$ 24.90")]
    assert vm.groups[0].cards[0].in_cart and vm.groups[0].cards[0].cart_quantity == 4
    assert vm.cart.budget.message == "Te quedan $ 70.30 de tu presupuesto de $ 100.00."


def test_optimizar_precio_se_deshabilita_explicando_por_que():
    b = basket(resolved(slot(), scored(product("A", "5"), 0.9), scored(product("B", "10"), 0.8)))
    wow = {a.action_id: a for a in project_advisor(b, default_from_basket(b), [], mission_id="m").wow_actions}
    assert wow["optimize_price"].enabled is False
    assert wow["optimize_price"].disabled_reason


# --- marca pedida ------------------------------------------------------------


def _brand_slot(*brands: str) -> BasketSlot:
    return BasketSlot(slot_id="cola", label="Gaseosa cola", target_category=Category.GROCERY,
                      preferred_brands=list(brands))


def test_marca_pedida_genera_chip_y_etiqueta_en_la_tarjeta():
    from app.presentation.advisor_reply import recommendation_reply

    s = _brand_slot("Coca-Cola")
    coca = ScoredProduct(product=product("coca", "8", brand="Coca-Cola"), total_score=0.5, matches_preferred_brand=True)
    otra = ScoredProduct(product=product("otra", "5", brand="Casa"), total_score=0.9, matches_preferred_brand=False)
    b = basket(resolved(s, coca, otra))

    chips = project_chips(b.mission)
    cards = {c.product_id: c for c in project_groups(b, CartState(), "m")[0].cards}

    assert any(c.kind == "brand" and c.text == "Marca: Coca-Cola" for c in chips)
    assert cards["coca"].requested_brand is True
    assert cards["otra"].requested_brand is False
    assert "No encontré" not in recommendation_reply(b)


def test_marca_no_encontrada_se_dice_en_la_respuesta():
    from app.presentation.advisor_reply import recommendation_reply

    s = _brand_slot("Big Cola")
    otra = ScoredProduct(product=product("otra", "5", brand="Casa"), total_score=0.9, matches_preferred_brand=False)
    b = basket(resolved(s, otra))

    assert b.slots[0].preferred_brand_found is False
    assert "No encontré Big Cola disponible para gaseosa cola; te muestro otras marcas." in recommendation_reply(b)


def test_sin_marca_pedida_no_hay_chip_ni_aviso():
    s = slot()
    b = basket(resolved(s, scored(product("p", "5", brand="Casa"), 0.5)))

    assert b.slots[0].preferred_brand_found is None
    assert not any(c.kind == "brand" for c in project_chips(b.mission))
