"""Productos de supermercado sintéticos con IDs estables desde un CSV editable."""

from __future__ import annotations

import csv
import json
from decimal import Decimal
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parent.parent / "app/data/seeds/supermarket.csv"
REFRIGERATED = {"aves", "res", "cerdo", "pescados", "mariscos", "embutidos", "lacteos"}
PERISHABLE = REFRIGERATED | {"frutas", "verduras", "panaderia"}

# Marcas comerciales conocidas por tipo de producto. Cada familia genera tres
# presentaciones y rota entre estas marcas para que siempre existan alternativas.
BRANDS_BY_SUBCATEGORY = {
    "frutas": ("Dole", "Del Monte", "Chiquita"),
    "verduras": ("Dole", "Del Monte", "Green Giant"),
    "aves": ("Mr. Pollo", "Pronaca", "San Fernando"),
    "res": ("Don Diego", "Pronaca", "Swift"),
    "cerdo": ("Don Diego", "La Española", "San Fernando"),
    "pescados": ("Real", "Van Camps", "Pacific Star"),
    "mariscos": ("Real", "Pacific Star", "AquaChile"),
    "embutidos": ("Don Diego", "Plumrose", "La Española"),
    "lacteos": ("Gloria", "La Lechera", "Alpina"),
    "huevos": ("Indaves", "Avícola Fernández", "San Fernando"),
    "panaderia": ("Bimbo", "Wonder", "Pillsbury"),
    "granos": ("Costeño", "Goya", "Verde Valle"),
    "harinas": ("Pillsbury", "Gold Medal", "Haz de Oros"),
    "pastas": ("Barilla", "Don Vittorio", "La Moderna"),
    "conservas": ("Real", "Van Camps", "Goya"),
    "aceites": ("La Española", "Carbonell", "Cocinero"),
    "condimentos": ("McCormick", "Badia", "Knorr"),
    "salsas": ("Heinz", "Hellmann's", "McCormick"),
    "reposteria": ("Betty Crocker", "Duncan Hines", "Nestlé"),
    "desayuno": ("Nescafé", "Kellogg's", "Quaker"),
    "snacks": ("Lay's", "Doritos", "Oreo"),
    "congelados": ("McCain", "Green Giant", "McCormick"),
    "bebidas": ("Coca-Cola", "Pepsi", "Inca Kola"),
    "licores": ("Pilsener", "Casillero del Diablo", "Johnnie Walker"),
    "limpieza": ("Clorox", "Lysol", "Mr. Músculo"),
    "higiene": ("Colgate", "Dove", "Rexona"),
    "bebes": ("Huggies", "Pampers", "Johnson's Baby"),
    "mascotas": ("Purina", "Pedigree", "Whiskas"),
}


def supermarket_products() -> list[dict]:
    with DATA_PATH.open(encoding="utf-8", newline="") as source:
        families = list(csv.DictReader(source))
    ids = [row["family_id"] for row in families]
    if len(ids) != len(set(ids)):
        raise ValueError("family_id duplicado en supermarket.csv")

    products = []
    for row in families:
        family = int(row["family_id"])
        subcategory = row["subcategory"]
        frozen = subcategory == "congelados" or "congelad" in row["name"].lower()
        storage = "congelado" if frozen else "refrigerado" if subcategory in REFRIGERATED else "ambiente"
        brands = BRANDS_BY_SUBCATEGORY.get(subcategory, ("Nestlé", "Unilever", "Kraft"))
        for variant, (label, multiplier, units_per_pack, promo_pct) in enumerate(
            (
                ("Individual", "1", 1, "0"),
                ("Dúo", "1.85", 2, "0.08"),
                ("Familiar", "3.45", 4, "0.12"),
            ), 1
        ):
            pid = f"SUP-{row['family_id']}-{variant}"
            price = (Decimal(row["base_price"]) * Decimal(multiplier)).quantize(Decimal("0.01"))
            if price <= 0 or Decimal(row["pack_size"]) <= 0:
                raise ValueError(f"Precio o presentación inválidos: {pid}")
            brand = brands[variant - 1]
            attributes = {"storage": storage, "units_per_pack": units_per_pack}
            if subcategory == "licores":
                attributes["contains_alcohol"] = True
            signals = {
                name: {"value": value, "source": "simulated", "note": "Valor ficticio de prueba; no es una medición comercial."}
                for name, value in {
                    "margin_pct": (0.10 + (family % 5) * 0.01, 0.30 + (family % 7) * 0.01, 0.23)[variant - 1],
                    "turnover_index": (8.0, 5.0, 2.0)[variant - 1],
                    "inventory_age_days": variant if subcategory in PERISHABLE and not frozen else (7, 25, 60)[variant - 1],
                    "is_private_label": False,
                }.items()
            }
            status = "out_of_stock" if variant == 3 and family % 10 == 0 else "low_stock" if variant == 2 and family % 8 == 0 else "in_stock"
            stock = [{"store_id": "__ALL__", "status": status,
                      "qty": {"in_stock": 45, "low_stock": 2, "out_of_stock": 0}[status]}]
            if variant == 3 and family % 13 == 0:
                stock = []
            promo = (price * (Decimal("1") - Decimal(promo_pct))).quantize(Decimal("0.01"))
            snippet = f"Ficha de producto: {brand} {row['name']}. Presentación: {label}, {units_per_pack} unidad(es) por pack."
            products.append({
                "product_id": pid,
                "name": f"{brand} {row['name']} — {label}",
                "category": "grocery",
                "subcategory": subcategory,
                "raw_category": f"supermercado/{subcategory}",
                "brand": brand,
                "description": f"{snippet} Términos de búsqueda: {row['keywords']}.",
                "unit": row["unit"],
                "pack_size": float(row["pack_size"]),
                "price_amount": str(price),
                "currency": "USD",
                "promo_amount": str(promo) if Decimal(promo_pct) else None,
                "is_active": 0 if variant == 3 and family % 17 == 0 else 1,
                "attributes_json": json.dumps(attributes, ensure_ascii=False),
                "stock_json": json.dumps(stock),
                "signals_json": json.dumps(signals),
                "documents_json": json.dumps([{
                    "doc_id": f"DOC-{pid}", "doc_title": "Ficha de producto",
                    "locator": pid, "snippet": snippet,
                }], ensure_ascii=False) if variant == 2 else "[]",
            })
    return products
