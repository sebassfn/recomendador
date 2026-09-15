"""Genera catalog.db completo: semilla base + catálogo sintético, en ese orden.

seed_catalog reemplaza la base de destino y expand_catalog le agrega productos,
así que el orden importa. Es el paso que corre CI antes de construir la imagen.

Uso desde la raíz: uv run python scripts/generar_catalogo.py [ruta_destino]
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.expand_catalog import expand, products
from scripts.seed_catalog import build

if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else PROJECT_ROOT / "catalog.db"
    build(target)
    total = expand(target)
    print(f"Actualizados {len(products())} productos PRD-*, SUP-* y BRD-*. Catálogo total: {total}.")
