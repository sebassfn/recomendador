"""Endpoints HTTP. Sólo orquestan: sesión -> servicio -> proyector -> plantilla.
Cero lógica de negocio acá (CLAUDE.md: "el negocio decide el orden").

Todas las mutaciones HTMX devuelven el mismo partial (`advisor_body.html`) con
el `AdvisorVM` completo, que reemplaza `#advisor` entero. Es repetido a
propósito: dos regiones de la pantalla no pueden quedar desincronizadas si
siempre se re-renderizan juntas.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.agent import AgentService
from app.db import get_connection
from app.presentation import cart as cart_ops
from app.presentation.projector import project_advisor
from app.services import advisor_service
from app.web import session as sessions

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# Chips semilla del guion de demo (docs/04-guion-de-demo.md §1-3): texto
# EXACTO de los 3 JSON en app/data/seeds/ -> `RetailMissionDomain.shortcut`
# pega en caché y nunca llama al agente (doc 04 §6: "el modelo no responde"
# no puede tumbar la demo).
SEED_CHIPS = [
    {
        "label": "Viaje a la playa",
        "text": "Me voy con los niños a la playa este feriado largo, somos 4 y vamos en carro",
    },
    {
        "label": "Mantenimiento del carro",
        "text": "Necesito hacerle mantenimiento al carro antes de viajar, es un Toyota Yaris 2018",
    },
    {
        "label": "Mudanza a depto chico",
        "text": "Me mudo a un departamento chico y tengo 300 soles para organizarlo",
    },
]


def _parse_budget(raw: str) -> Decimal | None:
    """El presupuesto del formulario. Vacío o inválido = sin presupuesto
    (ausente, no cero)."""
    raw = raw.strip().replace(",", ".")
    if not raw:
        return None
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return None
    return value if value > 0 else None


def _agent(request: Request) -> AgentService:
    return request.app.state.agent


def _set_user_cookie(request: Request, response: Response, user_id: str) -> None:
    """Id anónimo de la cookie `uid` -- lo que le permite al agente
    (`AgentService.list_sessions`) encontrar las conversaciones pasadas de
    este navegador (CLAUDE.md: sigue sin haber cuentas ni login)."""
    if request.cookies.get(sessions.USER_COOKIE) != user_id:
        response.set_cookie(
            sessions.USER_COOKIE, user_id, max_age=sessions.USER_COOKIE_MAX_AGE, httponly=True, samesite="lax"
        )


def _render_body(request: Request, session: sessions.MissionSession) -> HTMLResponse:
    vm = project_advisor(
        session.basket,
        session.cart,
        session.conversation,
        mission_id=session.mission_id,
        notices=session.notices,
    )
    # Los avisos se muestran una vez.
    session.notices = []
    response = templates.TemplateResponse(request, "partials/advisor_body.html", {"vm": vm})
    _set_user_cookie(request, response, session.user_id)
    return response


def _expired(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "partials/session_expired.html", {})


async def _recover(mission_id: str, request: Request) -> sessions.MissionSession | None:
    """Sesión perdida pero recuperable desde la caché de semillas (doc 03
    §10.4). Cero LLM: el texto semilla pega en caché."""
    text = sessions.seed_text_for(mission_id)
    if text is None:
        return None
    user_id = sessions.resolve_user_id(request)
    conn = get_connection()
    try:
        session = await advisor_service.start_mission(conn, text, None, _agent(request), user_id)
    finally:
        conn.close()
    session.mission_id = mission_id
    session.notices.append(
        "Tu sesión expiró; recuperé la misión desde la caché. El carrito se reinició."
    )
    sessions.put(session)
    return session


# ---------------------------------------------------------------------------
# Páginas
# ---------------------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
def entrada_mision(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html", {"seed_chips": SEED_CHIPS})


@router.post("/mission")
async def crear_mision(
    request: Request,
    text: str = Form(default=""),
    budget: str = Form(default=""),
) -> Response:
    """Interpreta la necesidad, arma la canasta, crea la sesión y redirige a
    su URL. El redirect (303) es lo que hace que recargar no re-envíe el
    formulario y que la misión tenga una URL propia contra la que HTMX vuelve.
    """
    user_id = sessions.resolve_user_id(request)
    conn = get_connection()
    try:
        session = await advisor_service.start_mission(
            conn, text.strip() or SEED_CHIPS[0]["text"], _parse_budget(budget), _agent(request), user_id
        )
    finally:
        conn.close()
    sessions.put(session)
    response = RedirectResponse(f"/mission/{session.mission_id}", status_code=303)
    _set_user_cookie(request, response, user_id)
    return response


@router.get("/mission/{mission_id}", response_class=HTMLResponse)
async def ver_mision(request: Request, mission_id: str) -> Response:
    session = sessions.get(mission_id) or await _recover(mission_id, request)
    if session is None:
        return RedirectResponse("/", status_code=303)

    vm = project_advisor(
        session.basket,
        session.cart,
        session.conversation,
        mission_id=session.mission_id,
        notices=session.notices,
    )
    session.notices = []
    response = templates.TemplateResponse(request, "mission.html", {"vm": vm})
    _set_user_cookie(request, response, session.user_id)
    return response


# ---------------------------------------------------------------------------
# Carrito
# ---------------------------------------------------------------------------


@router.post("/mission/{mission_id}/cart/{op}", response_class=HTMLResponse)
def mutar_carrito(
    request: Request,
    mission_id: str,
    op: str,
    slot_id: str = Form(...),
    product_id: str = Form(...),
) -> HTMLResponse:
    session = sessions.get(mission_id)
    if session is None:
        return _expired(request)

    if op in ("add", "inc"):
        session.cart = cart_ops.add(session.cart, slot_id, product_id)
    elif op == "dec":
        qty = cart_ops.quantity_of(session.cart, slot_id, product_id)
        session.cart = cart_ops.set_quantity(session.cart, slot_id, product_id, qty - 1)
    elif op == "remove":
        session.cart = cart_ops.remove(session.cart, slot_id, product_id)

    # Un id que no está en el pool visible (request manipulado, o de una
    # canasta anterior) no se queda en el carrito con un precio inventado.
    session.cart, _ = cart_ops.prune(session.cart, session.basket)
    return _render_body(request, session)


# ---------------------------------------------------------------------------
# Acciones WOW y refinamiento
# ---------------------------------------------------------------------------


@router.post("/mission/{mission_id}/optimize-price", response_class=HTMLResponse)
def optimizar_precio(request: Request, mission_id: str) -> HTMLResponse:
    session = sessions.get(mission_id)
    if session is None:
        return _expired(request)
    advisor_service.optimize_price(session)
    return _render_body(request, session)


@router.post("/mission/{mission_id}/improve-quality", response_class=HTMLResponse)
def mejorar_calidad(request: Request, mission_id: str) -> HTMLResponse:
    session = sessions.get(mission_id)
    if session is None:
        return _expired(request)
    conn = get_connection()
    try:
        advisor_service.improve_quality(session, conn)
    finally:
        conn.close()
    return _render_body(request, session)


@router.post("/mission/{mission_id}/turn", response_class=HTMLResponse)
async def turno(
    request: Request,
    mission_id: str,
    text: str = Form(default=""),
    action: str = Form(default=""),
) -> HTMLResponse:
    session = sessions.get(mission_id)
    if session is None:
        return _expired(request)
    conn = get_connection()
    try:
        await advisor_service.apply_turn(session, conn, text, action or None, _agent(request))
    finally:
        conn.close()
    return _render_body(request, session)
