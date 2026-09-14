"""Una fila de catálogo con marca real y moneda `$` pasa por el adaptador."""

import json
import sqlite3
from decimal import Decimal

from app.adapters.catalog_adapter import row_to_product
from app.domain.schema import Currency, SignalSource

ROW = {
    "product_id": "BRD-004",
    "name": "Coca-Cola Sin Azúcar Pack x6 500ml (DEMO)",
    "category": "grocery",
    "subcategory": "bebidas",
    "raw_category": "supermercado/bebidas",
    "brand": "Coca-Cola",
    "description": "Gaseosa cola sin azúcar en botellas de 500 ml, paquete de 6 unidades. Producto y datos comerciales simulados.",
    "image_url": None,
    "unit": "ml",
    "pack_size": 500,
    "price_amount": "24.90",
    "currency": "$",
    "promo_amount": "22.41",
    "is_active": 1,
    "attributes_json": json.dumps({"units_per_pack": 6, "flavor": "cola", "sugar_free": "sí", "container_type": "botella", "volume_ml": 500}),
    "stock_json": json.dumps([{"store_id": "__ALL__", "status": "in_stock", "qty": 30}]),
    "signals_json": json.dumps({
        "margin_pct": {"value": 0.28, "source": "simulated"},
        "turnover_index": {"value": 8.5, "source": "simulated"},
        "is_private_label": {"value": False, "source": "simulated"},
    }),
    "documents_json": "[]",
}


def test_fila_de_marca_real_con_dolar_valida():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(f"CREATE TABLE products ({', '.join(ROW)})")
    conn.execute(f"INSERT INTO products VALUES ({', '.join('?' for _ in ROW)})", list(ROW.values()))

    product = row_to_product(conn.execute("SELECT * FROM products").fetchone())

    assert product.brand == "Coca-Cola"
    assert product.price.currency is Currency.DOLLAR
    assert product.price.effective_amount == Decimal("22.41")
    assert product.attributes["units_per_pack"] == 6
    assert product.attributes["volume_ml"] == 500
    assert product.signals.margin_pct.source is SignalSource.SIMULATED
