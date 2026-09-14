"""Motor de scoring: filtro duro (capa 1) + ranking (capa 2).

Implementa docs/02-motor-de-scoring.md. No toca SQLite ni HTTP: recibe
`Product`/`BasketSlot` ya resueltos por quien llame (adaptador o endpoint) y
devuelve `ScoredProduct`. La capa 3 (explicación/citas) no vive acá.

Regla de oro de todo el módulo, repetida del doc 02 §4: **una señal ausente
nunca se puntúa como 0**. O se imputa con la mediana del set (marcada
`DERIVED`) o se elimina de `S` y su peso se reparte entre las señales vivas.
"""

from __future__ import annotations

import re
import statistics
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Mapping, Sequence

from app.domain.schema import (
    AvailabilityStatus,
    BasketSlot,
    Category,
    CompatibilityOperator,
    CompatibilityRule,
    ExclusionReason,
    Price,
    Product,
    ScoredProduct,
    ScoringWeights,
    SignalSource,
)
from app.domain.specifications import evaluate_requirement

# ---------------------------------------------------------------------------
# Parámetros congelados (doc 02 §9)
# ---------------------------------------------------------------------------

COVERAGE_THRESHOLD = 0.60
RELEVANCE_FLOOR = 0.20
PROMO_WEIGHT_FIXED = 0.07
TURNOVER_MIX = (0.70, 0.30)  # (turnover_index, inventory_age invertida)
RELEVANCE_MIX = (0.45, 0.35, 0.20)  # (attr_match, text_match, category_match)
MIN_SET_SIZE_FOR_MINMAX = 3

_ALL_STORES_SENTINEL = "__ALL__"

# Nombres de señal usados como claves en component_scores / weights_applied.
# Deben coincidir con los campos de ScoringWeights.
SIGNAL_NAMES = ("relevance", "margin", "turnover", "private_label", "promo")
BUSINESS_SIGNAL_NAMES = ("margin", "turnover", "private_label")  # sujetas a §4


# ---------------------------------------------------------------------------
# Capa 1 — Filtro duro (doc 02 §2)
# ---------------------------------------------------------------------------


def _attribute_value_matches(actual: str | float, expected: str) -> bool:
    """`expected` es el valor que `slot.required_attributes` pide para un
    atributo (talla de llanta, viscosidad de aceite, voltaje de batería...) --
    cualquier atributo con un valor específico y no una simple presencia.
    Comparación insensible a mayúsculas y a espacios sobrantes, nunca por
    substring: "185/65R15" no matchea "85/65R1". Mismo criterio que usa
    `_default_attr_match` para la señal de relevancia -- una sola función
    para que el filtro duro y el score nunca discrepen sobre qué es "igual"."""
    return str(actual).strip().casefold() == expected.strip().casefold()


@dataclass(frozen=True)
class HardFilterResult:
    excluded_reason: ExclusionReason | None
    exclusion_detail: str | None
    compatibility_checked: bool
    compatibility_passed: bool | None

    @property
    def passed(self) -> bool:
        return self.excluded_reason is None


