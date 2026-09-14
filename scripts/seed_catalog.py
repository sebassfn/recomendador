"""Genera catalog.db con el catálogo base de 3 categorías.

Esto NO es el ETL real (doc 01/07): es la semilla mínima para desarrollar la
rebanada vertical sin depender de insumos reales. El esquema de tablas ya
sigue el contrato del doc 01 §7 (columnas JSON para attributes/stock/signals/
documents) para que el adaptador real sólo tenga que cambiar la fuente de
filas, nunca el consumidor.

Uso: uv run python scripts/seed_catalog.py [ruta_destino]
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "catalog.db"

SCHEMA = """
CREATE TABLE products (
    product_id      TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    category        TEXT NOT NULL,
    subcategory     TEXT,
    raw_category    TEXT,
    brand           TEXT,
    description     TEXT,
    image_url       TEXT,
    unit            TEXT,
    pack_size       REAL,
    price_amount    TEXT NOT NULL,
    currency        TEXT NOT NULL DEFAULT 'USD',
    promo_amount    TEXT,
    is_active       INTEGER NOT NULL DEFAULT 1,
    attributes_json TEXT NOT NULL DEFAULT '{}',
    stock_json      TEXT NOT NULL DEFAULT '[]',
    signals_json    TEXT NOT NULL DEFAULT '{}',
    documents_json  TEXT NOT NULL DEFAULT '[]'
);
"""

# La procedencia comercial se conserva en signals_json; los textos visibles se
# mantienen como fichas normales de producto.

PRODUCTS = [
    # ---------------------------------------------------------------- GROCERY
    dict(
        product_id="CAT-G001",
        name="Nivea Protector Solar SPF50",
        category="grocery",
        subcategory="cuidado personal",
        brand="Nivea",
        description="Protector solar familiar de alta protección.",
        price_amount="29.90",
        promo_amount="24.90",
        attributes={"spf": "50", "units_per_pack": 1},
        stock=[{"store_id": "__ALL__", "status": "in_stock", "qty": 40}],
        signals={
            "margin_pct": {"value": 0.42, "source": "simulated", "note": "margen no viene en el dataset demo; valor sintético"},
            "is_private_label": {"value": False, "source": "simulated"},
            "turnover_index": {"value": 7.1, "source": "derived", "note": "derivado de ventas simuladas de la última semana"},
        },
        documents=[
            {
                "doc_id": "DOC-GUIA-VERANO-2025",
                "doc_title": "Guía de verano 2025",
                "locator": "p. 4",
                "snippet": "Para niños se recomienda SPF50 o superior",
                "confidence": 0.95,
            }
        ],
    ),
    dict(
        product_id="CAT-G002",
        name="Dasani Agua Mineral Pack 12x625ml",
        category="grocery",
        subcategory="bebidas",
        brand="Dasani",
        description="Pack de agua mineral para hidratación familiar.",
        price_amount="18.50",
        attributes={"units_per_pack": 12},
        stock=[{"store_id": "__ALL__", "status": "in_stock", "qty": 120}],
        signals={"margin_pct": {"value": 0.15, "source": "simulated"}},
        documents=[],
    ),
    dict(
        product_id="CAT-G003",
        name="OFF! Repelente de Insectos Familiar 200ml",
        category="grocery",
        subcategory="cuidado personal",
        brand="OFF!",
        description="Repelente de insectos familiar en aerosol.",
        price_amount="15.90",
        attributes={"units_per_pack": 1},
        stock=[{"store_id": "__ALL__", "status": "low_stock", "qty": 3}],
        signals={"is_private_label": {"value": False, "source": "simulated"}},
        documents=[],
    ),
    dict(
        product_id="CAT-G004",
        name="Nature Valley Snacks Saludables Mix Familiar 500g",
        category="grocery",
        subcategory="despensa",
        brand="Nature Valley",
        description="Mix familiar de frutos secos para snack.",
        price_amount="12.50",
        attributes={"units_per_pack": 1},
        stock=[{"store_id": "__ALL__", "status": "in_stock", "qty": 60}],
        signals={"is_private_label": {"value": False, "source": "simulated"}},
        documents=[],
    ),
    # ------------------------------------------------------------------ AUTO
    dict(
        product_id="CAT-A001",
        name="Michelin Llanta 185/65R15 Todo Terreno",
        category="auto",
        subcategory="llantas",
        brand="Michelin",
        description="Llanta para conducción en distintos tipos de terreno.",
        price_amount="320.00",
        attributes={"tire_size": "185/65R15", "units_per_pack": 1},
        stock=[{"store_id": "__ALL__", "status": "in_stock", "qty": 16}],
        signals={"turnover_index": {"value": 4.2, "source": "simulated"}},
        documents=[],
    ),
    dict(
        product_id="CAT-A002",
        name="Castrol Aceite Sintético 5W30 4L",
        category="auto",
        subcategory="mantenimiento",
        brand="Castrol",
        description="Aceite sintético para motor de viscosidad 5W30.",
        price_amount="89.90",
        promo_amount="79.90",
        attributes={"viscosity": "5W30", "units_per_pack": 1},
        stock=[{"store_id": "__ALL__", "status": "in_stock", "qty": 25}],
        signals={"margin_pct": {"value": 0.28, "source": "simulated"}},
        documents=[
            {
                "doc_id": "DOC-MANUAL-MANTENIMIENTO",
                "doc_title": "Manual de mantenimiento preventivo",
                "locator": "sección 2",
                "snippet": "Cambiar el aceite sintético cada 10,000 km o 12 meses",
                "confidence": 0.9,
            }
        ],
    ),
    dict(
        product_id="CAT-A003",
        name="Stanley Kit de Emergencia Vehicular",
        category="auto",
        subcategory="accesorios",
        brand="Stanley",
        description="Kit de emergencia vehicular con cables y triángulo.",
        price_amount="65.00",
        attributes={"units_per_pack": 1},
        stock=[{"store_id": "__ALL__", "status": "low_stock", "qty": 2}],
        signals={"is_private_label": {"value": False, "source": "simulated"}},
        documents=[],
    ),
    # ------------------------------------------------------------------ HOME
    dict(
        product_id="CAT-H001",
        name="Rubbermaid Organizador Plástico Apilable 40L",
        category="home",
        subcategory="almacenaje",
        brand="Rubbermaid",
        description="Caja organizadora plástica apilable de 40 litros.",
        price_amount="45.00",
        attributes={"capacity_l": 40, "units_per_pack": 1},
        stock=[{"store_id": "__ALL__", "status": "in_stock", "qty": 30}],
        signals={"is_private_label": {"value": True, "source": "simulated"}},
        documents=[],
    ),
    dict(
        product_id="CAT-H002",
        name="U-Haul Set de Cajas de Mudanza x10",
        category="home",
        subcategory="almacenaje",
        brand="U-Haul",
        description="Set de cajas de cartón reforzado para mudanza.",
        price_amount="39.90",
        attributes={"units_per_pack": 10},
        stock=[{"store_id": "__ALL__", "status": "in_stock", "qty": 50}],
        signals={"is_private_label": {"value": False, "source": "simulated"}},
        documents=[],
    ),
    dict(
        product_id="CAT-H003",
        name="Ikea Perchero de Pie Plegable",
        category="home",
        subcategory="organización",
        brand="Ikea",
        description="Perchero plegable de metal para organización del hogar.",
        price_amount="55.00",
        attributes={"units_per_pack": 1},
        stock=[{"store_id": "__ALL__", "status": "out_of_stock", "qty": 0}],
        signals={"is_private_label": {"value": False, "source": "simulated"}},
        documents=[],
    ),
]


def build(db_path: Path) -> None:
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA)
        for p in PRODUCTS:
            conn.execute(
                """
                INSERT INTO products (
                    product_id, name, category, subcategory, raw_category, brand,
                    description, image_url, unit, pack_size,
                    price_amount, currency, promo_amount, is_active,
                    attributes_json, stock_json, signals_json, documents_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    p["product_id"],
                    p["name"],
                    p["category"],
                    p.get("subcategory"),
                    p.get("raw_category", p["category"]),
                    p.get("brand"),
                    p.get("description"),
                    p.get("image_url"),
                    p.get("unit"),
                    p.get("pack_size"),
                    p["price_amount"],
                    p.get("currency", "USD"),
                    p.get("promo_amount"),
                    1 if p.get("is_active", True) else 0,
                    json.dumps(p.get("attributes", {})),
                    json.dumps(p.get("stock", [])),
                    json.dumps(p.get("signals", {})),
                    json.dumps(p.get("documents", [])),
                ),
            )
        conn.commit()
    finally:
        conn.close()

    print(f"catalog.db generado en {db_path} con {len(PRODUCTS)} productos base.")


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DB_PATH
    build(target)
