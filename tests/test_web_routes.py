"""Smoke de las rutas del asesor contra `catalog.db` real (read-only).

Sin credenciales de agente en el entorno de test: todo lo que no pega en la
caché de semillas (`RetailMissionDomain.shortcut`) recorre el fallback
determinista del dominio (`RetailMissionDomain.fallback`) -- que es
exactamente lo que tiene que seguir funcionando si el agente no puede usar
ningún modelo en plena demo.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.web import session as sessions

PLAYA = "Me voy con los niños a la playa este feriado largo, somos 4 y vamos en carro"


@pytest.fixture
def client():
    sessions.clear()
    with TestClient(app) as test_client:  # dispara el lifespan (arma app.state.agent)
        yield test_client


def _subtotal(html: str) -> str:
    return re.search(r"Subtotal</p>\s*<p[^>]*>([^<]+)<", html).group(1)


def _start(client, budget="300") -> str:
    r = client.post("/mission", data={"text": PLAYA, "budget": budget}, follow_redirects=False)
    assert r.status_code == 303
    return r.headers["location"]


def test_crear_mision_redirige_y_renderiza_el_asesor(client):
    url = _start(client)
    assert url.startswith("/mission/playa_con_ninos-")
    html = client.get(url).text
    for needle in ("Entendí tu necesidad", "4 personas", "Presupuesto $ 300", "Carrito inteligente",
                   "de tu presupuesto", "Optimizar precio", "¿Quieres que lo ajuste?", 'hx-target="#advisor"'):
        assert needle in html, needle


def test_presupuesto_del_formulario_ya_no_se_ignora(client):
    assert "Sin presupuesto declarado" in client.get(_start(client, budget="")).text
    assert "Presupuesto $ 100" in client.get(_start(client, budget="100")).text


def test_mutaciones_devuelven_el_partial_y_cambian_el_subtotal(client):
    mid = _start(client).rsplit("/", 1)[1]
    base = _subtotal(client.get(f"/mission/{mid}").text)

    r = client.post(f"/mission/{mid}/cart/remove", data={"slot_id": "slot-hidratacion", "product_id": "PRD-003-2"})
    assert r.status_code == 200 and "<html" not in r.text  # fragmento, no página
    assert _subtotal(r.text) != base

    r = client.post(f"/mission/{mid}/optimize-price")
    assert "Ahorras" in r.text or "más económica" in r.text


def test_producto_fuera_del_pool_no_entra_al_carrito(client):
    mid = _start(client).rsplit("/", 1)[1]
    before = _subtotal(client.get(f"/mission/{mid}").text)
    r = client.post(f"/mission/{mid}/cart/add", data={"slot_id": "slot-hidratacion", "product_id": "NO-EXISTE"})
    assert _subtotal(r.text) == before


def test_quitar_categoria_funciona_sin_llm(client):
    """`drop_category:*` es una acción rápida ya inequívoca: se resuelve en
    Python siempre, nunca pasa por el agente (`advisor_service._deterministic_revision`)."""
    mid = _start(client).rsplit("/", 1)[1]
    r = client.post(f"/mission/{mid}/turn", data={"text": "Quita productos de autos", "action": "drop_category:auto"})
    assert 'id="group-auto"' not in r.text
    assert "Sin autos" in r.text


def test_texto_libre_sin_llm_no_toca_la_canasta(client):
    """Sin credenciales de agente, el ajuste en texto libre no se puede
    interpretar; el fallback del dominio para una REVISIÓN es conservar el
    plan previo tal cual (`RetailMissionDomain.fallback`), así que la canasta
    no cambia."""
    mid = _start(client).rsplit("/", 1)[1]
    before = _subtotal(client.get(f"/mission/{mid}").text)
    r = client.post(f"/mission/{mid}/turn", data={"text": "somos 6"})
    assert _subtotal(r.text) == before


def test_sesion_inexistente_no_es_500(client):
    r = client.post("/mission/nope/cart/add", data={"slot_id": "x", "product_id": "y"})
    assert r.status_code == 200 and "Tu sesión expiró" in r.text


def test_sesion_perdida_de_semilla_se_recupera_y_opaca_redirige(client):
    assert "recuperé la misión" in client.get("/mission/playa_con_ninos-abc123").text
    r = client.get("/mission/opaco", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"


@pytest.mark.parametrize(("answer", "requirement", "has_diapers"), [
    ("pesa 5kg", {
        "attribute": "supported_weight_kg", "operator": "contains",
        "value": "5", "unit": "kg", "source_text": "pesa 5kg",
    }, False),
    ("usa talla M", {
        "attribute": "size", "operator": "eq", "value": "M",
        "source_text": "talla M",
    }, True),
])
def test_clarification_to_recommendations_uses_real_catalog_and_natural_reply(client, answer, requirement, has_diapers):
    from app.domain.schema import AttributeRequirement, BasketSlot, Category, MissionPlanDraft
    from app.agent.graph.schemas import ReviewVerdict
    from app.agent.subagents.disambiguator import DisambiguationResult
    from app.mission_agent.domain import RetailMissionDomain
    from tests.agent.conftest import make_test_service
    from tests.agent.fakes import orchestrator_decision

    agent, router, _ = make_test_service(domain=RetailMissionDomain())
    app.state.agent = agent
    router.get("orchestrator").structured_queue = [
        orchestrator_decision("investigate", tasks=[{"subagent": "disambiguator", "instruction": "consultar talla"}]),
        orchestrator_decision("plan", tasks=[{"subagent": "planner", "instruction": "resolver"}]),
    ]
    router.get("disambiguator").structured_queue = [DisambiguationResult(
        is_ambiguous=True, question="¿Qué talla usa tu bebé o cuánto pesa?",
    )]
    router.get("reviewer").structured_queue = [
        ReviewVerdict(ready_to_finish=False, ambiguous=True),
        ReviewVerdict(ready_to_finish=True, summary="Listo"),
    ]
    router.get("planner").structured_queue = [MissionPlanDraft(slots=[
        BasketSlot(slot_id="panales", label="Pañales", target_category=Category.GROCERY,
                   keywords=["pañales"], attribute_requirements=[AttributeRequirement(**requirement)]),
        BasketSlot(slot_id="toallitas", label="Toallitas húmedas", target_category=Category.GROCERY,
                   keywords=["toallitas húmedas"]),
    ])]
    first = client.post("/mission", data={"text": "útiles de aseo para mi bebé"}, follow_redirects=False)
    url = first.headers["location"]
    assert "¿Qué talla usa tu bebé o cuánto pesa?" in client.get(url).text
    html = client.post(f"{url}/turn", data={"text": answer}).text
    assert "opciones de toallitas húmedas" in html
    assert "en Supermercado" in html
    assert "Pañales talla M x30" in html if has_diapers else "Pañales talla M x30" not in html
    if not has_diapers:
        assert "peso admitido 5 kg" in html and "falta esa información" in html
    assert "Listo: agregué" not in html
    assert "le falta un atributo" not in html.lower()


def _catalog_has_brand(brand: str) -> bool:
    from app.db import get_connection

    conn = get_connection()
    try:
        return conn.execute("SELECT 1 FROM products WHERE brand = ? AND is_active = 1 LIMIT 1", (brand,)).fetchone() is not None
    finally:
        conn.close()


def test_marca_pedida_ordena_primero_contra_el_catalogo_real(client):
    if not _catalog_has_brand("Coca-Cola"):
        pytest.skip("catalog.db todavía no trae productos Coca-Cola (BRD-*)")
    from app.agent.graph.schemas import ReviewVerdict
    from app.domain.schema import BasketSlot, Category, MissionPlanDraft
    from app.mission_agent.domain import RetailMissionDomain
    from tests.agent.conftest import make_test_service
    from tests.agent.fakes import orchestrator_decision

    agent, router, _ = make_test_service(domain=RetailMissionDomain())
    app.state.agent = agent
    router.get("orchestrator").structured_queue = [
        orchestrator_decision("plan", tasks=[{"subagent": "planner", "instruction": "resolver"}]),
    ]
    router.get("reviewer").structured_queue = [ReviewVerdict(ready_to_finish=True, summary="Listo")]
    router.get("planner").structured_queue = [MissionPlanDraft(slots=[
        BasketSlot(slot_id="gaseosa", label="Gaseosa cola", target_category=Category.GROCERY,
                   keywords=["gaseosa", "gaseosa cola", "cola", "refresco"], preferred_brands=["coca-cola"]),
    ])]

    url = client.post("/mission", data={"text": "quiero comprar coca-cola"}, follow_redirects=False).headers["location"]
    html = client.get(url).text

    assert "Marca: coca-cola" in html
    assert "Marca que pediste" in html
    first_card = re.search(r"<h4[^>]*>([^<]+)</h4>", html).group(1)
    assert "Coca-Cola" in first_card
