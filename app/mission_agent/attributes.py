"""Valida especificaciones y marcas contra el registro y el texto original."""

from app.domain.schema import AttributeRequirement, MissionPlan
from app.domain.specifications import definition_for, evidence_matches, source_fragment_for_value
from app.engine.scoring import mentions_brand


def normalize_requirements(plan: MissionPlan) -> MissionPlan:
    slots = []
    for slot in plan.slots:
        requirements = [
            requirement.model_copy(update={
                "attribute": definition_for(requirement.attribute).key,
                # No eliminar una restricción sin respaldo: ampliaría la búsqueda.
                "source_text": requirement.source_text if evidence_matches(requirement, plan.raw_input) else "",
            })
            for requirement in slot.attribute_requirements
        ]
        for key, value in slot.required_attributes.items():
            canonical = definition_for(key).key
            if any(r.attribute == canonical for r in requirements):
                continue
            requirements.append(AttributeRequirement(
                attribute=canonical,
                operator="eq",
                value=value,
                source_text=source_fragment_for_value(value, plan.raw_input),
            ))
        # Una marca que el cliente no nombró se descarta: la preferencia es
        # blanda, así que quitarla sólo amplía el orden, nunca inventa nada.
        brands = [b for b in slot.preferred_brands if mentions_brand(plan.raw_input, b)]
        slots.append(slot.model_copy(update={
            "required_attributes": {},
            "attribute_requirements": requirements,
            "preferred_brands": brands,
        }))
    return plan.model_copy(update={"slots": slots})
