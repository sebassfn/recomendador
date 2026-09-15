"""Tests del motor de scoring (docs/02-motor-de-scoring.md).

Los 10 casos son los de docs/07-herramientas-y-comandos.md §4. Los 3
primeros reproducen los ejemplos numéricos resueltos del doc 02 §6 —
los números del doc son la verdad: si el motor no los reproduce, el bug
está acá, no en el doc.
"""

from __future__ import annotations

import random
import statistics
from decimal import Decimal

import pytest

from app.domain.schema import (
    BasketSlot,
    BusinessSignals,
    Category,
    ExclusionReason,
    Price,
    Product,
    ScoringWeights,
    Signal,
    SignalSource,
    StoreStock,
)
from app.engine.scoring import (
    RELEVANCE_FLOOR,
    SIGNAL_NAMES,
    apply_sliders,
    brand_key,
    mentions_brand,
    combine_weighted_score,
    minmax_normalize,
    resolve_business_component,
    score_slot,
)

TOL = 1e-3


def make_product(
    product_id: str,
    *,
    category: Category = Category.GROCERY,
    margin: float | None = None,
    turnover_index: float | None = None,
    inventory_age_days: float | None = None,
    is_private_label: bool | None = None,
    price: str = "100.00",
    promo: str | None = None,
    name: str | None = None,
    attributes: dict[str, str] | None = None,
    brand: str | None = None,
    stock: list[StoreStock] | None = None,
) -> Product:
    return Product(
        product_id=product_id,
        name=name or f"Producto {product_id}",
        brand=brand,
        stock=stock or [],
        category=category,
        price=Price(amount=Decimal(price), promo_amount=Decimal(promo) if promo else None),
        attributes=attributes or {},
        signals=BusinessSignals(
            margin_pct=Signal(value=margin) if margin is not None else None,
            turnover_index=Signal(value=turnover_index) if turnover_index is not None else None,
            inventory_age_days=(
                Signal(value=inventory_age_days) if inventory_age_days is not None else None
            ),
            is_private_label=(
                Signal(value=is_private_label) if is_private_label is not None else None
            ),
        ),
    )


# ---------------------------------------------------------------------------
# 1-3: Los 3 ejemplos numéricos del doc 02 §6
# ---------------------------------------------------------------------------


def test_ejemplo_1_todas_las_senales_pesos_por_defecto():
    weights = ScoringWeights()  # rel .50 · mar .20 · rot .15 · mp .08 · promo .07 -> suma 1
    productos = {
        "A": {"relevance": 0.92, "margin": 0.30, "turnover": 0.55, "private_label": 0.0, "promo": 1.0},
        "B": {"relevance": 0.78, "margin": 0.85, "turnover": 0.70, "private_label": 1.0, "promo": 0.0},
        "C": {"relevance": 0.85, "margin": 0.40, "turnover": 0.20, "private_label": 0.0, "promo": 0.0},
    }
    scores = {pid: combine_weighted_score(comp, weights)[0] for pid, comp in productos.items()}

    assert scores["A"] == pytest.approx(0.6725, abs=TOL)
    assert scores["B"] == pytest.approx(0.7450, abs=TOL)
    assert scores["C"] == pytest.approx(0.5350, abs=TOL)
    # Orden: B > A > C. La marca propia gana pese a ser menos relevante que A.
    assert scores["B"] > scores["A"] > scores["C"]


