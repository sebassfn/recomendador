"""Consultas SQL a mano sobre `catalog.db` (doc 01 §7: sin ORM).

Devuelve `Product` ya adaptado: el repositorio es la frontera entre SQL crudo
y el contrato de dominio.
"""

from __future__ import annotations

import sqlite3

from app.adapters.catalog_adapter import row_to_product
from app.domain.schema import Category, Product


def candidates_for_category(conn: sqlite3.Connection, category: Category) -> list[Product]:
    """Todos los productos activos de una categoría. El filtro duro y el
    ranking (capa de negocio) deciden qué pasa; acá sólo se acota el universo
    por categoría para no traer todo el catálogo a memoria."""
    if category is Category.UNKNOWN:
        rows = conn.execute("SELECT * FROM products WHERE is_active = 1").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM products WHERE category = ? AND is_active = 1",
            (category.value,),
        ).fetchall()
    return [row_to_product(row) for row in rows]
