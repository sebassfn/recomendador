"""Añade un catálogo reproducible sin borrar productos existentes.

Uso desde la raíz: uv run python scripts/expand_catalog.py
Opcional: pasar la ruta de una base existente como primer argumento.
Repetir el comando actualiza únicamente los IDs PRD-*, SUP-* y BRD-* de estas semillas.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from decimal import Decimal
from pathlib import Path

# La ejecución directa añade scripts/ a sys.path, pero no la raíz que
# contiene app/. Resolver desde __file__ también permite otro directorio cwd.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.adapters.catalog_adapter import row_to_product
from scripts.branded_catalog import branded_products
from scripts.supermarket_catalog import supermarket_products

# Categoría, nombre/búsqueda, precio base USD, atributos comunes.
FAMILIES = [
    ("grocery", "Protector solar bloqueador SPF50 200ml", "25", {"spf": "50"}),
    ("grocery", "Repelente de insectos familiar 200ml", "16", {}),
    ("grocery", "Agua mineral embotellada pack 6x1L", "12", {}),
    ("grocery", "Bebida hidratante isotónica 1L", "5", {}),
    ("grocery", "Snacks frutos secos mix 500g", "18", {}),
    ("grocery", "Gaseosa bebida familiar 3L", "9", {}),
    ("grocery", "Jugo de frutas bebida 1L", "6", {}),
    ("grocery", "Arroz abarrotes despensa 5kg", "23", {}),
    ("grocery", "Aceite comestible vegetal 1L", "8", {}),
    ("grocery", "Menestras lentejas despensa 1kg", "7", {}),
    ("grocery", "Limpiador multiuso desinfectante 1L", "8", {}),
    ("grocery", "Detergente para ropa 2kg", "19", {}),
    ("grocery", "Jabón de manos líquido 500ml", "7", {}),
    ("grocery", "Papel higiénico pack 12 rollos", "16", {}),
    ("grocery", "Bolsas de basura resistentes 50L x20", "9", {}),
    ("grocery", "Líquido limpiaparabrisas limpiador de vidrios 1L", "12", {}),
    ("auto", "Llanta neumático 185/65R15", "230", {"tire_size": "185/65R15"}),
    ("auto", "Llanta neumático 195/65R15", "260", {"tire_size": "195/65R15"}),
    ("auto", "Llanta neumático 205/55R16", "290", {"tire_size": "205/55R16"}),
    ("auto", "Aceite de motor lubricante 5W30 4L", "65", {"viscosity": "5W30"}),
    ("auto", "Aceite de motor lubricante 10W40 4L", "55", {"viscosity": "10W40"}),
    ("auto", "Filtro de aceite motor", "22", {}),
    ("auto", "Filtro de aire motor", "28", {}),
    ("auto", "Kit de emergencia vehicular cables triángulo", "45", {}),
    ("auto", "Medidor de presión de llantas neumáticos", "19", {}),
    ("auto", "Compresor inflador portátil neumáticos 12V", "95", {"voltage": "12V"}),
    ("auto", "Escobillas limpiaparabrisas par", "30", {}),
    ("auto", "Carbón vegetal insumos de parrilla 3kg", "15", {}),
    ("auto", "Parrilla portátil para camping", "100", {}),
    ("home", "Cooler hielera bolsa térmica 24L", "65", {"capacity_l": 24}),
    ("home", "Organizador de maletera contenedor para auto", "32", {}),
    ("home", "Caja organizadora contenedor plástico apilable 40L", "28", {"capacity_l": 40}),
    ("home", "Repisa estante modular almacenaje", "85", {}),
    ("home", "Cajas de cartón mudanza pack x10", "30", {}),
    ("home", "Perchero de pie plegable organización", "40", {}),
    ("home", "Sábanas textil hogar juego 2 plazas", "45", {}),
    ("home", "Cortinas textil hogar par", "55", {}),
    ("home", "Toallas textil hogar juego x2", "25", {}),
    ("home", "Vasos platos descartables servilletas kit x20", "15", {}),
    ("home", "Mantel para mesa reunión cumpleaños", "18", {}),
    ("home", "Escoba trapeador kit limpieza hogar", "22", {}),
    ("home", "Carpa tienda de campaña camping 4 personas", "180", {"capacity_people": 4}),
    ("home", "Silla plegable playa camping", "40", {}),
    ("home", "Sombrilla parasol playa", "50", {}),
]


BRAND_RULES = (
    (("protector solar",), ("Nivea", "Banana Boat", "Neutrogena")),
    (("repelente",), ("OFF!", "Raid", "Autan")),
    (("agua mineral",), ("Dasani", "San Luis", "Cielo")),
    (("bebida hidratante",), ("Gatorade", "Powerade", "Sporade")),
    (("snacks",), ("Nature Valley", "Planters", "Kirkland Signature")),
    (("gaseosa",), ("Coca-Cola", "Pepsi", "Inca Kola")),
    (("jugo",), ("Del Valle", "Tropicana", "Natura")),
    (("arroz", "menestras"), ("Costeño", "Goya", "Verde Valle")),
    (("aceite comestible",), ("Cocinero", "La Española", "Carbonell")),
    (("limpiador", "detergente", "jabón de manos", "papel higiénico", "bolsas de basura"),
     ("Clorox", "Lysol", "Mr. Músculo")),
    (("llanta",), ("Michelin", "Goodyear", "Bridgestone")),
    (("aceite de motor",), ("Mobil", "Castrol", "Shell")),
    (("filtro", "escobillas"), ("Bosch", "Mann-Filter", "Fram")),
    (("kit de emergencia", "medidor de presión", "compresor"), ("Stanley", "Michelin", "Black+Decker")),
    (("carbón", "parrilla"), ("Kingsford", "Weber", "Char-Broil")),
    (("cooler",), ("Coleman", "Igloo", "Rubbermaid")),
    (("organizador", "caja organizadora", "repisa", "cajas de cartón", "perchero"),
     ("Rubbermaid", "Sterilite", "Iris USA")),
    (("sábanas", "cortinas", "toallas", "mantel"), ("Cannon", "Mainstays", "Ikea")),
    (("vasos",), ("Dart", "Solo Cup", "Hefty")),
    (("escoba",), ("Vileda", "Scotch-Brite", "O-Cedar")),
    (("carpa", "silla plegable", "sombrilla"), ("Coleman", "Ozark Trail", "Quechua")),
)


def brands_for(name: str, category: str) -> tuple[str, str, str]:
    lowered = name.casefold()
    for needles, brands in BRAND_RULES:
        if any(needle in lowered for needle in needles):
            return brands
    return {
        "grocery": ("Nestlé", "Unilever", "Kraft"),
        "auto": ("Bosch", "3M", "Stanley"),
        "home": ("Rubbermaid", "Ikea", "Mainstays"),
    }[category]


def products() -> list[dict]:
    result = []
    for index, (category, name, base, attributes) in enumerate(FAMILIES, 1):
        brands = brands_for(name, category)
        for variant, (label, multiplier, units_per_pack, promo_pct) in enumerate(
            (("Individual", "1", 1, "0"), ("Dúo", "1.85", 2, "0.08"), ("Familiar", "3.45", 4, "0.12")), 1
        ):
            pid = f"PRD-{index:03d}-{variant}"
            amount = (Decimal(base) * Decimal(multiplier)).quantize(Decimal("0.01"))
            brand = brands[variant - 1]
            # Tres perfiles distintos para comparar relevancia y negocio.
            signals = {
                key: {"value": value, "source": "simulated", "note": "Dato sintético para pruebas; no representa ventas reales."}
                for key, value in {
                    "margin_pct": (0.12, 0.38, 0.25)[variant - 1],
                    "turnover_index": (9.0, 3.0, 6.0)[variant - 1],
                    "inventory_age_days": (10, 90, 30)[variant - 1],
                    "is_private_label": False,
                }.items()
            }
            status = "in_stock"
            if variant == 3 and index % 5 == 0:
                status = "out_of_stock"
            elif variant == 2 and index % 4 == 0:
                status = "low_stock"
            stock = [{"store_id": "__ALL__", "status": status,
                      "qty": {"in_stock": 35, "low_stock": 2, "out_of_stock": 0}[status]}]
            if variant == 3 and index % 6 == 0:
                stock = []  # Disponibilidad desconocida.
            product_attributes = {**attributes, "units_per_pack": units_per_pack}
            promo = (amount * (Decimal("1") - Decimal(promo_pct))).quantize(Decimal("0.01"))
            snippet = f"Ficha de producto: {brand} {name}. Presentación {label}, {units_per_pack} unidad(es) por pack."
            result.append({
                "product_id": pid,
                "name": f"{brand} {name} — {label}",
                "category": category,
                "brand": brand,
                "description": snippet,
                "price_amount": str(amount),
                "currency": "USD",
                "promo_amount": str(promo) if Decimal(promo_pct) else None,
                "is_active": 0 if variant == 3 and index % 11 == 0 else 1,
                "attributes_json": json.dumps(product_attributes),
                "stock_json": json.dumps(stock),
                "signals_json": json.dumps(signals),
                "documents_json": json.dumps([{
                    "doc_id": f"DOC-{pid}", "doc_title": "Ficha de producto",
                    "locator": pid, "snippet": snippet,
                }]) if variant == 2 else "[]",
            })
    result.extend(supermarket_products())
    result.extend(branded_products())
    return result


def expand(path: Path) -> int:
    # mode=rw exige una base existente y evita crear una vacía por error.
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=rw", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            for product in products():
                columns = list(product)
                updates = ", ".join(f"{key}=excluded.{key}" for key in columns if key != "product_id")
                conn.execute(
                    f"INSERT INTO products ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)}) "
                    f"ON CONFLICT(product_id) DO UPDATE SET {updates}",
                    list(product.values()),
                )
                # Valida exactamente el adaptador que usa la aplicación;
                # cualquier fallo revierte toda la ampliación.
                row_to_product(conn.execute("SELECT * FROM products WHERE product_id = ?", (product["product_id"],)).fetchone())
        return conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    finally:
        conn.close()


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else PROJECT_ROOT / "catalog.db"
    total = expand(target)
    print(f"Actualizados {len(products())} productos PRD-*, SUP-* y BRD-*. Catálogo total: {total}.")