def test_ejemplo_2_degradacion_de_margen_y_mediana_vs_cero():
    weights = ScoringWeights()

    # 2a: cobertura de margen 0% -> muere, S = {rel, rot, mp, promo}.
    live_sin_margen = ["relevance", "turnover", "private_label", "promo"]
    D = {"relevance": 0.60, "turnover": 0.90, "private_label": 1.0, "promo": 0.0}
    E = {"relevance": 0.80, "turnover": 0.20, "private_label": 0.0, "promo": 1.0}

    d_score, d_w = combine_weighted_score(D, weights, live_sin_margen)
    e_score, e_w = combine_weighted_score(E, weights, live_sin_margen)

    assert d_w["relevance"] == pytest.approx(0.6250, abs=TOL)
    assert d_w["turnover"] == pytest.approx(0.1875, abs=TOL)
    assert d_w["private_label"] == pytest.approx(0.1000, abs=TOL)
    assert d_w["promo"] == pytest.approx(0.0875, abs=TOL)
    assert sum(d_w.values()) == pytest.approx(1.0, abs=1e-9)

    assert d_score == pytest.approx(0.6438, abs=TOL)
    assert e_score == pytest.approx(0.6250, abs=TOL)
    assert d_score > e_score  # D (0.644) > E (0.625)

    # 2b: contraejemplo — cobertura 70%, margen vive, mediana del set = 0.55.
    # E no trae margen: imputarle la mediana (nunca 0) cambia el resultado.
    D_real = {"relevance": 0.60, "margin": 0.62, "turnover": 0.90, "private_label": 1.0, "promo": 0.0}
    E_mediana = {"relevance": 0.80, "margin": 0.55, "turnover": 0.20, "private_label": 0.0, "promo": 1.0}
    E_cero = {"relevance": 0.80, "margin": 0.00, "turnover": 0.20, "private_label": 0.0, "promo": 1.0}

    d_score2, _ = combine_weighted_score(D_real, weights)
    e_mediana_score, _ = combine_weighted_score(E_mediana, weights)
    e_cero_score, _ = combine_weighted_score(E_cero, weights)

    assert d_score2 == pytest.approx(0.6390, abs=TOL)
    assert e_mediana_score == pytest.approx(0.6100, abs=TOL)
    assert e_cero_score == pytest.approx(0.5000, abs=TOL)

    # Usar cero le cuesta a E ~0.11 puntos y no es lo que hace el motor.
    assert e_mediana_score - e_cero_score == pytest.approx(0.11, abs=TOL)


def test_ejemplo_3_el_slider_invierte_el_top_2():
    F = {"relevance": 0.95, "margin": 0.35, "turnover": 0.30, "private_label": 0.0, "promo": 0.0}
    G = {"relevance": 0.50, "margin": 0.70, "turnover": 0.60, "private_label": 1.0, "promo": 0.0}

    # Con pesos por defecto, F gana.
    default_weights = ScoringWeights()
    f_score, _ = combine_weighted_score(F, default_weights)
    g_score, _ = combine_weighted_score(G, default_weights)
    assert f_score == pytest.approx(0.5900, abs=TOL)
    assert g_score == pytest.approx(0.5600, abs=TOL)
    assert f_score > g_score

    # El jurado sube los sliders: margen 0.45 · liquidar 0.30 · marca propia 0.20.
    # w_rel crudo = max(0.20, 1 - 0.45 - 0.30 - 0.20 - 0.07) = max(0.20, -0.02) = 0.20 (piso activo).
    slider_weights = apply_sliders(margin=0.45, turnover=0.30, private_label=0.20)
    assert slider_weights.relevance == pytest.approx(RELEVANCE_FLOOR)

    f_score2, f_w2 = combine_weighted_score(F, slider_weights)
    g_score2, g_w2 = combine_weighted_score(G, slider_weights)

    assert f_w2["relevance"] == pytest.approx(0.1639, abs=TOL)
    assert f_w2["margin"] == pytest.approx(0.3689, abs=TOL)
    assert f_w2["turnover"] == pytest.approx(0.2459, abs=TOL)
    assert f_w2["private_label"] == pytest.approx(0.1639, abs=TOL)
    assert f_w2["promo"] == pytest.approx(0.0574, abs=TOL)

    assert f_score2 == pytest.approx(0.3586, abs=TOL)
    assert g_score2 == pytest.approx(0.6515, abs=TOL)
    # Se invierte: G desplaza a F.
    assert g_score2 > f_score2


# ---------------------------------------------------------------------------
# 4: Señal ausente en todo el set -> se elimina y los pesos renormalizan a 1.0
# ---------------------------------------------------------------------------


def test_senal_ausente_en_todo_el_set_se_elimina_y_renormaliza():
    slot = BasketSlot(slot_id="s1", label="Slot", target_category=Category.GROCERY)
    productos = [
        make_product(
            f"p{i}",
            turnover_index=float(i),
            inventory_age_days=float(10 - i),
            is_private_label=(i % 2 == 0),
            # margin_pct nunca se declara -> cobertura 0% para todo el set
        )
        for i in range(5)
    ]

    resultados = score_slot(productos, slot, ScoringWeights())

    assert len(resultados) == 5
    for sp in resultados:
        assert "margin" in sp.missing_signals
        assert "margin" not in sp.component_scores
        assert "margin" not in sp.weights_applied
        assert sum(sp.weights_applied.values()) == pytest.approx(1.0, abs=1e-9)