def apply_hard_filter(
    product: Product,
    slot: BasketSlot,
    *,
    store_id: str | None = None,
    budget_remaining: Decimal | None = None,
    compatibility_rules: Sequence[CompatibilityRule] = (),
    required_attribute_coverage: Mapping[str, float] | None = None,
) -> HardFilterResult:
    """Evalúa los 8 criterios de la tabla del doc 02 §2, en orden. Corta en el
    primero que falla."""

    # 1. Precio — Price.amount es obligatorio en el contrato, así que un
    # Product válido nunca llega acá sin precio (ya fue descartado en el
    # adaptador). Se deja el chequeo por completitud con la tabla del doc.
    if product.price is None:
        return HardFilterResult(ExclusionReason.NO_PRICE, "Sin precio.", False, None)

    # 2. Activo
    if not product.is_active:
        return HardFilterResult(ExclusionReason.DISCONTINUED, "Producto descontinuado.", False, None)

    # 3. Stock — UNKNOWN no descarta.
    if product.availability is AvailabilityStatus.OUT_OF_STOCK:
        return HardFilterResult(ExclusionReason.OUT_OF_STOCK, "Sin stock.", False, None)

    # 4. Tienda — sin store_id real o sin stock por tienda, el criterio se desactiva.
    if store_id is not None and product.stock:
        store_ids = {s.store_id for s in product.stock}
        if _ALL_STORES_SENTINEL not in store_ids and store_id not in store_ids:
            return HardFilterResult(
                ExclusionReason.NOT_IN_SELECTED_STORE,
                f"No disponible en la tienda '{store_id}'.",
                False,
                None,
            )

    # 5. Categoría — UNKNOWN en el slot no compite por tipo.
    if slot.target_category is not Category.UNKNOWN and product.category != slot.target_category:
        return HardFilterResult(
            ExclusionReason.WRONG_CATEGORY,
            f"Categoría '{product.category.value}' no coincide con '{slot.target_category.value}'.",
            False,
            None,
        )

    # 6. Compatibilidad — sólo se evalúan las reglas aplicables (el producto
    # trae el atributo). Sin reglas, el criterio se desactiva por completo.
    compatibility_checked = bool(compatibility_rules)
    compatibility_passed: bool | None = None
    if compatibility_rules:
        applicable = [r for r in compatibility_rules if r.target_attribute in product.attributes]
        compatibility_passed = all(_evaluate_compatibility_rule(product, r) for r in applicable)
        if not compatibility_passed:
            return HardFilterResult(
                ExclusionReason.INCOMPATIBLE,
                "No cumple una regla de compatibilidad aplicable.",
                compatibility_checked,
                compatibility_passed,
            )

    # 7. Atributo requerido — dos formas de fallar, distintas a propósito:
    #
    # - FALTA el atributo: el catálogo no sabe el dato de este producto. Se
    #   relaja a advertencia si la cobertura del atributo en el catálogo es
    #   < 50 % (puede que la mayoría del catálogo tampoco lo declare).
    # - el atributo está mal (el producto SÍ declara la talla/medida/tipo y
    #   no es la que la necesidad pide, p. ej. una llanta 195/65R15 para un
    #   auto que necesita 185/65R15): esto NUNCA se relaja por cobertura —
    #   no importa cuántos productos del catálogo tengan la medida
    #   equivocada, uno que no sirve para ESTE vehículo no sirve igual.
    #   `expected == ""` pide sólo que el atributo exista, sin importar el
    #   valor (mismo criterio que `_default_attr_match`, usado en relevancia).
    for key, expected in slot.required_attributes.items():
        actual = product.attributes.get(key)
        if actual is None:
            coverage = (required_attribute_coverage or {}).get(key)
            if coverage is not None and coverage < 0.50:
                continue  # relajado: no descarta
            return HardFilterResult(
                ExclusionReason.MISSING_REQUIRED_ATTRIBUTE,
                f"Falta el atributo requerido '{key}'.",
                compatibility_checked,
                compatibility_passed,
            )
        if expected and not _attribute_value_matches(actual, expected):
            return HardFilterResult(
                ExclusionReason.WRONG_REQUIRED_ATTRIBUTE_VALUE,
                f"'{key}' es {actual!r}, la necesidad pide {expected!r}.",
                compatibility_checked,
                compatibility_passed,
            )

    for requirement in slot.attribute_requirements:
        # Una especificación que el modelo no puede vincular literalmente al
        # mensaje del usuario se conserva, pero nunca filtra como si estuviera
        # confirmada.
        if not requirement.source_text:
            return HardFilterResult(
                ExclusionReason.MISSING_REQUIRED_ATTRIBUTE,
                f"No se pudo verificar el origen de '{requirement.attribute}'.",
                compatibility_checked,
                compatibility_passed,
            )
        matches = evaluate_requirement(product, requirement)
        if matches is None:
            return HardFilterResult(
                ExclusionReason.MISSING_REQUIRED_ATTRIBUTE,
                f"Faltan metadatos para verificar '{requirement.attribute}'.",
                compatibility_checked,
                compatibility_passed,
            )
        if not matches:
            return HardFilterResult(
                ExclusionReason.WRONG_REQUIRED_ATTRIBUTE_VALUE,
                f"El producto no cumple '{requirement.attribute}'={requirement.value!r}.",
                compatibility_checked,
                compatibility_passed,
            )

    # 8. Presupuesto — sin presupuesto declarado, no se evalúa.
    if budget_remaining is not None and product.price.effective_amount > budget_remaining:
        return HardFilterResult(
            ExclusionReason.OVER_BUDGET,
            "Excede el presupuesto remanente del slot.",
            compatibility_checked,
            compatibility_passed,
        )

    return HardFilterResult(None, None, compatibility_checked, compatibility_passed)


