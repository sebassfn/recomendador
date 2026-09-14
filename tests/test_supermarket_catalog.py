from pathlib import Path
import sqlite3

from app.adapters.catalog_adapter import row_to_product
from app.domain.schema import BasketSlot, Category, ScoringWeights
from app.services.basket_service import resolve_single_slot
from scripts.expand_catalog import expand
from scripts.branded_catalog import branded_products
from scripts.seed_catalog import build
from scripts.supermarket_catalog import supermarket_products


def test_expansion_preserves_catalog_and_is_repeatable(tmp_path: Path):
    path = tmp_path / "catalog.db"
    build(path)
    with sqlite3.connect(path) as conn:
        original = conn.execute("SELECT * FROM products ORDER BY product_id").fetchall()
    total = expand(path)
    assert expand(path) == total
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT * FROM products WHERE product_id LIKE 'CAT-%' ORDER BY product_id").fetchall() == original
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM products WHERE product_id LIKE 'SUP-%'").fetchall()
        assert len(rows) == len(supermarket_products())
        families = {}
        for row in rows:
            product = row_to_product(row)
            assert product.category == Category.GROCERY
            assert "DEMO" not in product.name
            assert product.brand
            assert product.price.currency.value == "USD"
            assert product.attributes["units_per_pack"] > 0
            assert product.pack_size > 0
            assert product.price.amount > 0
            for signal in (product.signals.margin_pct, product.signals.turnover_index,
                           product.signals.inventory_age_days, product.signals.is_private_label):
                assert signal is None or signal.source.value == "simulated"
            for citation in product.documents:
                assert citation.snippet in product.description
            families.setdefault(product.product_id.rsplit("-", 1)[0], []).append(product)
        assert all(any(p.is_active and p.availability.value == "in_stock" for p in family) for family in families.values())


def test_branded_catalog_has_clean_brands_packs_and_simulated_signals(tmp_path: Path):
    path = tmp_path / "catalog.db"
    build(path)
    expand(path)
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM products WHERE product_id LIKE 'BRD-%'").fetchall()
        assert len(rows) == len(branded_products()) >= 60
        brands_by_term = {term: set() for term in ("pasta dental", "pañal", "lejía", "mezcla para pastel")}
        for row in rows:
            product = row_to_product(row)
            assert product.brand and "demo" not in product.brand.casefold()
            assert "demo" not in product.name.casefold()
            assert "simulad" not in (product.description or "").casefold()
            assert product.price.currency.value == "USD"
            assert product.attributes["units_per_pack"] > 0
            assert product.signals.margin_pct.source.value == "simulated"
            assert product.signals.turnover_index.source.value == "simulated"
            assert product.signals.is_private_label.value is False
            for term in brands_by_term:
                if term in product.name.casefold():
                    brands_by_term[term].add(product.brand)
        assert all(len(brands) >= 2 for brands in brands_by_term.values())


def test_supermarket_needs_find_matching_products(tmp_path: Path):
    path = tmp_path / "catalog.db"
    build(path)
    expand(path)
    # Necesidades explícitas: comprueba catálogo + adaptador + ranking sin red.
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        for keyword in ("manzana", "pechuga", "costilla", "chorizo", "salmon",
                        "huevo", "azucar", "garbanzo", "comino", "chimichurri",
                        "mayonesa", "cerveza", "vino tinto", "torta", "lavavajillas",
                        "pañal", "pasta dental", "mezcla para pastel", "levadura"):
            slot = BasketSlot(slot_id=keyword, label=keyword, target_category=Category.GROCERY, keywords=[keyword])
            result = resolve_single_slot(conn, slot, ScoringWeights())
            assert result.picked is not None, keyword
            product = result.picked.product
            assert keyword in product.description.lower(), (keyword, product.name)
            assert product.is_active and product.availability.value != "out_of_stock"