# ---------------------------------------------------------------------------
# 5: Cobertura 70% -> se imputa la mediana, nunca 0 (contraejemplo doc 02 §6 Ej. 2b)
# ---------------------------------------------------------------------------


def test_cobertura_70_por_ciento_imputa_mediana_nunca_cero():
    presentes = {"p1": 0.1, "p2": 0.9, "p3": 0.5, "p4": 0.3, "p5": 0.7, "p6": 0.2, "p7": 0.8}
    normalizado = {**presentes, "p8": None, "p9": None, "p10": None}  # 7/10 = 70% cobertura

    resuelto = resolve_business_component(normalizado)
    mediana_esperada = statistics.median(presentes.values())

    assert resuelto.alive is True
    for pid in ("p8", "p9", "p10"):
        assert resuelto.values[pid] == pytest.approx(mediana_esperada)
        assert resuelto.values[pid] != 0.0
        assert resuelto.sources[pid] is SignalSource.DERIVED
    for pid in presentes:
        assert resuelto.sources[pid] is SignalSource.REAL


# ---------------------------------------------------------------------------
# 6: Umbral de cobertura 60%: 59% mata la señal, 61% la mantiene
# ---------------------------------------------------------------------------


def test_umbral_de_cobertura_60_por_ciento():
    def con_cobertura(n_presentes: int, total: int = 100) -> dict[str, float | None]:
        return {f"p{i}": (1.0 if i < n_presentes else None) for i in range(total)}

    assert resolve_business_component(con_cobertura(59)).alive is False
    assert resolve_business_component(con_cobertura(60)).alive is True  # borde exacto, "al menos 60%"
    assert resolve_business_component(con_cobertura(61)).alive is True


# ---------------------------------------------------------------------------
# 7: Piso de w_relevance = 0.20 con los 3 sliders al máximo
# ---------------------------------------------------------------------------


def test_piso_de_relevancia_con_sliders_al_maximo():
    # Rangos máximos del doc 02 §5: margen 0.50 · liquidar 0.40 · marca propia 0.30.
    weights = apply_sliders(margin=0.50, turnover=0.40, private_label=0.30)

    assert weights.relevance == pytest.approx(RELEVANCE_FLOOR)

    componentes = {"relevance": 1.0, "margin": 0.0, "turnover": 0.0, "private_label": 0.0, "promo": 0.0}
    _, aplicados = combine_weighted_score(componentes, weights)
    suma_cruda = 0.20 + 0.50 + 0.40 + 0.30 + 0.07
    assert aplicados["relevance"] == pytest.approx(0.20 / suma_cruda)
    # El negocio no puede secuestrar el ranking: relevancia sigue teniendo peso.
    assert aplicados["relevance"] > 0.0


# ---------------------------------------------------------------------------
# 8: score in [0,1] siempre, con cualquier combinación de señales
# ---------------------------------------------------------------------------


def test_score_siempre_en_0_1():
    rng = random.Random(1234)
    for _ in range(300):
        vivas = set(rng.sample(SIGNAL_NAMES, k=rng.randint(1, len(SIGNAL_NAMES))))
        vivas.add("relevance")
        componentes = {name: rng.random() for name in vivas}
        weights = apply_sliders(
            margin=rng.uniform(0.0, 0.5),
            turnover=rng.uniform(0.0, 0.4),
            private_label=rng.uniform(0.0, 0.3),
        )
        score, aplicados = combine_weighted_score(componentes, weights, list(vivas))
        assert 0.0 <= score <= 1.0
        assert sum(aplicados.values()) == pytest.approx(1.0, abs=1e-9)


# ---------------------------------------------------------------------------
# 9: Candidate set < 3 -> min-max degrada a 0.5 constante
# ---------------------------------------------------------------------------


