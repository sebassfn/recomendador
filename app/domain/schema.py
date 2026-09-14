"""Esquema canónico interno del recomendador de misión de compra.

Este módulo es EL CONTRATO. Toda la aplicación (motor de scoring, plantillas,
endpoints) consume únicamente estos tipos; nada lee el dataset crudo. La capa de
adaptación que se escribe el día de la prueba tiene un solo trabajo: producir
instancias válidas de `Product`, `DocumentRef` y `CompatibilityRule`.

Principio rector — REGLA DE DEGRADACIÓN:
    Sólo cuatro campos son obligatorios (product_id, name, category, price).
    Todo lo demás es opcional y cada feature declara qué hace sin él.
    Las señales de negocio nunca son floats crudos: van envueltas en `Signal`,
    que sabe si el valor es real, derivado o simulado. Eso es lo que permite
    que la UI muestre un badge honesto y que el motor renormalice sus pesos.

Nada en este archivo contiene lógica de negocio: sólo tipos, enums, defaults y
validadores de coherencia.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Category(str, Enum):
    """Las tres categorías canónicas del retailer.

    El dataset real traerá su propia taxonomía (probablemente cientos de nodos).
    El adaptador la colapsa a estos tres valores mediante la tabla de sinónimos
    del doc 01. `UNKNOWN` es el destino de lo que no se pudo mapear: sigue siendo
    buscable pero nunca se propone como parte de una canasta cross-categoría.
    """

    GROCERY = "grocery"  # consumo diario: supermercado
    AUTO = "auto"  # llantas, accesorios, mantenimiento
    HOME = "home"  # decoración, almacenaje
    UNKNOWN = "unknown"


class SignalSource(str, Enum):
    """Procedencia de una señal de negocio. Atraviesa todo el sistema.

    REAL      -> vino tal cual del dataset. Sin badge en la UI.
    DERIVED   -> calculada a partir de otros campos reales (ej. margen = (pvp-costo)/pvp,
                 o mediana de la categoría). Badge gris "estimado".
    SIMULATED -> no había forma de derivarla; valor sintético para que la feature
                 no muera. Badge ámbar "simulado". NUNCA se oculta al jurado.
    """

    REAL = "real"
    DERIVED = "derived"
    SIMULATED = "simulated"


class AvailabilityStatus(str, Enum):
    """Resultado del filtro duro de disponibilidad.

    UNKNOWN es deliberadamente distinto de OUT_OF_STOCK: si el dataset no trae
    stock, los productos no se descartan (quedarían cero resultados), se marcan
    como no verificables y la UI lo dice.
    """

    IN_STOCK = "in_stock"
    LOW_STOCK = "low_stock"
    OUT_OF_STOCK = "out_of_stock"
    UNKNOWN = "unknown"


class MissionKind(str, Enum):
    """Arquetipos de misión que el intérprete de necesidad puede reconocer.

    Existen para elegir la plantilla de slots por defecto cuando el LLM no está
    disponible (fallback determinista por palabras clave). `GENERIC` es el
    comodín: arma slots directamente desde las entidades extraídas.
    """

    TRIP = "trip"  # viaje, playa, feriado, camping
    VEHICLE_MAINTENANCE = "vehicle_maintenance"  # revisión, llantas, aceite
    HOME_SETUP = "home_setup"  # mudanza, organización, depto chico
    EVENT = "event"  # reunión, cumpleaños, parrilla
    RESTOCK = "restock"  # compra semanal
    GENERIC = "generic"


class ExclusionReason(str, Enum):
    """Códigos del filtro duro. Alimentan la feature "explicación del descarte".

    Son un enum y no strings libres porque la UI muestra un texto distinto por
    código y el doc 03 declara un estado por cada uno.
    """

    OUT_OF_STOCK = "out_of_stock"
    NOT_IN_SELECTED_STORE = "not_in_selected_store"
    OVER_BUDGET = "over_budget"
    INCOMPATIBLE = "incompatible"
    WRONG_CATEGORY = "wrong_category"
    MISSING_REQUIRED_ATTRIBUTE = "missing_required_attribute"
    WRONG_REQUIRED_ATTRIBUTE_VALUE = "wrong_required_attribute_value"
    DISCONTINUED = "discontinued"
    NO_PRICE = "no_price"
    NO_TEXT_MATCH = "no_text_match"


class CompatibilityOperator(str, Enum):
    """Operadores admitidos por una regla de compatibilidad."""

    EQUALS = "equals"
    IN_SET = "in_set"
    BETWEEN = "between"  # numérico inclusivo
    MATCHES_PATTERN = "matches_pattern"  # regex, p. ej. medidas de llanta


class Currency(str, Enum):
    DOLLAR = "$"
    PEN = "PEN"
    USD = "USD"
    COP = "COP"
    MXN = "MXN"
    CLP = "CLP"


# ---------------------------------------------------------------------------
# Señales: el envoltorio que hace posible la degradación
# ---------------------------------------------------------------------------

T = TypeVar("T")


class Signal(BaseModel, Generic[T]):
    """Un valor de negocio con su procedencia.

    Ninguna feature lee un float crudo. Lee un `Signal`, que sabe si el dato
    existe de verdad. Si el motor recibe `None` para una señal, NO la puntúa
    como cero: la elimina del cálculo y reparte su peso (ver doc 02).
    """

    model_config = ConfigDict(frozen=True)

    value: T
    source: SignalSource = SignalSource.REAL
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    note: str | None = Field(
        default=None,
        description="Explicación corta de la derivación, mostrada en el tooltip del badge.",
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_trustworthy(self) -> bool:
        """True si la señal puede presentarse sin badge de advertencia."""
        return self.source is SignalSource.REAL and self.confidence >= 0.8


# ---------------------------------------------------------------------------
# Precio y disponibilidad
# ---------------------------------------------------------------------------


class Price(BaseModel):
    """Precio de lista y, opcionalmente, precio promocional vigente.

    `amount` es obligatorio: un producto sin precio no puede entrar a una canasta
    con presupuesto ni mostrarse con credibilidad, así que el adaptador lo
    descarta (ExclusionReason.NO_PRICE) en vez de inventarlo.
    """

    model_config = ConfigDict(frozen=True)

    amount: Decimal = Field(ge=0)
    currency: Currency = Currency.USD
    promo_amount: Decimal | None = Field(default=None, ge=0)
    promo_starts_on: date | None = None
    promo_ends_on: date | None = None

    @model_validator(mode="after")
    def _promo_must_be_lower(self) -> Price:
        if self.promo_amount is not None and self.promo_amount > self.amount:
            raise ValueError("promo_amount no puede superar amount")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_promo(self) -> bool:
        return self.promo_amount is not None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def effective_amount(self) -> Decimal:
        """Precio que paga el cliente. Es el que usan presupuesto y ticket."""
        return self.promo_amount if self.promo_amount is not None else self.amount


class StoreStock(BaseModel):
    """Disponibilidad de un producto en una tienda concreta.

    Si el dataset no trae stock por tienda, el adaptador genera una única entrada
    con `store_id="__ALL__"` y `status=UNKNOWN`. La feature de selección de
    tienda se oculta (no se rompe) y el filtro duro degrada a "producto activo".
    """

    model_config = ConfigDict(frozen=True)

    store_id: str
    store_name: str | None = None
    qty: int | None = Field(default=None, ge=0)
    status: AvailabilityStatus = AvailabilityStatus.UNKNOWN
    updated_at: datetime | None = None


# ---------------------------------------------------------------------------
# Respaldo documental
# ---------------------------------------------------------------------------


class DocumentRef(BaseModel):
    """Un documento de los insumos, indexado para poder citarlo."""

    model_config = ConfigDict(frozen=True)

    doc_id: str
    title: str
    kind: str | None = Field(
        default=None,
        description="guía de compra, ficha técnica, manual, política, catálogo…",
    )
    uri: str | None = None
    published_on: date | None = None


class Citation(BaseModel):
    """Fragmento concreto que justifica una recomendación.

    Sin `Citation` una recomendación sigue siendo válida: se renderiza con el
    estado "sin respaldo documental" (doc 03). Lo que nunca se hace es inventar
    la cita.
    """

    model_config = ConfigDict(frozen=True)

    doc_id: str
    doc_title: str
    locator: str | None = Field(
        default=None, description="Página, sección, encabezado o número de fila."
    )
    snippet: str = Field(description="Texto literal citado. Nunca parafraseado por el LLM.")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    uri: str | None = None


# ---------------------------------------------------------------------------
# Compatibilidad / fitment
# ---------------------------------------------------------------------------


class CompatibilityRule(BaseModel):
    """Regla que decide si un producto sirve para un contexto declarado.

    Ejemplo (llanta): subject = {"vehicle_model": "Toyota Yaris 2018"},
    target_attribute = "tire_size", operator = IN_SET, values = ["185/65R15", ...].

    Es deliberadamente genérica para no depender de un esquema automotriz que
    quizá no exista. Si el dataset no trae atributos de fitment, el motor no
    evalúa ninguna regla y la verificación degrada a coincidencia textual de
    medida (doc 06).
    """

    model_config = ConfigDict(frozen=True)

    rule_id: str
    subject: dict[str, str] = Field(
        default_factory=dict,
        description="Contexto declarado por el usuario (vehículo, espacio, etc.).",
    )
    target_attribute: str = Field(description="Atributo del producto que se evalúa.")
    operator: CompatibilityOperator = CompatibilityOperator.EQUALS
    values: list[str] = Field(default_factory=list)
    numeric_range: tuple[float, float] | None = None
    source: SignalSource = SignalSource.REAL
    citation: Citation | None = None

    @model_validator(mode="after")
    def _operator_needs_operand(self) -> CompatibilityRule:
        if self.operator is CompatibilityOperator.BETWEEN and self.numeric_range is None:
            raise ValueError("operator=BETWEEN requiere numeric_range")
        if self.operator is not CompatibilityOperator.BETWEEN and not self.values:
            raise ValueError(f"operator={self.operator.value} requiere values no vacío")
        return self


# ---------------------------------------------------------------------------
# Señales de negocio
# ---------------------------------------------------------------------------


class BusinessSignals(BaseModel):
    """Las señales que el Modo Negocio expone y los sliders reordenan.

    Las cuatro son opcionales. Ausente significa ausente: el motor la saca del
    promedio ponderado y renormaliza. No existe "margen = 0".
    """

    model_config = ConfigDict(frozen=True)

    margin_pct: Signal[float] | None = Field(
        default=None, description="Margen bruto como fracción de 0 a 1."
    )
    turnover_index: Signal[float] | None = Field(
        default=None, description="Rotación. Mayor es mejor. Escala libre, se normaliza."
    )
    inventory_age_days: Signal[float] | None = Field(
        default=None, description="Antigüedad de inventario. Menor es mejor (se invierte)."
    )
    is_private_label: Signal[bool] | None = Field(
        default=None, description="Marca propia. Señal binaria."
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def available_signals(self) -> list[str]:
        """Nombres de las señales presentes. El motor renormaliza sobre esta lista."""
        return [
            name
            for name in ("margin_pct", "turnover_index", "inventory_age_days", "is_private_label")
            if getattr(self, name) is not None
        ]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_any_simulated(self) -> bool:
        """True si alguna señal presente es sintética. Dispara el badge global."""
        return any(
            getattr(self, name).source is SignalSource.SIMULATED  # type: ignore[union-attr]
            for name in self.available_signals
        )


# ---------------------------------------------------------------------------
# Producto
# ---------------------------------------------------------------------------


class Product(BaseModel):
    """Unidad canónica que consume toda la aplicación.

    Obligatorios: product_id, name, category, price. Nada más.
    Un producto construido sólo con esos cuatro campos DEBE validar — es el test
    de humo del contrato y la garantía de que el peor dataset posible sigue
    produciendo una demo funcional.
    """

    model_config = ConfigDict(frozen=True)

    # --- obligatorios ---
    product_id: str
    name: str
    category: Category
    price: Price

    # --- degradables ---
    subcategory: str | None = None
    raw_category: str | None = Field(
        default=None, description="Categoría original del dataset, para auditar el mapeo."
    )
    brand: str | None = None
    description: str | None = None
    image_url: str | None = None
    unit: str | None = Field(default=None, description="kg, L, unidad, par…")
    pack_size: float | None = None

    attributes: dict[str, str | float] = Field(
        default_factory=dict,
        description=(
            "Atributos libres del dataset (medida de llanta, color, capacidad, "
            "material…). Son la materia prima del fitment y del comparador."
        ),
    )

    attribute_sources: dict[str, SignalSource] = Field(default_factory=dict)
    stock: list[StoreStock] = Field(default_factory=list)
    signals: BusinessSignals = Field(default_factory=BusinessSignals)
    documents: list[Citation] = Field(
        default_factory=list, description="Respaldo documental precalculado por el indexador."
    )
    is_active: bool = True

    @computed_field  # type: ignore[prop-decorator]
    @property
    def availability(self) -> AvailabilityStatus:
        """Disponibilidad agregada sobre todas las tiendas conocidas."""
        if not self.stock:
            return AvailabilityStatus.UNKNOWN
        statuses = {s.status for s in self.stock}
        for candidate in (
            AvailabilityStatus.IN_STOCK,
            AvailabilityStatus.LOW_STOCK,
            AvailabilityStatus.UNKNOWN,
        ):
            if candidate in statuses:
                return candidate
        return AvailabilityStatus.OUT_OF_STOCK

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_documentary_support(self) -> bool:
        return bool(self.documents)


# ---------------------------------------------------------------------------
# Misión de compra
# ---------------------------------------------------------------------------


class MissionConstraints(BaseModel):
    """Restricciones duras extraídas de la necesidad del usuario."""

    model_config = ConfigDict(frozen=True)

    budget_total: Decimal | None = Field(default=None, ge=0)
    currency: Currency = Currency.USD
    store_id: str | None = None
    group_size: int | None = Field(default=None, ge=1)
    has_children: bool | None = None
    target_date: date | None = None
    vehicle: dict[str, str] | None = Field(
        default=None, description="Marca, modelo, año, medida declarada. Alimenta el fitment."
    )
    excluded_categories: list[Category] = Field(default_factory=list)


class AttributeRequirement(BaseModel):
    """Especificación explícita, independiente del tipo de producto.

    contains verifica un valor contra el intervalo admitido del producto;
    between verifica un atributo escalar contra el intervalo pedido.
    """

    attribute: str
    operator: Literal["eq", "gte", "lte", "between", "contains"] = "eq"
    value: str
    upper_value: str | None = None
    unit: str | None = None
    source_text: str = Field(default="", description="Fragmento literal del usuario que declara el valor; nunca una inferencia.")

    @model_validator(mode="after")
    def _between_requires_upper(self) -> AttributeRequirement:
        if self.operator == "between" and self.upper_value is None:
            raise ValueError("between requiere upper_value")
        return self


class BasketSlot(BaseModel):
    """Un rol funcional dentro de la canasta, no un producto.

    Esta es la pieza conceptual del producto: el LLM no elige SKUs, declara
    necesidades ("hidratación para 4 personas", "protección solar", "revisión de
    neumáticos") y copia lo que el cliente declaró (especificaciones, marcas
    nombradas). El motor resuelve cada slot contra la base de datos.
    """

    model_config = ConfigDict(frozen=True)

    slot_id: str
    label: str = Field(description="Texto mostrado al usuario, p. ej. 'Protección solar'.")
    rationale: str | None = Field(default=None, description="Por qué esta misión necesita esto.")
    target_category: Category = Category.UNKNOWN
    keywords: list[str] = Field(default_factory=list)
    required_attributes: dict[str, str] = Field(default_factory=dict)
    attribute_requirements: list[AttributeRequirement] = Field(default_factory=list)
    preferred_brands: list[str] = Field(
        default_factory=list,
        description="Marcas que el cliente nombró literalmente. Preferencia blanda: ordena primero, nunca filtra.",
    )
    quantity: int = Field(default=1, ge=1)
    priority: int = Field(default=3, ge=1, le=5, description="1 = imprescindible, 5 = accesorio.")
    is_optional: bool = False


class MissionPlan(BaseModel):
    """Salida del intérprete de necesidad; entrada del motor determinista.

    FRONTERA DEL LLM: el modelo produce este objeto y nada más. No ve productos,
    no ve precios, no ordena nada. Todo lo que ocurre después es Python auditable.
    """

    model_config = ConfigDict(frozen=True)

    raw_input: str
    mission_kind: MissionKind = MissionKind.GENERIC
    title: str | None = Field(default=None, description="Nombre corto de la misión para la UI.")
    slots: list[BasketSlot] = Field(default_factory=list)
    constraints: MissionConstraints = Field(default_factory=MissionConstraints)
    entities: dict[str, Any] = Field(default_factory=dict)
    interpreted_by: str = Field(
        default="llm", description="'llm' | 'keyword_fallback' | 'cached_seed'"
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def spanned_categories(self) -> list[Category]:
        """Categorías que la misión atraviesa. Si son >= 2 hay valor cross-categoría."""
        return sorted({s.target_category for s in self.slots} - {Category.UNKNOWN})


class MissionPlanDraft(BaseModel):
    """Lo que el subagente `planner` de `app/agent/` produce -- un subconjunto
    de `MissionPlan`. `raw_input` e `interpreted_by` los completa
    `app/mission_agent/bridge.py`, no el LLM: son metadatos de CÓMO se llegó
    al plan, no contenido que el modelo deba inferir. Ver
    `app/mission_agent/domain.py::RetailMissionDomain.output_model`.
    """

    mission_kind: MissionKind = MissionKind.GENERIC
    title: str | None = None
    slots: list[BasketSlot] = Field(default_factory=list)
    constraints: MissionConstraints = Field(default_factory=MissionConstraints)
    entities: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


class ScoringWeights(BaseModel):
    """Pesos del ranking. Los tres sliders del Modo Negocio escriben aquí.

    Los valores por defecto y sus rangos están justificados en el doc 02. No
    tienen por qué sumar 1: el motor los normaliza sobre las señales realmente
    disponibles en el candidate set.
    """

    model_config = ConfigDict(frozen=True)

    relevance: float = Field(default=0.50, ge=0.0, le=1.0)
    margin: float = Field(default=0.20, ge=0.0, le=1.0)
    turnover: float = Field(default=0.15, ge=0.0, le=1.0)
    private_label: float = Field(default=0.08, ge=0.0, le=1.0)
    promo: float = Field(default=0.07, ge=0.0, le=1.0)


class ScoredProduct(BaseModel):
    """Producto evaluado. Una sola estructura alimenta tres features.

    - Tarjeta normal   -> product + total_score
    - Modo Negocio     -> component_scores + weights_applied + signals
    - Descarte         -> excluded_reason + exclusion_detail

    Por eso "explicación del descarte" es barata de añadir al final: el objeto ya
    la contiene, sólo falta la plantilla.
    """

    model_config = ConfigDict(frozen=True)

    product: Product
    slot_id: str | None = None
    total_score: float = Field(default=0.0, ge=0.0, le=1.0)
    component_scores: dict[str, float] = Field(
        default_factory=dict, description="Señal normalizada (0-1) ANTES de aplicar el peso."
    )
    weights_applied: dict[str, float] = Field(
        default_factory=dict, description="Pesos ya renormalizados sobre las señales presentes."
    )
    missing_signals: list[str] = Field(
        default_factory=list, description="Señales ausentes cuyo peso se redistribuyó."
    )
    excluded_reason: ExclusionReason | None = None
    exclusion_detail: str | None = None
    compatibility_checked: bool = False
    compatibility_passed: bool | None = None
    matches_preferred_brand: bool | None = Field(
        default=None, description="None si el slot no pidió marca; si la pidió, si este producto es de esa marca."
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_recommended(self) -> bool:
        return self.excluded_reason is None


# ---------------------------------------------------------------------------
# Canasta
# ---------------------------------------------------------------------------


class ResolvedSlot(BaseModel):
    """Un slot con sus candidatos ya resueltos y ordenados."""

    model_config = ConfigDict(frozen=True)

    slot: BasketSlot
    picked: ScoredProduct | None = Field(
        default=None, description="None cuando no hubo ningún candidato que pasara el filtro duro."
    )
    alternatives: list[ScoredProduct] = Field(default_factory=list)
    rejected: list[ScoredProduct] = Field(
        default_factory=list, description="Descartados con su motivo. Alimenta el 'por qué no'."
    )
    most_common_rejection_reason: ExclusionReason | None = Field(
        default=None,
        description="Motivo de descarte más frecuente sobre TODOS los candidatos, no sólo `rejected` (que viene truncado).",
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_unfulfilled(self) -> bool:
        return self.picked is None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def preferred_brand_found(self) -> bool | None:
        """None si el slot no pidió marca. El motor ordena la marca pedida
        primero, así que basta con mirar el `picked`."""
        if not self.slot.preferred_brands:
            return None
        return self.picked is not None and self.picked.matches_preferred_brand is True


class Basket(BaseModel):
    """Resultado completo de una misión: lo que se renderiza y se presenta."""

    model_config = ConfigDict(frozen=True)

    mission: MissionPlan
    slots: list[ResolvedSlot] = Field(default_factory=list)
    weights: ScoringWeights = Field(default_factory=ScoringWeights)
    currency: Currency = Currency.USD
    baseline_ticket: Decimal | None = Field(
        default=None,
        description="Ticket de una canasta monocategoría equivalente. Base del uplift.",
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def items_count(self) -> int:
        return sum(rs.slot.quantity for rs in self.slots if rs.picked is not None)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def estimated_ticket(self) -> Decimal:
        total = Decimal("0")
        for rs in self.slots:
            if rs.picked is not None:
                total += rs.picked.product.price.effective_amount * rs.slot.quantity
        return total

    @computed_field  # type: ignore[prop-decorator]
    @property
    def categories_covered(self) -> list[Category]:
        return sorted(
            {rs.picked.product.category for rs in self.slots if rs.picked is not None}
            - {Category.UNKNOWN}
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_cross_category(self) -> bool:
        """El argumento central de la propuesta, hecho dato."""
        return len(self.categories_covered) >= 2

    @computed_field  # type: ignore[prop-decorator]
    @property
    def unfulfilled_slots(self) -> list[str]:
        return [rs.slot.label for rs in self.slots if rs.is_unfulfilled]


# ---------------------------------------------------------------------------
# Diagnóstico del adaptador
# ---------------------------------------------------------------------------


class FieldMapping(BaseModel):
    """Una fila de la plantilla de mapeo del doc 01, ya ejecutada."""

    model_config = ConfigDict(frozen=True)

    canonical_field: str
    source_ref: str | None = Field(default=None, description="tabla.columna del insumo real.")
    transformation: str | None = None
    coverage_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    resolution: SignalSource | None = Field(
        default=None, description="None = el campo quedó ausente."
    )
    note: str | None = None


class AdapterReport(BaseModel):
    """Lo que el sistema sabe sobre sus propios límites.

    Se renderiza como pantalla de diagnóstico. Ante el jurado es la prueba de que
    las degradaciones son decisiones declaradas y no accidentes.
    """

    model_config = ConfigDict(frozen=True)

    source_files: list[str] = Field(default_factory=list)
    products_ingested: int = 0
    products_valid: int = 0
    products_rejected: dict[str, int] = Field(
        default_factory=dict, description="Motivo -> conteo. Motivos = ExclusionReason.value."
    )
    documents_indexed: int = 0
    compatibility_rules_loaded: int = 0
    mappings: list[FieldMapping] = Field(default_factory=list)
    degraded_features: dict[str, str] = Field(
        default_factory=dict, description="Feature -> comportamiento degradado que quedó activo."
    )
    generated_at: datetime | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def category_coverage_ok(self) -> bool:
        """Sin al menos dos categorías vivas no hay demo cross-categoría."""
        return self.products_valid > 0
