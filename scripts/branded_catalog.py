"""Productos de marcas comerciales con señales de negocio simuladas."""

from __future__ import annotations

import csv
import json
from decimal import Decimal
from pathlib import Path


DATA_PATH = Path(__file__).resolve().parent.parent / "app/data/seeds/branded.csv"
EXPECTED_COLUMNS = (
    "family_id", "subcategory", "brand", "name", "unit", "pack_size",
    "units_per_pack", "base_price", "margin_pct", "turnover_index",
    "promo_pct", "keywords",
)


def branded_products() -> list[dict]:
    with DATA_PATH.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        if tuple(reader.fieldnames or ()) != EXPECTED_COLUMNS:
            raise ValueError("Columnas inválidas en branded.csv")
        rows = list(reader)

    ids = [row["family_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("family_id duplicado en branded.csv")

    products = []
    for row in rows:
        pid = f"BRD-{row['family_id']}"
        price = Decimal(row["base_price"])
        pack_size = Decimal(row["pack_size"])
        units_per_pack = int(row["units_per_pack"])
        margin_pct = Decimal(row["margin_pct"])
        turnover_index = Decimal(row["turnover_index"])
        promo_pct = Decimal(row["promo_pct"])
        if price <= 0 or pack_size <= 0 or units_per_pack <= 0:
            raise ValueError(f"Precio o presentación inválidos: {pid}")
        if not (Decimal("0") <= margin_pct <= Decimal("1")):
            raise ValueError(f"Margen inválido: {pid}")
        if turnover_index < 0 or not (Decimal("0") <= promo_pct < Decimal("1")):
            raise ValueError(f"Rotación o promoción inválida: {pid}")

        promo = (price * (Decimal("1") - promo_pct)).quantize(Decimal("0.01"))
        signals = {
            key: {
                "value": value,
                "source": "simulated",
                "note": "Señal comercial generada para el catálogo de referencia.",
            }
            for key, value in {
                "margin_pct": float(margin_pct),
                "turnover_index": float(turnover_index),
                "is_private_label": False,
            }.items()
        }
        description = (
            f"{row['brand']} {row['name']}. Presentación de {row['pack_size']} "
            f"{row['unit']}, {units_per_pack} unidad(es) por pack. "
            f"Términos de búsqueda: {row['keywords']}."
        )
        products.append({
            "product_id": pid,
            "name": f"{row['brand']} {row['name']}",
            "category": "grocery",
            "subcategory": row["subcategory"],
            "raw_category": f"supermercado/{row['subcategory']}",
            "brand": row["brand"],
            "description": description,
            "unit": row["unit"],
            "pack_size": float(pack_size),
            "price_amount": str(price.quantize(Decimal("0.01"))),
            "currency": "USD",
            "promo_amount": str(promo) if promo_pct else None,
            "is_active": 1,
            "attributes_json": json.dumps({"units_per_pack": units_per_pack}, ensure_ascii=False),
            "stock_json": json.dumps([{"store_id": "__ALL__", "status": "in_stock", "qty": 40}]),
            "signals_json": json.dumps(signals, ensure_ascii=False),
            "documents_json": "[]",
        })
    return products
