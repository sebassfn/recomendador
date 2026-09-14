"""ETL: insumos reales -> `catalog.db`. El único archivo que se escribe el día
de la prueba (docs/01-contrato-de-datos.md).

Este módulo es la implementación de la capa de adaptación del doc 01 §1. El
dataset real es desconocido hoy, así que todas las funciones son firmas
vacías: el día de la prueba, después del triage (doc 01 §5) y con la
plantilla de mapeo (doc 01 §6) llena, sólo hace falta reemplazar el
`raise NotImplementedError` de cada una por el cuerpo real.

Pipeline (`build_db` los encadena en este orden):

    load_source()           insumos crudos -> filas homogéneas
        -> normalize_categories()   categoría cruda -> Category canónica
        -> derive_signals()         proxies -> BusinessSignals por fila
        -> index_docs()             documentos -> DocumentRef + Citation
    build_db()               arma Product[], valida obligatorios, escribe
                              el esquema SQLite del doc 01 §7.

`AdapterReport` es un modelo **frozen** (`app/domain/schema.py`): no se
mutan sus campos in-place. Cada paso recibe el reporte acumulado hasta ahí y
devuelve una versión nueva (`report.model_copy(update={...})`), así que la
firma de cada función incluye el reporte de entrada y de salida.

Nada aguas abajo de este archivo (motor, repositorios, UI) importa nada de
`app.etl`: sólo consume `catalog.db` a través de
`app/adapters/catalog_adapter.py` (regla de oro del doc 01 §1).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.domain.schema import (
    AdapterReport,
    CompatibilityRule,
    DocumentRef,
)

# Fila cruda de un insumo (una tabla.columna del CSV/XLSX/dump, o un registro
# de un documento). El shape real recién se conoce en el triage (doc 01 §5);
# hasta entonces es deliberadamente un dict sin esquema.
RawRecord = dict[str, Any]


def load_source(source_dir: Path, report: AdapterReport) -> tuple[list[RawRecord], AdapterReport]:
    """Lee los insumos crudos (CSV/XLSX/dump SQL) desde `source_dir`.

    Qué hace el día de la prueba:
        - Detecta el formato real y lee con pandas (CSV/XLSX) o `sqlite3`
          (dump). El protocolo de triage (doc 01 §5) ya dice qué comando
          correr para cada caso.
        - Homogeniza a `list[RawRecord]`: una fila = un producto candidato,
          sin normalizar todavía ningún campo canónico.
        - No decide inclusión/exclusión: el filtro duro de los 4 campos
          obligatorios (doc 01 §2) se aplica recién en `build_db`, cuando ya
          se armó el `Product` completo.

    Puebla en el reporte devuelto:
        - `source_files`: rutas de los archivos leídos.
        - `products_ingested`: conteo de filas crudas (antes de cualquier
          descarte).
    """
    raise NotImplementedError(
        "Llenar el día de la prueba con el triage (doc 01 §5): formato real de ./insumos."
    )


def normalize_categories(
    raw_records: list[RawRecord], report: AdapterReport
) -> tuple[list[RawRecord], AdapterReport]:
    """Mapea la taxonomía cruda del dataset a `Category` (doc 01 §4).

    Qué hace el día de la prueba:
        - Aplica la tabla de sinónimos llenada en el triage (doc 01 §4) para
          colapsar la categoría cruda a `grocery` / `auto` / `home`.
        - Lo que no matchea ninguna regla queda `Category.UNKNOWN` — nunca se
          fuerza una de las tres canónicas por adivinanza (sigue siendo
          buscable, pero nunca entra a una canasta cross-categoría).
        - Escribe en cada `RawRecord` tanto la categoría canónica como
          `raw_category` (el valor original, para la auditoría de doc 01
          §3.1 / pantalla de diagnóstico).

    Puebla en el reporte devuelto:
        - Una `FieldMapping` para `category` en `report.mappings` (cobertura
          %, resolución) una vez terminado el mapeo.

    Criterio de corte (doc 01 §4): a los 20 minutos, si más del 40 % cae en
    UNKNOWN, se abandona el mapeo exhaustivo y se mapean sólo las ramas que
    necesitan los 3 escenarios de la demo (doc 04). El resto queda UNKNOWN
    declarado, no reintentado.
    """
    raise NotImplementedError(
        "Llenar el día de la prueba con la tabla de sinónimos del triage (doc 01 §4)."
    )


def derive_signals(
    raw_records: list[RawRecord], report: AdapterReport
) -> tuple[list[RawRecord], AdapterReport]:
    """Calcula las señales de negocio (`BusinessSignals`) por producto.

    Qué hace el día de la prueba — la cadena de proxies ya está decidida
    (doc 01 §3.5); sólo hay que confirmar en qué escalón cae cada dataset:
        - `margin_pct`: (1) REAL si hay costo -> DERIVED `(pvp-costo)/pvp`;
          si no, (2) DERIVED mediana de margen por categoría; si no,
          (3) SIMULATED con tabla de márgenes típicos del retailer.
        - `turnover_index`: (1) DERIVED conteo de ventas si hay tabla de
          transacciones; si no, (2) DERIVED invirtiendo
          `inventory_age_days`; si no, (3) SIMULATED.
        - `inventory_age_days`: DERIVED fecha de ingreso vs. hoy si existe
          la columna; si no, queda ausente (doc 01 §3.5 no define un proxy
          simulado para este campo).
        - `is_private_label`: DERIVED cruzando `brand` contra la lista de
          marcas propias del retailer; si no hay lista, queda ausente.

    Regla de oro: una señal que no resuelve en ningún escalón queda `None`
    en su `Signal[...]`, nunca `0`. El motor la saca del scoring y
    redistribuye su peso (doc 02 §4) — este módulo no redondea eso, sólo
    declara la ausencia.

    No decide `is_active` ni disponibilidad de stock (eso es doc 01 §3.3 y
    vive en `load_source` / `normalize_categories`, no acá).

    Puebla en el reporte devuelto:
        - `FieldMapping` por cada señal en `report.mappings` con su
          `resolution` (`REAL` / `DERIVED` / `SIMULATED` / ausente).
        - `report.degraded_features` si alguna señal queda ausente en todo
          el dataset (slider deshabilitado en Modo Negocio).
    """
    raise NotImplementedError(
        "Llenar el día de la prueba según qué escalón de proxy exista para cada señal (doc 01 §3.5)."
    )


def index_docs(
    docs_dir: Path, raw_records: list[RawRecord], report: AdapterReport
) -> tuple[list[DocumentRef], list[RawRecord], AdapterReport]:
    """Indexa los documentos de insumos y resuelve citas por producto (doc 01 §8).

    Qué hace el día de la prueba:
        - Corre el comando de triage (doc 01 §8.2) para contar palabras del
          corpus y decidir el tramo A/B/C (casi seguro A, < ~50k palabras).
        - Extrae texto con docling (`export_to_markdown()`, da encabezados
          para el `locator`); `pypdf` es el fallback si docling no responde
          en 5 minutos (doc 07 §2).
        - Tramo A: los documentos completos van al LLM (con
          `cache_control: {"type": "ephemeral"}` porque son un prefijo
          estable) junto con cada producto/slot candidato; el LLM devuelve
          el span literal que lo respalda.
        - Tramo B: docling arma `documents_fts` en chunks de ~400 palabras
          con solape de 50 (`doc_id` + `locator`); FTS5 con `OR` y recall
          amplio (top 30) y el LLM elige el chunk y extrae el span.
        - **Toda `Citation.snippet` se valida como substring literal** del
          documento indexado antes de adjuntarla a un `RawRecord`. Si no
          valida, se descarta la cita — nunca se redacta una (doc 01 §3.6).
        - Adjunta a cada `RawRecord` la lista de `Citation` que le
          correspondan (puede quedar vacía: la tarjeta muestra "sin
          respaldo documental", sigue siendo una recomendación válida).

    Puebla en el reporte devuelto:
        - `documents_indexed`: conteo de `DocumentRef` cargados.
    """
    raise NotImplementedError(
        "Llenar el día de la prueba según el tramo A/B decidido en el triage (doc 01 §8.2)."
    )


def build_db(
    source_dir: Path,
    docs_dir: Path,
    out_path: Path,
    compatibility_rules: list[CompatibilityRule] | None = None,
) -> AdapterReport:
    """Orquesta el pipeline completo y escribe `catalog.db` (doc 01 §7).

    Qué hace el día de la prueba:
        1. `load_source(source_dir, report)` -> filas crudas.
        2. `normalize_categories(records, report)` -> categoría canónica.
        3. `derive_signals(records, report)` -> señales de negocio.
        4. `index_docs(docs_dir, records, report)` -> documentos + citas.
        5. Arma un `Product` por fila superviviente:
           - Sin `name` (y sin poder derivar un `product_id`): fila
             descartada, contada en `report.products_rejected`
             (doc 01 §2 — no hay `ExclusionReason` para esto porque nunca
             llega a ser `Product`, se descarta antes).
           - Sin `price.amount`: fila descartada con
             `ExclusionReason.NO_PRICE`, contada en
             `report.products_rejected`. Nunca se inventa un precio.
           - Categoría ausente/no mapeada: `Category.UNKNOWN`, el producto
             se construye igual (doc 01 §2).
        6. Escribe el esquema SQLite del doc 01 §7 en `out_path`: `products`
           (una fila por producto, con `attributes_json` / `stock_json` /
           `signals_json` / `documents_json`, igual convención que
           `scripts/seed_catalog.py`), `documents`, `compatibility_rules`,
           `products_fts` (FTS5 sobre `name || description || brand ||
           attributes`) y `documents_fts` si el tramo B de §8 está activo.
        7. Cierra `report.generated_at` y devuelve el reporte final — se
           transcribe tal cual a la pantalla de diagnóstico.

    Es el único punto de entrada pensado para `python -m app.etl` (doc 07
    §5.2: `uv run --group etl python -m app.etl ./insumos --out catalog.db`).
    """
    report = AdapterReport(source_files=[])
    raise NotImplementedError(
        "Llenar el día de la prueba: cablear los 4 pasos + el CREATE TABLE del doc 01 §7."
    )