def _evaluate_compatibility_rule(product: Product, rule: CompatibilityRule) -> bool:
    actual = product.attributes.get(rule.target_attribute)
    if actual is None:
        return True  # no aplica a este producto

    if rule.operator is CompatibilityOperator.EQUALS:
        return str(actual) == rule.values[0]
    if rule.operator is CompatibilityOperator.IN_SET:
        return str(actual) in rule.values
    if rule.operator is CompatibilityOperator.BETWEEN:
        assert rule.numeric_range is not None
        lo, hi = rule.numeric_range
        try:
            value = float(actual)
        except (TypeError, ValueError):
            return False
        return lo <= value <= hi
    if rule.operator is CompatibilityOperator.MATCHES_PATTERN:
        return any(re.fullmatch(pattern, str(actual)) for pattern in rule.values)
    return True


# ---------------------------------------------------------------------------
# Capa 2 — Normalización por señal (doc 02 §3.1)
# ---------------------------------------------------------------------------


def minmax_normalize(values: Mapping[str, float]) -> dict[str, float]:
    """Min-max sobre el candidate set. Con < 3 elementos, o si todos son
    iguales (min == max, no hay forma de discriminar), degrada a 0.5
    constante — así el único candidato no saca 1.0 artificial (doc 02 §3.1)."""
    if len(values) < MIN_SET_SIZE_FOR_MINMAX:
        return {k: 0.5 for k in values}
    lo, hi = min(values.values()), max(values.values())
    if hi == lo:
        return {k: 0.5 for k in values}
    return {k: (v - lo) / (hi - lo) for k, v in values.items()}


def normalize_relevance(attr_match: float, text_match: float, category_match: float) -> float:
    w_attr, w_text, w_cat = RELEVANCE_MIX
    return w_attr * attr_match + w_text * text_match + w_cat * category_match


def normalize_private_label(is_private_label: bool) -> float:
    return 1.0 if is_private_label else 0.0


def normalize_promo(price: Price, as_of: date | None = None) -> float:
    """Binaria: 1 si hay promo vigente a la fecha. Sin fechas de vigencia,
    toda promo se asume vigente (doc 02 §3.1)."""
    if not price.has_promo:
        return 0.0
    as_of = as_of or date.today()
    if price.promo_starts_on is not None and as_of < price.promo_starts_on:
        return 0.0
    if price.promo_ends_on is not None and as_of > price.promo_ends_on:
        return 0.0
    return 1.0


# ---------------------------------------------------------------------------
# Capa 2 — Regla de cobertura y degradación (doc 02 §4)
# ---------------------------------------------------------------------------


def signal_coverage(values: Mapping[str, float | None]) -> float:
    if not values:
        return 0.0
    present = sum(1 for v in values.values() if v is not None)
    return present / len(values)


@dataclass(frozen=True)
class ResolvedComponent:
    alive: bool
    values: dict[str, float] = field(default_factory=dict)
    sources: dict[str, SignalSource] = field(default_factory=dict)


