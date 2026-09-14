"""Especificaciones genéricas: talla, unidades, rangos y evidencia."""

from decimal import Decimal

import pytest

from app.db import get_connection
from app.domain.schema import (
    AttributeRequirement, Basket, BasketSlot, Category, ExclusionReason,
    MissionPlan, Price, Product, ResolvedSlot, ScoredProduct, ScoringWeights,
    StoreStock,
)
from app.domain.specifications import (
    AttributeDefinition, evaluate_requirement, extract_attributes,
)
from app.engine.scoring import score_slot
from app.mission_agent.attributes import normalize_requirements
from app.presentation.advisor_reply import recommendation_reply
from app.presentation.cart import CartState
from app.presentation.projector import project_groups
from app.services.basket_service import resolve_single_slot


def slot(label="Producto", **kwargs):
    return BasketSlot(slot_id="s", label=label, target_category=Category.GROCERY,
                      keywords=[label], **kwargs)


@pytest.mark.parametrize(("requirement", "attrs", "expected"), [
    (AttributeRequirement(attribute="size", value="M", source_text="talla M"), {"size": "m"}, True),
    (AttributeRequirement(attribute="capacity_l", operator="gte", value="500", unit="ml", source_text="500 ml"), {"capacity_l": 1}, True),
    (AttributeRequirement(attribute="capacity_l", operator="between", value="1", upper_value="2", unit="L", source_text="1 a 2 L"), {"capacity_l": 3}, False),
    (AttributeRequirement(attribute="supported_weight_kg", operator="contains", value="5", unit="kg", source_text="pesa 5kg"), {"min_weight_kg": 4, "max_weight_kg": 9}, True),
    (AttributeRequirement(attribute="supported_weight_kg", operator="contains", value="5", unit="kg", source_text="pesa 5kg"), {"min_weight_kg": 6, "max_weight_kg": 10}, False),
    (AttributeRequirement(attribute="supported_weight_kg", operator="contains", value="5", unit="kg", source_text="pesa 5kg"), {}, None),
])
def test_requirements_are_independent_of_product_type(requirement, attrs, expected):
    product = Product(product_id="p", name="Producto", category=Category.GROCERY,
                      price=Price(amount=Decimal("10")), attributes=attrs)
    assert evaluate_requirement(product, requirement) is expected


def test_name_extraction_is_registry_driven_and_marks_provenance():
    definition = AttributeDefinition(
        key="format", label="formato", name_pattern=r"\bformato\s+(?P<value>[A-Z]\d)\b"
    )
    attrs, sources = extract_attributes({}, "Producto formato A4", [definition])
    assert attrs == {"format": "A4"}
    assert sources["format"].value == "derived"


def test_catalog_exposes_declared_and_derived_metadata():
    with get_connection() as conn:
        tires = resolve_single_slot(conn, BasketSlot(
            slot_id="t", label="Llantas", target_category=Category.AUTO,
            keywords=["llanta"], required_attributes={"tire_size": "185/65R15"},
        ), ScoringWeights())
        sized = resolve_single_slot(conn, slot(
            "Pañales", attribute_requirements=[AttributeRequirement(
                attribute="size", value="M", source_text="talla M",
            )],
        ), ScoringWeights())
    assert tires.picked is not None
    assert tires.picked.product.attributes["tire_size"] == "185/65R15"
    assert sized.picked is not None
    assert sized.picked.product.attributes["size"].casefold() == "m"
    assert sized.picked.product.attribute_sources["size"].value == "derived"


def test_requirement_without_literal_evidence_fails_closed():
    requirement = AttributeRequirement(attribute="size", value="M", source_text="pesa 5kg")
    plan = normalize_requirements(MissionPlan(raw_input="pesa 5kg", slots=[slot(
        "Pañales", attribute_requirements=[requirement],
    )]))
    assert plan.slots[0].attribute_requirements[0].source_text == ""
    product = Product(product_id="p", name="Pañales talla M", category=Category.GROCERY,
                      price=Price(amount=Decimal("10")), attributes={"size": "M"})
    result = score_slot([product], plan.slots[0], ScoringWeights())[0]
    assert result.excluded_reason is ExclusionReason.MISSING_REQUIRED_ATTRIBUTE


def test_legacy_attribute_is_migrated_with_literal_evidence():
    plan = normalize_requirements(MissionPlan(
        raw_input="Necesito llantas 185/65R15 para mi auto.",
        slots=[BasketSlot(
            slot_id="t", label="Llantas", target_category=Category.AUTO,
            keywords=["llantas"], required_attributes={"tire_size": "185/65R15"},
        )],
    ))
    assert plan.slots[0].required_attributes == {}
    requirement = plan.slots[0].attribute_requirements[0]
    assert requirement.attribute == "tire_size"
    assert requirement.source_text == "Necesito llantas 185/65R15 para mi auto."


