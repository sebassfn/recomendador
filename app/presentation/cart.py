"""Estado del carrito: sólo ids y cantidades, operaciones puras.

El carrito NO guarda productos ni precios. Guarda `(slot_id, product_id,
quantity)` y se resuelve contra el `Basket` de la sesión en el proyector
(`projector.index_basket`). Dos consecuencias buscadas:

- El precio que se muestra es siempre el del `Basket` vigente, nunca uno
  congelado en el momento de agregar.
- Todo lo agregable ya está en el `Basket` (es `picked` o `alternatives` de algún
  slot), así que no hace falta consultar la base por id.

Cada operación devuelve un `CartState` nuevo. Nada muta: una sesión puede
guardar el estado anterior para "deshacer" copiando una referencia.

No hay persistencia (CLAUDE.md / doc 03 §10.5): esto vive en memoria del
proceso dentro de `app/web/session.py` y muere con él.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.domain.schema import Basket, ResolvedSlot, ScoredProduct


@dataclass(frozen=True)
class CartLine:
    slot_id: str
    product_id: str
    quantity: int

    @property
    def key(self) -> tuple[str, str]:
        return (self.slot_id, self.product_id)


@dataclass(frozen=True)
class CartState:
    lines: tuple[CartLine, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.lines

    @property
    def keys(self) -> set[tuple[str, str]]:
        return {line.key for line in self.lines}


def default_from_basket(basket: Basket) -> CartState:
    """El carrito inicial: el `picked` de cada slot con la cantidad que la
    misión pidió (`slot.quantity`, p.ej. 4 aguas para 4 personas).

    Arrancar lleno y no vacío es deliberado: el mockup muestra una canasta ya
    armada que el usuario ajusta. Un carrito vacío obligaría a 7 clics antes de
    ver el valor de la propuesta.
    """
    return CartState(
        lines=tuple(
            CartLine(rs.slot.slot_id, rs.picked.product.product_id, rs.slot.quantity)
            for rs in basket.slots
            if rs.picked is not None
        )
    )


def quantity_of(state: CartState, slot_id: str, product_id: str) -> int:
    for line in state.lines:
        if line.key == (slot_id, product_id):
            return line.quantity
    return 0


def set_quantity(state: CartState, slot_id: str, product_id: str, quantity: int) -> CartState:
    """Fija la cantidad de una línea. `quantity <= 0` la elimina; una clave que
    no existe se agrega al final (conserva el orden de inserción)."""
    key = (slot_id, product_id)
    if quantity <= 0:
        return remove(state, slot_id, product_id)

    if key in state.keys:
        return CartState(
            lines=tuple(
                CartLine(slot_id, product_id, quantity) if line.key == key else line
                for line in state.lines
            )
        )
    return CartState(lines=state.lines + (CartLine(slot_id, product_id, quantity),))


def add(state: CartState, slot_id: str, product_id: str, quantity: int = 1) -> CartState:
    """Suma `quantity` a la línea; si no existe, la crea."""
    return set_quantity(
        state, slot_id, product_id, quantity_of(state, slot_id, product_id) + quantity
    )


def remove(state: CartState, slot_id: str, product_id: str) -> CartState:
    key = (slot_id, product_id)
    return CartState(lines=tuple(line for line in state.lines if line.key != key))


def replace_product(
    state: CartState, slot_id: str, old_product_id: str, new_product_id: str
) -> CartState:
    """Cambia el producto de una línea conservando slot y cantidad.

    Es la operación de "Optimizar precio": el usuario pidió 4 aguas, sigue
    teniendo 4 aguas, sólo que de otra marca. Si el nuevo producto ya estaba en
    el carrito para ese slot, las cantidades se suman en su línea.
    """
    if old_product_id == new_product_id:
        return state
    old_qty = quantity_of(state, slot_id, old_product_id)
    if old_qty == 0:
        return state
    without_old = remove(state, slot_id, old_product_id)
    return add(without_old, slot_id, new_product_id, old_qty)


# Opciones por slot que la UI muestra: el elegido + hasta 2 alternativas. El
# motor trae hasta 3 alternativas (`basket_service.MAX_ALTERNATIVES`), pero
# mostrar todas satura la pantalla del celular.
#
# Este número define EL POOL entero, no sólo lo que se pinta: carrito,
# "Optimizar precio" y roles trabajan sobre las mismas opciones visibles. Si no,
# optimizar podría meter al carrito un producto que el usuario nunca vio, y el
# texto "dentro de las alternativas que ya te mostré" sería mentira.
CARDS_PER_SLOT = 3


def pool_of(rs: ResolvedSlot) -> list[ScoredProduct]:
    """Las opciones visibles de un slot: `picked` + alternativas, en el orden
    del motor, truncado a `CARDS_PER_SLOT`. Todas pasaron el filtro duro."""
    return (([rs.picked] if rs.picked else []) + list(rs.alternatives))[:CARDS_PER_SLOT]


def slot_pool(basket: Basket, slot_id: str) -> list[ScoredProduct]:
    for rs in basket.slots:
        if rs.slot.slot_id == slot_id:
            return pool_of(rs)
    return []


@dataclass(frozen=True)
class PriceSwap:
    slot_id: str
    old_product_id: str
    new_product_id: str
    quantity: int
    saving: Decimal  # ya multiplicado por la cantidad


def cheaper_swaps(state: CartState, basket: Basket) -> list[PriceSwap]:
    """Para cada línea, la alternativa más barata de SU MISMO slot.

    Es la lógica de "Optimizar precio" y deliberadamente NO toca el motor: elige
    dentro del pool que `score_slot` ya filtró (stock, categoría,
    compatibilidad), así que un reemplazo nunca puede ser un producto inválido.
    El precio de un empate lo desempata el score del motor: entre dos igual de
    baratos gana el que el negocio ya prefería.

    Límite honesto: optimiza dentro de las ≤4 opciones que el motor trajo, no
    sobre el catálogo entero. El texto de la UI tiene que decirlo así.
    """
    swaps: list[PriceSwap] = []
    for line in state.lines:
        pool = slot_pool(basket, line.slot_id)
        current = next((sp for sp in pool if sp.product.product_id == line.product_id), None)
        if current is None or len(pool) < 2:
            continue
        cheapest = min(
            pool, key=lambda sp: (sp.product.price.effective_amount, -sp.total_score)
        )
        diff = current.product.price.effective_amount - cheapest.product.price.effective_amount
        if diff > 0:
            swaps.append(
                PriceSwap(
                    slot_id=line.slot_id,
                    old_product_id=line.product_id,
                    new_product_id=cheapest.product.product_id,
                    quantity=line.quantity,
                    saving=diff * line.quantity,
                )
            )
    return swaps


def apply_swaps(state: CartState, swaps: list[PriceSwap]) -> CartState:
    for swap in swaps:
        state = replace_product(state, swap.slot_id, swap.old_product_id, swap.new_product_id)
    return state


def prune(state: CartState, basket: Basket) -> tuple[CartState, list[str]]:
    """Descarta las líneas que ya no se pueden resolver contra `basket`.

    Pasa después de re-interpretar o re-resolver: si el LLM quitó un slot, o
    el re-ranking sacó un producto del pool, su línea de carrito queda huérfana.
    Devuelve el estado limpio y los ids descartados, para que el proyector los
    anuncie en vez de hacerlos desaparecer en silencio.
    """
    valid = {(rs.slot.slot_id, sp.product.product_id) for rs in basket.slots for sp in pool_of(rs)}

    kept = tuple(line for line in state.lines if line.key in valid)
    dropped = [line.product_id for line in state.lines if line.key not in valid]
    return CartState(lines=kept), dropped