def resolve_business_component(
    normalized_by_product: Mapping[str, float | None],
    threshold: float = COVERAGE_THRESHOLD,
) -> ResolvedComponent:
    """Aplica la regla de cobertura del 60 % a una señal de negocio ya
    normalizada a [0,1] por producto (`None` = ausente para ese producto).

    - cobertura >= umbral: la señal vive. A quien le falta se le imputa la
      **mediana** de los valores presentes (nunca 0), marcada `DERIVED`.
    - cobertura < umbral: la señal muere para todo el set (dict vacío).
    """
    if signal_coverage(normalized_by_product) < threshold:
        return ResolvedComponent(alive=False)

    present = {pid: v for pid, v in normalized_by_product.items() if v is not None}
    med = statistics.median(present.values())
    values: dict[str, float] = dict(present)
    sources: dict[str, SignalSource] = {pid: SignalSource.REAL for pid in present}
    for pid, v in normalized_by_product.items():
        if v is None:
            values[pid] = med
            sources[pid] = SignalSource.DERIVED
    return ResolvedComponent(alive=True, values=values, sources=sources)


# ---------------------------------------------------------------------------
# Capa 2 — La fórmula: renormalización de pesos y score (doc 02 §3, §4)
# ---------------------------------------------------------------------------


def combine_weighted_score(
    component_scores: Mapping[str, float],
    weights: ScoringWeights,
    live_signals: Sequence[str] | None = None,
) -> tuple[float, dict[str, float]]:
    """score(p) = Σ w'ᵢ·nᵢ(p), con w'ᵢ = wᵢ / Σ wⱼ sobre las señales vivas S.

    `component_scores` trae únicamente las señales vivas para este producto,
    ya normalizadas a [0,1] (ver `resolve_business_component` /
    `normalize_*`). `live_signals` fija S explícitamente; por defecto se
    toman las claves de `component_scores`.

    Devuelve `(score_total, pesos_renormalizados)`, con score_total siempre
    en [0,1] (doc 02 §3).
    """
    live = list(live_signals) if live_signals is not None else list(component_scores.keys())
    raw_weights = {name: getattr(weights, name) for name in live}
    total_weight = sum(raw_weights.values())

    if total_weight <= 0:
        # Degenerado (todos los pesos en 0): reparto uniforme entre las vivas.
        renormalized = {name: 1.0 / len(live) for name in live} if live else {}
    else:
        renormalized = {name: w / total_weight for name, w in raw_weights.items()}

    score = sum(renormalized[name] * component_scores[name] for name in live)
    # Clamp: sólo protege contra el redondeo de punto flotante, la fórmula
    # ya garantiza [0,1] matemáticamente.
    score = min(1.0, max(0.0, score))
    return score, renormalized


# ---------------------------------------------------------------------------
# Capa 2 — Modo Negocio: sliders con piso de relevancia (doc 02 §5)
# ---------------------------------------------------------------------------


def apply_sliders(
    margin: float,
    turnover: float,
    private_label: float,
    promo: float = PROMO_WEIGHT_FIXED,
) -> ScoringWeights:
    """w_relevance = max(0.20, 1 − margen − rotación − marca_propia − promo).
    El resto se renormaliza después, en `combine_weighted_score`."""
    relevance = max(RELEVANCE_FLOOR, 1.0 - margin - turnover - private_label - promo)
    return ScoringWeights(
        relevance=relevance,
        margin=margin,
        turnover=turnover,
        private_label=private_label,
        promo=promo,
    )


# ---------------------------------------------------------------------------
# Orquestación por slot: filtro duro + señales + score (pipeline completo)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RelevanceInputs:
    """Entradas ya calculadas de relevancia para un producto. `text_match` se
    calcula fuera del motor (FTS5/BM25, doc 02 §3.1); si no se provee, el
    motor usa un fallback determinista por coincidencia de keywords."""

    attr_match: float
    text_match: float
    category_match: float


def _default_attr_match(product: Product, slot: BasketSlot) -> float:
    """En la práctica, un sobreviviente del filtro duro ya cumple TODOS los
    `required_attributes` con valor esperado no vacío (criterio 7 excluye lo
    contrario) -- este cálculo sigue existiendo por si alguien llama
    `score_slot` con `relevance_inputs` propios que no pasaron por
    `apply_hard_filter`, y como documentación de qué significa "matchear"."""
    if not slot.required_attributes and not slot.attribute_requirements:
        return 1.0
    satisfied = 0
    for key, expected in slot.required_attributes.items():
        actual = product.attributes.get(key)
        if actual is not None and (expected == "" or _attribute_value_matches(actual, expected)):
            satisfied += 1
    for requirement in slot.attribute_requirements:
        if evaluate_requirement(product, requirement):
            satisfied += 1
    total = len(slot.required_attributes) + len(slot.attribute_requirements)
    return satisfied / total