def test_minmax_degrada_a_0_5_con_menos_de_tres():
    assert minmax_normalize({"a": 10.0}) == {"a": 0.5}
    assert minmax_normalize({"a": 1.0, "b": 999.0}) == {"a": 0.5, "b": 0.5}

    # Con 3 o más, min-max normal (no degrada).
    normal = minmax_normalize({"a": 0.0, "b": 5.0, "c": 10.0})
    assert normal == {"a": 0.0, "b": 0.5, "c": 1.0}


# ---------------------------------------------------------------------------
# 10: Product con sólo los 4 campos obligatorios recorre el motor entero
# ---------------------------------------------------------------------------


def test_producto_minimo_recorre_el_motor_entero():
    producto = Product(
        product_id="min-1",
        name="Producto mínimo",
        category=Category.GROCERY,
        price=Price(amount=Decimal("19.90")),
    )
    slot = BasketSlot(slot_id="slot-1", label="Necesidad genérica")

    resultados = score_slot([producto], slot, ScoringWeights())

    assert len(resultados) == 1
    scored = resultados[0]
    assert scored.is_recommended is True
    assert 0.0 <= scored.total_score <= 1.0
    assert set(scored.missing_signals) == {"margin", "turnover", "private_label"}
    assert "margin" not in scored.component_scores
    assert sum(scored.weights_applied.values()) == pytest.approx(1.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Coincidencia de texto: palabras completas, sin tildes, plural tolerado
# ---------------------------------------------------------------------------


def _slot(*keywords: str) -> BasketSlot:
    return BasketSlot(slot_id="s", label="Aseo del bebé", target_category=Category.GROCERY, keywords=list(keywords))


def _by_id(resultados):
    return {sp.product.product_id: sp for sp in resultados}


def test_keyword_no_coincide_dentro_de_otra_palabra():
    """"aseo" está dentro de "gaseosa" como substring, pero no es la palabra."""
    gaseosa = make_product("gaseosa", name="Gaseosa bebida familiar 3L")
    kit = make_product("kit", name="Kit de aseo personal")

    res = _by_id(score_slot([gaseosa, kit], _slot("aseo"), ScoringWeights()))

    assert res["gaseosa"].excluded_reason is ExclusionReason.NO_TEXT_MATCH
    assert res["kit"].is_recommended


def test_keyword_multipalabra_tolera_sinonimo_parcial():
    """La mitad (o más) de las palabras significativas de la keyword alcanza:
    "vegetales para asar" matchea "Verduras mixtas para asar" (comparten
    "para" y "asar"; "para" es stopword y no cuenta, "asar" sí). No debe
    matchear un producto que sólo comparte una palabra de relleno."""
    verduras = make_product("verduras", name="Verduras mixtas para asar a la parrilla")
    solo_relleno = make_product("solo-relleno", name="Salsa para pastas")

    res = _by_id(score_slot([verduras, solo_relleno], _slot("vegetales para asar"), ScoringWeights()))

    assert res["verduras"].is_recommended
    assert res["solo-relleno"].excluded_reason is ExclusionReason.NO_TEXT_MATCH


def test_keyword_ignora_tildes_y_mayusculas():
    toallitas = make_product("t", name="Toallitas Húmedas x80")

    res = _by_id(score_slot([toallitas], _slot("toallitas humedas"), ScoringWeights()))

    assert res["t"].is_recommended


@pytest.mark.parametrize(
    ("keyword", "name"),
    [("pañal", "Pañales talla M x30"), ("pañales", "Pañal talla M"), ("toallita", "Toallitas húmedas"), ("bebe", "Jabón para bebés")],
)
def test_keyword_tolera_singular_y_plural(keyword, name):
    p = make_product("p", name=name)

    res = _by_id(score_slot([p], _slot(keyword), ScoringWeights()))

    assert res["p"].is_recommended


def test_gaseosa_de_mayor_margen_no_gana_el_slot_de_aseo_del_bebe():
    """Caso real reportado: con coincidencia por substring la gaseosa entraba
    (por "aseo") y ganaba por margen a pañales y toallitas."""
    candidatos = [
        make_product("gaseosa", name="Gaseosa bebida familiar 3L", margin=0.38, turnover_index=3.0),
        make_product("panales", name="Pañales talla M x30", margin=0.33, turnover_index=3.0),
        make_product("toallitas", name="Toallitas húmedas x80", margin=0.34, turnover_index=3.0),
    ]

    res = score_slot(candidatos, _slot("pañales", "toallitas", "aseo"), ScoringWeights())

    recomendados = [sp.product.product_id for sp in res if sp.is_recommended]
    assert "gaseosa" not in recomendados
    assert set(recomendados) == {"panales", "toallitas"}


# ---------------------------------------------------------------------------
# Atributo requerido con VALOR específico (talla/medida/tipo), no sólo
# presencia -- criterio 7b del doc 02 §2. Genérico: cualquier categoría con
# un atributo de este tipo (llantas: tire_size; aceite de motor: viscosity;
# batería: voltage...) se beneficia igual, sin código específico por rubro.
# ---------------------------------------------------------------------------


def _slot_talla(**required_attributes: str) -> BasketSlot:
    return BasketSlot(
        slot_id="s", label="Necesidad con talla", target_category=Category.AUTO, required_attributes=required_attributes
    )


def test_producto_con_talla_incorrecta_se_excluye_no_solo_pierde_puntaje():
    """Caso real reportado: una llanta 195/65R15 para un auto que necesita
    185/65R15 quedaba "recomendada" (con menos puntaje) en vez de excluida."""
    candidatos = [
        make_product("correcta", category=Category.AUTO, attributes={"tire_size": "185/65R15"}),
        make_product("incorrecta", category=Category.AUTO, attributes={"tire_size": "195/65R15"}),
    ]

    res = _by_id(score_slot(candidatos, _slot_talla(tire_size="185/65R15"), ScoringWeights()))

    assert res["correcta"].is_recommended
    assert res["incorrecta"].excluded_reason is ExclusionReason.WRONG_REQUIRED_ATTRIBUTE_VALUE
    assert "195/65R15" in res["incorrecta"].exclusion_detail
    assert "185/65R15" in res["incorrecta"].exclusion_detail


def test_talla_incorrecta_nunca_se_relaja_por_cobertura():
    """A diferencia de un atributo AUSENTE, uno presente pero equivocado
    excluye siempre -- ninguna cobertura de catálogo lo relaja (doc 02 §2)."""
    incorrecta = make_product("incorrecta", category=Category.AUTO, attributes={"viscosity": "10W40"})

    res = _by_id(
        score_slot(
            [incorrecta],
            _slot_talla(viscosity="5W30"),
            ScoringWeights(),
            required_attribute_coverage={"viscosity": 0.0},  # cobertura mínima posible
        )
    )

    assert res["incorrecta"].excluded_reason is ExclusionReason.WRONG_REQUIRED_ATTRIBUTE_VALUE


def test_atributo_ausente_sigue_siendo_distinto_y_relajable():
    sin_dato = make_product("sin-dato", category=Category.AUTO, attributes={})

    excluye_por_default = _by_id(score_slot([sin_dato], _slot_talla(tire_size="185/65R15"), ScoringWeights()))
    assert excluye_por_default["sin-dato"].excluded_reason is ExclusionReason.MISSING_REQUIRED_ATTRIBUTE

    relajado = _by_id(
        score_slot(
            [sin_dato],
            _slot_talla(tire_size="185/65R15"),
            ScoringWeights(),
            required_attribute_coverage={"tire_size": 0.1},  # < 50 %
        )
    )
    assert relajado["sin-dato"].is_recommended


def test_valor_esperado_vacio_sigue_pidiendo_solo_presencia():
    """`required_attributes={"tire_size": ""}` (el LLM no supo la medida
    exacta, sólo que el slot necesita una) sigue aceptando cualquier valor."""
    cualquier_talla = make_product("p", category=Category.AUTO, attributes={"tire_size": "205/55R16"})

    res = _by_id(score_slot([cualquier_talla], _slot_talla(tire_size=""), ScoringWeights()))

    assert res["p"].is_recommended


def test_comparacion_de_talla_ignora_mayusculas_y_espacios():
    p = make_product("p", category=Category.AUTO, attributes={"tire_size": " 185/65r15 "})

    res = _by_id(score_slot([p], _slot_talla(tire_size="185/65R15"), ScoringWeights()))

    assert res["p"].is_recommended


# ---------------------------------------------------------------------------
# Preferencia de marca: nivel de orden, no filtro ni puntaje
# ---------------------------------------------------------------------------


def _slot_cola(*brands: str) -> BasketSlot:
    return BasketSlot(
        slot_id="cola",
        label="Gaseosa cola",
        target_category=Category.GROCERY,
        keywords=["gaseosa", "cola"],
        preferred_brands=list(brands),
    )


def _colas() -> list[Product]:
    generica = make_product(
        "generica", name="Gaseosa cola 2L", brand="Mercado Casa (DEMO)",
        margin=0.90, turnover_index=9.0, price="5.00", promo="4.00",
    )
    cocas = [
        make_product(f"coca-{m}", name=f"Gaseosa cola Coca-Cola {m}", brand="Coca-Cola",
                     margin=m, turnover_index=2.0, price="8.00")
        for m in (0.10, 0.30, 0.50)
    ]
    return [generica, *cocas]


def test_marca_pedida_va_primero_aunque_otra_tenga_mas_score():
    res = score_slot(_colas(), _slot_cola("coca cola"), ScoringWeights())
    ids = [sp.product.product_id for sp in res]
    by_id = _by_id(res)

    assert ids[:3] == ["coca-0.5", "coca-0.3", "coca-0.1"]
    assert ids[3] == "generica"
    assert by_id["generica"].total_score > by_id["coca-0.5"].total_score
    assert by_id["coca-0.5"].matches_preferred_brand is True
    assert by_id["generica"].matches_preferred_brand is False


def test_marca_no_cambia_el_total_score():
    con_marca = _by_id(score_slot(_colas(), _slot_cola("Coca-Cola"), ScoringWeights()))
    sin_marca = _by_id(score_slot(_colas(), _slot_cola(), ScoringWeights()))

    for pid in con_marca:
        assert con_marca[pid].total_score == pytest.approx(sin_marca[pid].total_score)


def test_sin_marca_pedida_el_orden_es_el_de_siempre():
    res = score_slot(_colas(), _slot_cola(), ScoringWeights())

    assert res[0].product.product_id == "generica"
    assert all(sp.matches_preferred_brand is None for sp in res)


def test_marca_pedida_sin_stock_sigue_excluida():
    agotada = make_product(
        "coca-agotada", name="Gaseosa cola Coca-Cola", brand="Coca-Cola",
        stock=[StoreStock(store_id="__ALL__", status="out_of_stock", qty=0)],
    )
    generica = make_product("generica", name="Gaseosa cola 2L", brand="Casa")

    res = score_slot([agotada, generica], _slot_cola("Coca-Cola"), ScoringWeights())

    assert res[0].product.product_id == "generica"
    assert res[1].excluded_reason is ExclusionReason.OUT_OF_STOCK
    assert res[1].matches_preferred_brand is True


def test_marca_no_salta_el_filtro_de_texto():
    helado = make_product("oreo-helado", name="Helado sabor Oreo", brand="Oreo")
    galleta = make_product("galleta", name="Galletas de chocolate", brand="Casa")
    slot = BasketSlot(slot_id="g", label="Galletas", target_category=Category.GROCERY,
                      keywords=["galletas"], preferred_brands=["Oreo"])

    res = _by_id(score_slot([helado, galleta], slot, ScoringWeights()))

    assert res["oreo-helado"].excluded_reason is ExclusionReason.NO_TEXT_MATCH
    assert res["galleta"].is_recommended


@pytest.mark.parametrize("a, b", [("Coca-Cola", "coca cola"), ("Coca-Cola", "COCACOLA"), ("Inca Kola (demo)", "inca kola")])
def test_brand_key_ignora_separadores_mayusculas_y_demo(a, b):
    assert brand_key(a) == brand_key(b)


@pytest.mark.parametrize(
    "text, brand, expected",
    [
        ("quiero comprar coca-cola", "Coca-Cola", True),
        ("quiero comprar cocacola", "Coca Cola", True),
        ("galletas Oreo paquete de 12", "oreo", True),
        ("gaseosa cola de 2 litros", "Coca-Cola", False),
        ("colágeno en polvo", "cola", False),
    ],
)
def test_mentions_brand(text, brand, expected):
    assert mentions_brand(text, brand) is expected
