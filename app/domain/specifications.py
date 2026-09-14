"""Registro y comparación de especificaciones, sin tipos de producto.

Operadores y unidades genéricos; claves, alias y fuentes declaradas como datos.
"""
from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.schema import AttributeRequirement, Product, SignalSource


class AttributeDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    key: str
    label: str
    aliases: list[str] = Field(default_factory=list)
    kind: Literal["text", "number", "range"] = "text"
    unit: str | None = None
    unit_factors: dict[str, float] = Field(default_factory=dict)
    minimum_attribute: str | None = None
    maximum_attribute: str | None = None
    name_pattern: str | None = None

    @model_validator(mode="after")
    def _validate_definition(self):
        if self.kind == "range" and not (self.minimum_attribute and self.maximum_attribute):
            raise ValueError("Un intervalo requiere sus dos atributos límite")
        if self.name_pattern and "value" not in re.compile(self.name_pattern).groupindex:
            raise ValueError("La extracción requiere un grupo 'value'")
        if any(not math.isfinite(v) or v <= 0 for v in self.unit_factors.values()):
            raise ValueError("Las conversiones deben ser positivas y finitas")
        return self


@lru_cache(maxsize=1)
def attribute_definitions() -> tuple[AttributeDefinition, ...]:
    path = Path(__file__).resolve().parents[1] / "data" / "attribute_definitions.json"
    definitions = tuple(AttributeDefinition.model_validate(raw) for raw in json.loads(path.read_text()))
    names = [name.casefold() for d in definitions for name in [d.key, *d.aliases]]
    if len(names) != len(set(names)):
        raise ValueError("Atributos o alias duplicados")
    return definitions


def definition_for(key: str, definitions=None) -> AttributeDefinition:
    for definition in attribute_definitions() if definitions is None else definitions:
        if key.casefold() in [definition.key.casefold(), *(a.casefold() for a in definition.aliases)]:
            return definition
    return AttributeDefinition(key=key, label=key)


def extract_attributes(attributes: dict, name: str, definitions=None) -> tuple[dict, dict[str, SignalSource]]:
    result = dict(attributes)
    sources = {}
    for definition in attribute_definitions() if definitions is None else definitions:
        if result.get(definition.key) is not None:
            continue
        declared = [attributes[a] for a in definition.aliases if attributes.get(a) is not None]
        if declared:
            if all(str(v).strip().casefold() == str(declared[0]).strip().casefold() for v in declared):
                result[definition.key] = declared[0]
            continue  # no reemplazar datos estructurados contradictorios con el nombre
        if definition.name_pattern:
            matches = list(re.finditer(definition.name_pattern, name, re.IGNORECASE))
            values = {m["value"].strip().casefold() for m in matches}
            if len(values) == 1:
                result[definition.key] = matches[0]["value"].strip()
                sources[definition.key] = SignalSource.DERIVED
    return result, sources


def numeric_value(raw, definition: AttributeDefinition, unit: str | None = None) -> float | None:
    match = re.fullmatch(r"\s*([+-]?\d+(?:[.,]\d+)?)\s*([^\d\s].*?)?\s*", str(raw))
    if not match:
        return None
    suffix = (match[2] or "").strip().casefold()
    declared_unit = (unit or "").strip().casefold()
    if suffix and declared_unit and suffix != declared_unit:
        return None
    effective_unit = suffix or declared_unit or (definition.unit or "").casefold()
    if effective_unit:
        factor = definition.unit_factors.get(effective_unit)
        if factor is None:
            return None
    else:
        factor = 1
    value = float(match[1].replace(",", ".")) * factor
    return value if math.isfinite(value) else None


def evaluate_requirement(product: Product, requirement: AttributeRequirement, definitions=None) -> bool | None:
    """True cumple, False contradice, None no se puede verificar."""
    definition = definition_for(requirement.attribute, definitions)
    expected = requirement.value
    if definition.kind == "range":
        if requirement.operator != "contains":
            return None
        lo = numeric_value(product.attributes.get(definition.minimum_attribute), definition)
        hi = numeric_value(product.attributes.get(definition.maximum_attribute), definition)
        target = numeric_value(expected, definition, requirement.unit)
        if lo is None or hi is None or target is None or lo > hi:
            return None
        return lo <= target <= hi
    actual = product.attributes.get(definition.key)
    if actual is None:
        return None
    if requirement.operator == "eq" and expected == "":
        return True
    if definition.kind == "text":
        if requirement.operator != "eq" or requirement.unit:
            return None
        return str(actual).strip().casefold() == expected.strip().casefold()
    value = numeric_value(actual, definition)
    target = numeric_value(expected, definition, requirement.unit)
    if value is None or target is None:
        return None
    if requirement.operator == "eq":
        return math.isclose(value, target, rel_tol=1e-9, abs_tol=1e-9)
    if requirement.operator == "gte":
        return value >= target
    if requirement.operator == "lte":
        return value <= target
    if requirement.operator == "between":
        upper = numeric_value(requirement.upper_value, definition, requirement.unit)
        return None if upper is None or target > upper else target <= value <= upper
    return None


def evidence_matches(requirement: AttributeRequirement, request_text: str) -> bool:
    """Una talla inferida no se vuelve explícita por citar un peso del usuario."""
    source = requirement.source_text.strip()
    if not source or source.casefold() not in request_text.casefold():
        return False
    values = [requirement.value]
    if requirement.upper_value is not None:
        values.append(requirement.upper_value)
    for value in values:
        pattern = r"(?<!\w)" + re.escape(value.strip()).replace(r"\ ", r"\s+")
        pattern += r"(?![\d.,])" if re.fullmatch(r"[+-]?\d+(?:[.,]\d+)?", value) else r"(?!\w)"
        if not re.search(pattern, source, re.IGNORECASE):
            return False
    return True


def source_fragment_for_value(value: str, request_text: str) -> str:
    """Devuelve la cláusula literal que contiene un valor, o vacío.

    No interpreta semántica ni convierte unidades; sólo aporta trazabilidad
    para migrar el contrato anterior de atributos exactos.
    """
    pattern = r"(?<!\w)" + re.escape(value.strip()).replace(r"\ ", r"\s+")
    pattern += r"(?![\d.,])" if re.fullmatch(r"[+-]?\d+(?:[.,]\d+)?", value) else r"(?!\w)"
    for fragment in re.split(r"[\n;]|(?<=[.!?])\s+", request_text):
        if re.search(pattern, fragment, re.IGNORECASE):
            return fragment.strip()
    return ""
