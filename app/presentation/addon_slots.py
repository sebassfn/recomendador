"""Slots preescritos que las acciones rápidas agregan sin LLM.

Son el fallback determinista de "Agrega bebidas" cuando el proveedor no
responde. Declaran una necesidad (como cualquier `BasketSlot`), no un producto:
el motor sigue resolviéndolos contra el catálogo.
"""

from __future__ import annotations

from app.domain.schema import BasketSlot, Category

ADDON_SLOTS: dict[str, BasketSlot] = {
    "add_drinks": BasketSlot(
        slot_id="addon-bebidas",
        label="Bebidas",
        rationale="Pediste agregar bebidas a la canasta.",
        target_category=Category.GROCERY,
        keywords=["bebida", "gaseosa", "jugo", "agua", "bebida hidratante", "refresco"],
        quantity=1,
        priority=4,
        is_optional=True,
    ),
}
