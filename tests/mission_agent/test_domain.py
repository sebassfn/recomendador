"""`RetailMissionDomain`: el plugin que le enseña a `app/agent/` (genérico)
qué es una misión de compra de este retailer. Reemplaza a los tests que antes
vivían en `tests/test_interpreter.py`.
"""

from __future__ import annotations

import pytest

from app.agent.contracts import AgentMode, AgentRequest
from app.domain.schema import Category, MissionKind
from app.mission_agent.domain import RetailMissionDomain
from app.mission_agent.seeds import SEED_MISSION_FILES

domain = RetailMissionDomain()


def _request(text: str, *, mode: AgentMode = AgentMode.START, **kwargs) -> AgentRequest:
    return AgentRequest(user_id="u1", message=text, mode=mode, **kwargs)


@pytest.mark.parametrize("text", list(SEED_MISSION_FILES))
def test_shortcut_hits_for_exact_demo_text(text: str) -> None:
    hit = domain.shortcut(_request(text))
    assert hit is not None
    assert len(hit["slots"]) > 0


def test_shortcut_is_exact_match_not_fuzzy() -> None:
    assert domain.shortcut(_request("Me voy con los niños a la playa")) is None


@pytest.mark.parametrize(
    ("text", "expected_category"),
    [
        ("Nos vamos de viaje a la playa este feriado", Category.GROCERY),
        ("Necesito revisar las llantas de mi carro", Category.AUTO),
        ("Me mudo a un departamento y quiero organizar todo", Category.HOME),
    ],
)
def test_fallback_classifies_by_keyword(text: str, expected_category: Category) -> None:
    plan = domain.fallback(_request(text))
    assert any(s["target_category"] == expected_category.value for s in plan["slots"])


def test_fallback_has_expanded_keywords_not_a_single_word() -> None:
    plan = domain.fallback(_request("Necesito revisar las llantas de mi carro antes de viajar"))
    tire_slot = next(s for s in plan["slots"] if s["target_category"] == Category.AUTO.value)
    assert len(tire_slot["keywords"]) >= 4


def test_fallback_generic_falls_back_to_input_words() -> None:
    plan = domain.fallback(_request("Quiero comprar un regalo para mi mascota"))
    assert plan["mission_kind"] == MissionKind.GENERIC.value
    assert plan["slots"][0]["keywords"]


def test_fallback_generic_drops_stopwords() -> None:
    """Caso real reportado: "útiles de aseo PARA mi bebé" encontraba
    "Parrilla portátil PARA camping" porque "para" quedaba como keyword."""
    plan = domain.fallback(_request("útiles de aseo para mi bebé"))
    keywords = plan["slots"][0]["keywords"]
    assert "para" not in keywords
    assert {"aseo", "bebe"} <= set(keywords)


def test_fallback_on_a_revision_keeps_the_previous_plan_unchanged() -> None:
    """Distinto del fallback de un arranque: un ajuste que no se pudo
    interpretar de ninguna manera no debe reemplazar el plan por uno
    genérico -- lo más correcto es no tocar nada (ver domain.py)."""
    previous = domain.fallback(_request("Necesito revisar las llantas de mi carro"))
    request = _request("somos 6", mode=AgentMode.REVISE, previous_output=previous)

    assert domain.fallback(request) == previous


def test_summarize_snapshot_never_mentions_prices() -> None:
    text = domain.summarize_snapshot(
        {"mission_title": "Viaje", "needs": ["Hidratación"], "product_names": ["Agua 1L"]}
    )
    assert "S/" not in text and "$" not in text
    assert "Agua 1L" in text