def test_legacy_inferred_value_is_migrated_without_evidence_and_fails_closed():
    plan = normalize_requirements(MissionPlan(
        raw_input="El bebé pesa 5kg.",
        slots=[slot("Pañales", required_attributes={"talla": "RN/P"})],
    ))
    requirement = plan.slots[0].attribute_requirements[0]
    assert requirement.attribute == "size"
    assert requirement.source_text == ""


def test_missing_metadata_is_omitted_and_explained_generically():
    requirement = AttributeRequirement(
        attribute="supported_weight_kg", operator="contains", value="5", unit="kg", source_text="pesa 5kg"
    )
    unresolved = ResolvedSlot(
        slot=slot("Pañales", attribute_requirements=[requirement]),
        most_common_rejection_reason=ExclusionReason.MISSING_REQUIRED_ATTRIBUTE,
    )
    basket = Basket(mission=MissionPlan(raw_input="pesa 5kg"), slots=[unresolved])
    assert project_groups(basket, CartState(), "m") == ()
    reply = recommendation_reply(basket)
    assert "peso admitido 5 kg" in reply and "falta esa información" in reply
    assert "atributo" not in reply


def test_stock_diagnosis_ignores_unrelated_products(monkeypatch):
    products = [Product(
        product_id="target", name="Filtro A4", category=Category.GROCERY,
        price=Price(amount=Decimal("10")),
        stock=[StoreStock(store_id="s", status="out_of_stock", qty=0)],
    )]
    products.extend(Product(product_id=f"other{i}", name="Arroz", category=Category.GROCERY,
                            price=Price(amount=Decimal("10"))) for i in range(5))
    monkeypatch.setattr("app.services.basket_service.candidates_for_category", lambda *_: products)
    result = resolve_single_slot(None, slot("Filtro"), ScoringWeights())
    assert result.most_common_rejection_reason is ExclusionReason.OUT_OF_STOCK
    assert [s.product.product_id for s in result.rejected] == ["target"]


@pytest.mark.parametrize(("requirement", "attrs", "expected"), [
    (AttributeRequirement(attribute="units_per_pack", value="12", source_text="paquete de 12"), {"units_per_pack": 12}, True),
    (AttributeRequirement(attribute="units_per_pack", value="12", source_text="paquete de 12"), {"units_per_pack": 6}, False),
    (AttributeRequirement(attribute="units_per_pack", value="12", source_text="paquete de 12"), {}, None),
    (AttributeRequirement(attribute="volume_ml", value="1.5", unit="l", source_text="de 1.5 l"), {"volume_ml": 1500}, True),
    (AttributeRequirement(attribute="sugar_free", value="sí", source_text="sin azúcar"), {"sugar_free": "Sí"}, True),
])
def test_presentation_specifications(requirement, attrs, expected):
    product = Product(product_id="p", name="Producto", category=Category.GROCERY,
                      price=Price(amount=Decimal("10")), attributes=attrs)
    assert evaluate_requirement(product, requirement) is expected


def test_pack_requirement_keeps_only_the_matching_pack():
    plan = normalize_requirements(MissionPlan(raw_input="galletas oreo paquete de 12", slots=[slot(
        "Galletas",
        attribute_requirements=[AttributeRequirement(attribute="units_per_pack", value="12", source_text="paquete de 12")],
        preferred_brands=["Oreo"],
    )]))
    products = [
        Product(product_id=f"oreo-{n}", name=f"Galletas Oreo x{n}", brand="Oreo", category=Category.GROCERY,
                price=Price(amount=Decimal(n)), attributes={"units_per_pack": n})
        for n in (6, 12)
    ]
    rs = resolve_single_slot_from(products, plan.slots[0])
    assert rs.picked is not None and rs.picked.product.product_id == "oreo-12"
    assert rs.alternatives == []
    assert rs.preferred_brand_found is True


def resolve_single_slot_from(products, basket_slot):
    scored = score_slot(products, basket_slot, ScoringWeights())
    recommended = [sp for sp in scored if sp.is_recommended]
    return ResolvedSlot(slot=basket_slot, picked=recommended[0] if recommended else None, alternatives=recommended[1:])


def test_brand_is_kept_only_when_the_customer_named_it():
    plan = normalize_requirements(MissionPlan(raw_input="quiero comprar coca-cola para la fiesta", slots=[slot(
        "Gaseosa", preferred_brands=["Coca-Cola", "Pepsi"],
    )]))
    assert plan.slots[0].preferred_brands == ["Coca-Cola"]