def _tokens(text: str) -> list[str]:
    """Minúsculas, sin tildes (la ñ también cae a n: "pañal" == "panal"), en
    palabras. Así "húmedas" y "humedas" son la misma palabra."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return re.findall(r"\w+", stripped)


def brand_key(text: str) -> str:
    """Forma comparable de una marca: "Coca-Cola", "coca cola" y "cocacola"
    dan lo mismo. El token "demo" de las etiquetas del catálogo sintético no
    es parte de la marca."""
    return "".join(t for t in _tokens(text) if t != "demo")


def mentions_brand(text: str, brand: str) -> bool:
    """La marca aparece en el texto como palabras contiguas completas, con o
    sin separadores ("coca-cola", "coca cola", "cocacola"). Nunca substring
    dentro de una palabra: "cola" no está en "colágeno"."""
    key = brand_key(brand)
    if not key:
        return False
    words = _tokens(text)
    return any(
        "".join(words[i:j]) == key
        for i in range(len(words))
        for j in range(i + 1, min(i + 5, len(words)) + 1)
    )


def matches_brand(product: Product, preferred_brands: Sequence[str]) -> bool:
    """Marca ausente no confirma nada: no coincide, pero tampoco se descarta."""
    if not product.brand:
        return False
    key = brand_key(product.brand)
    return any(brand_key(b) == key for b in preferred_brands if brand_key(b))


def _same_word(a: str, b: str) -> bool:
    """Igual, o una es el plural regular de la otra (+s, +es). Nunca prefijo
    ni substring: "aseo" no es "gaseosa" y "gas" no es "gaseosa"."""
    if a == b:
        return True
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    return long_ in (short + "s", short + "es")


def _keyword_in(keyword_tokens: Sequence[str], haystack_tokens: Sequence[str]) -> bool:
    """La keyword (una o varias palabras) aparece como secuencia contigua de
    palabras completas del texto del producto."""
    n = len(keyword_tokens)
    if n == 0:
        return False
    return any(
        all(_same_word(k, h) for k, h in zip(keyword_tokens, haystack_tokens[i : i + n]))
        for i in range(len(haystack_tokens) - n + 1)
    )


def matches_slot_text(product: Product, slot: BasketSlot) -> bool:
    """Mismo criterio léxico del ranking, también para acotar diagnósticos.

    El stock de una gaseosa no debe explicar por qué faltan pañales.
    """
    if not slot.keywords:
        return True
    haystack = _tokens(" ".join(filter(None, [product.name, product.description, product.brand])))
    return any(_keyword_in(_tokens(keyword), haystack) for keyword in slot.keywords)


def _text_matches(slot: BasketSlot, candidates: Sequence[Product]) -> dict[str, float]:
    """`text_match` de todos los candidatos de un slot, en una sola pasada:
    coincidencias de keywords / máximo de coincidencias del set.

    La coincidencia es por palabra completa (ver `_keyword_in`), no por
    substring: con `kw in haystack`, la keyword "aseo" encontraba "gaseosa",
    la gaseosa pasaba el filtro de texto y ganaba el slot "aseo del bebé" por
    margen."""
    if not slot.keywords:
        return {c.product_id: 1.0 for c in candidates}

    keyword_tokens = [_tokens(kw) for kw in slot.keywords]
    counts = {}
    for c in candidates:
        haystack = _tokens(" ".join(filter(None, [c.name, c.description, c.brand])))
        counts[c.product_id] = sum(1 for kt in keyword_tokens if _keyword_in(kt, haystack))

    max_count = max(counts.values(), default=0)
    if max_count == 0:
        return {pid: 0.0 for pid in counts}
    return {pid: n / max_count for pid, n in counts.items()}


def _default_category_match(product: Product, slot: BasketSlot) -> float:
    if slot.target_category is Category.UNKNOWN:
        return 1.0
    return 1.0 if product.category == slot.target_category else 0.0


def _resolve_relevance_inputs(
    product: Product,
    slot: BasketSlot,
    text_matches: Mapping[str, float],
    relevance_inputs: Mapping[str, RelevanceInputs] | None,
) -> RelevanceInputs:
    if relevance_inputs is not None and product.product_id in relevance_inputs:
        return relevance_inputs[product.product_id]
    return RelevanceInputs(
        attr_match=_default_attr_match(product, slot),
        text_match=text_matches[product.product_id],
        category_match=_default_category_match(product, slot),
    )


def _compute_relevance(ri: RelevanceInputs) -> float:
    return normalize_relevance(ri.attr_match, ri.text_match, ri.category_match)


def score_slot(
    candidates: Sequence[Product],
    slot: BasketSlot,
    weights: ScoringWeights,
    *,
    relevance_inputs: Mapping[str, RelevanceInputs] | None = None,
    store_id: str | None = None,
    budget_remaining: Decimal | None = None,
    compatibility_rules: Sequence[CompatibilityRule] = (),
    required_attribute_coverage: Mapping[str, float] | None = None,
    as_of: date | None = None,
) -> list[ScoredProduct]:
    """Pipeline completo para un slot: filtro duro (§2) sobre todos los
    candidatos, normalización + degradación (§3-4) sobre los que pasan, y
    orden descendente por score. Los descartados van al final con su
    `excluded_reason`."""

    results: list[ScoredProduct] = []
    survivors: list[Product] = []

    for product in candidates:
        hf = apply_hard_filter(
            product,
            slot,
            store_id=store_id,
            budget_remaining=budget_remaining,
            compatibility_rules=compatibility_rules,
            required_attribute_coverage=required_attribute_coverage,
        )
        if hf.passed:
            survivors.append(product)
        else:
            results.append(
                ScoredProduct(
                    product=product,
                    slot_id=slot.slot_id,
                    excluded_reason=hf.excluded_reason,
                    exclusion_detail=hf.exclusion_detail,
                    compatibility_checked=hf.compatibility_checked,
                    compatibility_passed=hf.compatibility_passed,
                )
            )

    if not survivors:
        return _order(results, slot)

    # Una sola pasada por slot: antes se recalculaba sobre todo el set para
    # cada producto (cuadrático sobre ~1000 candidatos con categoría UNKNOWN).
    text_matches = _text_matches(slot, survivors)
    relevance_inputs_resolved = {
        p.product_id: _resolve_relevance_inputs(p, slot, text_matches, relevance_inputs) for p in survivors
    }

    # Filtro semántico mínimo: no es uno de los 8 criterios binarios del doc 02
    # §2 (esos miran datos propios del producto), pero sin esto un producto sin
    # NINGUNA relación textual con el slot igual queda "recomendado" — con
    # required_attributes vacío (attr_match=1.0) y la categoría ya filtrada
    # (category_match=1.0), la mezcla 0.45/0.35/0.20 da un piso de 0.65 de
    # relevancia aunque text_match sea 0, y el producto gana por margen/
    # rotación en vez de por servir para lo que pidió el cliente.
    if slot.keywords:
        no_text_match = [p for p in survivors if relevance_inputs_resolved[p.product_id].text_match <= 0.0]
        for p in no_text_match:
            results.append(
                ScoredProduct(
                    product=p,
                    slot_id=slot.slot_id,
                    excluded_reason=ExclusionReason.NO_TEXT_MATCH,
                    exclusion_detail=(
                        f"Ninguno de los términos de búsqueda de '{slot.label}' aparece en el "
                        "nombre, descripción o marca del producto."
                    ),
                    compatibility_checked=bool(compatibility_rules),
                )
            )
        survivors = [p for p in survivors if p.product_id not in {x.product_id for x in no_text_match}]

    if not survivors:
        return _order(results, slot)

    relevance_scores = {p.product_id: _compute_relevance(relevance_inputs_resolved[p.product_id]) for p in survivors}

    # margin: min-max sobre los presentes, luego regla de cobertura.
    raw_margin = {
        p.product_id: (p.signals.margin_pct.value if p.signals.margin_pct is not None else None)
        for p in survivors
    }
    present_margin = {pid: v for pid, v in raw_margin.items() if v is not None}
    margin_minmax = minmax_normalize(present_margin)
    margin_input = {pid: margin_minmax.get(pid) for pid in raw_margin}
    margin = resolve_business_component(margin_input)

    # turnover: combina turnover_index (min-max) + inventory_age_days
    # (min-max, sin invertir: antigüedad alta -> mejor candidato a liquidar,
    # doc 02 §3.1). Si un producto sólo trae una de las dos, esa se lleva el
    # 100 % de la mezcla para ese producto.
    raw_turnover_idx = {
        p.product_id: (p.signals.turnover_index.value if p.signals.turnover_index is not None else None)
        for p in survivors
    }
    raw_age = {
        p.product_id: (
            p.signals.inventory_age_days.value if p.signals.inventory_age_days is not None else None
        )
        for p in survivors
    }
    turnover_idx_minmax = minmax_normalize({pid: v for pid, v in raw_turnover_idx.items() if v is not None})
    age_minmax = minmax_normalize({pid: v for pid, v in raw_age.items() if v is not None})

    turnover_input: dict[str, float | None] = {}
    for p in survivors:
        pid = p.product_id
        has_t = pid in turnover_idx_minmax
        has_a = pid in age_minmax
        if has_t and has_a:
            w_t, w_a = TURNOVER_MIX
            turnover_input[pid] = w_t * turnover_idx_minmax[pid] + w_a * age_minmax[pid]
        elif has_t:
            turnover_input[pid] = turnover_idx_minmax[pid]
        elif has_a:
            turnover_input[pid] = age_minmax[pid]
        else:
            turnover_input[pid] = None
    turnover = resolve_business_component(turnover_input)

    # private_label: binaria, luego regla de cobertura.
    pl_input = {
        p.product_id: (
            normalize_private_label(p.signals.is_private_label.value)
            if p.signals.is_private_label is not None
            else None
        )
        for p in survivors
    }
    private_label = resolve_business_component(pl_input)

    # promo: siempre derivable de Price, nunca ausente -> nunca muere.
    promo_values = {p.product_id: normalize_promo(p.price, as_of=as_of) for p in survivors}

    live_signals = ["relevance"]
    if margin.alive:
        live_signals.append("margin")
    if turnover.alive:
        live_signals.append("turnover")
    if private_label.alive:
        live_signals.append("private_label")
    live_signals.append("promo")

    for p in survivors:
        pid = p.product_id
        component_scores: dict[str, float] = {"relevance": relevance_scores[pid], "promo": promo_values[pid]}
        missing_signals: list[str] = []

        if margin.alive:
            component_scores["margin"] = margin.values[pid]
        else:
            missing_signals.append("margin")

        if turnover.alive:
            component_scores["turnover"] = turnover.values[pid]
        else:
            missing_signals.append("turnover")

        if private_label.alive:
            component_scores["private_label"] = private_label.values[pid]
        else:
            missing_signals.append("private_label")

        total_score, weights_applied = combine_weighted_score(component_scores, weights, live_signals)

        results.append(
            ScoredProduct(
                product=p,
                slot_id=slot.slot_id,
                total_score=total_score,
                component_scores=component_scores,
                weights_applied=weights_applied,
                missing_signals=missing_signals,
                compatibility_checked=bool(compatibility_rules),
            )
        )

    return _order(results, slot)


def _order(results: list[ScoredProduct], slot: BasketSlot) -> list[ScoredProduct]:
    """Marca pedida primero, sin tocar `total_score`: dentro de cada nivel
    decide el score normal (relevancia + señales comerciales)."""
    if slot.preferred_brands:
        results = [
            sp.model_copy(update={"matches_preferred_brand": matches_brand(sp.product, slot.preferred_brands)})
            for sp in results
        ]
    results.sort(
        key=lambda sp: (sp.excluded_reason is not None, sp.matches_preferred_brand is False, -sp.total_score)
    )
    return results
