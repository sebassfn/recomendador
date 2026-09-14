"""Operaciones puras del carrito."""

from __future__ import annotations

from decimal import Decimal

from app.domain.schema import Category
from app.presentation import cart as c
from tests.test_projector import basket, product, resolved, scored, slot


def test_add_suma_y_set_quantity_a_cero_elimina():
    s = c.add(c.CartState(), "s", "p")
    s = c.add(s, "s", "p", 2)
    assert c.quantity_of(s, "s", "p") == 3
    assert c.set_quantity(s, "s", "p", 0).is_empty


def test_la_misma_clave_en_otro_slot_es_otra_linea():
    s = c.add(c.add(c.CartState(), "s1", "p"), "s2", "p")
    assert len(s.lines) == 2


def test_default_respeta_la_cantidad_del_slot_y_omite_slots_vacios():
    b = basket(resolved(slot("a", qty=4), scored(product("A", "1"), 0.9)), resolved(slot("b"), None))
    assert c.default_from_basket(b).lines == (c.CartLine("a", "A", 4),)


def test_replace_conserva_cantidad_y_fusiona_si_ya_existe():
    s = c.CartState(lines=(c.CartLine("s", "A", 3), c.CartLine("s", "B", 1)))
    s = c.replace_product(s, "s", "A", "B")
    assert s.lines == (c.CartLine("s", "B", 4),)


def test_prune_descarta_lo_que_no_esta_en_el_pool_visible_y_lo_reporta():
    b = basket(resolved(slot(), *[scored(product(f"P{i}", "1"), 0.9 - i / 10) for i in range(4)]))
    s = c.CartState(lines=(c.CartLine("s1", "P0", 1), c.CartLine("s1", "P3", 1), c.CartLine("otro", "P0", 1)))
    kept, dropped = c.prune(s, b)
    assert kept.lines == (c.CartLine("s1", "P0", 1),)
    # P3 es la 4.ª opción: el motor la trajo pero la UI no la muestra.
    assert dropped == ["P3", "P0"]


def test_cheaper_swaps_solo_dentro_del_pool_visible_del_slot():
    b = basket(
        resolved(
            slot(qty=2), scored(product("A", "20"), 0.9), scored(product("B", "12"), 0.8),
            scored(product("C", "15"), 0.7), scored(product("D", "1"), 0.6),  # D no se muestra
        ),
        resolved(slot("x", Category.AUTO), scored(product("X", "5", Category.AUTO), 0.9)),
    )
    swaps = c.cheaper_swaps(c.default_from_basket(b), b)
    assert [(sw.old_product_id, sw.new_product_id, sw.saving) for sw in swaps] == [("A", "B", Decimal("16"))]

    after = c.apply_swaps(c.default_from_basket(b), swaps)
    assert c.quantity_of(after, "s1", "B") == 2
    assert c.cheaper_swaps(after, b) == []
