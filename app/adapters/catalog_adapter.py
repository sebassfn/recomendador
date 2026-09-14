"""Adaptador de `catalog.db` -> `Product`.

Único módulo que sabe que el catálogo vive en filas SQLite con columnas JSON.
Nada aguas abajo (repositorio, motor, plantillas) toca `sqlite3.Row` — todo
consume `Product` (CLAUDE.md regla 1).
"""

from __future__ import annotations

import json
import sqlite3

from app.domain.schema import (
    BusinessSignals,
    Category,
    Citation,
    Price,
    Product,
    Signal,
    SignalSource,
    StoreStock,
)
from app.domain.specifications import extract_attributes


def _signal(raw: dict | None) -> Signal | None:
    if raw is None:
        return None
    return Signal(
        value=raw["value"],
        source=SignalSource(raw.get("source", "real")),
        confidence=raw.get("confidence", 1.0),
        note=raw.get("note"),
    )


def row_to_product(row: sqlite3.Row) -> Product:
    attributes, attribute_sources = extract_attributes(
        json.loads(row["attributes_json"]), row["name"]
    )
    stock_raw = json.loads(row["stock_json"])
    signals_raw = json.loads(row["signals_json"])
    documents_raw = json.loads(row["documents_json"])

    return Product(
        product_id=row["product_id"],
        name=row["name"],
        category=Category(row["category"]),
        price=Price(
            amount=row["price_amount"],
            currency=row["currency"],
            promo_amount=row["promo_amount"],
        ),
        subcategory=row["subcategory"],
        raw_category=row["raw_category"],
        brand=row["brand"],
        description=row["description"],
        image_url=row["image_url"],
        unit=row["unit"],
        pack_size=row["pack_size"],
        attributes=attributes,
        attribute_sources=attribute_sources,
        stock=[StoreStock(**s) for s in stock_raw],
        signals=BusinessSignals(
            margin_pct=_signal(signals_raw.get("margin_pct")),
            turnover_index=_signal(signals_raw.get("turnover_index")),
            inventory_age_days=_signal(signals_raw.get("inventory_age_days")),
            is_private_label=_signal(signals_raw.get("is_private_label")),
        ),
        documents=[Citation(**d) for d in documents_raw],
        is_active=bool(row["is_active"]),
    )
