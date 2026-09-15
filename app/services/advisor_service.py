"""Operaciones del asesor sobre una sesión de misión.

Capa entre las rutas HTTP y el resto: recibe una `MissionSession`, llama al
agente de IA (`app/agent/`, vía `app/mission_agent/bridge.py`), al servicio de
canasta y a las operaciones de carrito, y deja la sesión actualizada con un
turno de asistente que describe EXACTAMENTE lo que pasó. Sin `Request`, sin
plantillas.

Qué va por el agente y qué no
-----------------------------
Todo ajuste en TEXTO LIBRE que cambia las necesidades de la misión pasa por
`app.mission_agent.bridge`: el subagente `planner` del agente revisa el
`MissionPlan`. El agente SIEMPRE devuelve algo usable -- si no puede
investigar/planificar con el modelo, su propio fallback determinista por
palabras clave (`app.mission_agent.keyword_fallback`) entra en su lugar; si
el pedido es ambiguo, pide una aclaración (`session.pending_clarification`) en
vez de adivinar.

Las acciones rápidas (`action=...`, quitar categoría, agregar un addon,
"más baratas", "sólo de marca") son comandos ya inequívocos -- se resuelven
100% en Python, sin pasar por el agente: no hay nada que interpretar.

Las frases del asistente son plantillas con contadores reales. Nunca
adjetivos que no se puedan verificar en pantalla.
"""

from __future__ import annotations

import sqlite3
from decimal import Decimal

from app.agent import AgentService, ClarificationAnswer, ClarificationRequest
from app.domain.schema import Basket, Category, MissionPlan, MissionPlanDraft, ScoringWeights
from app.engine.scoring import apply_sliders
from app.mission_agent import bridge
from app.mission_agent.catalog_feedback import build_retry_hint
from app.mission_agent.keyword_fallback import fallback_plan
from app.mission_agent.snapshot import build_snapshot
from app.presentation import cart as cart_ops
from app.presentation.advisor_reply import recommendation_reply
from app.presentation.addon_slots import ADDON_SLOTS
from app.presentation.projector import money
from app.presentation.viewmodel import TurnVM
from app.services.basket_service import resolve_mission
from app.web.session import MissionSession, new_mission_id

INTERPRETED_BY_DETAIL = {
    "cached_seed": "interpretado desde la caché de misiones de demo",
    "llm": "interpretado por el agente de IA",
    "keyword_fallback": "interpretado por palabras clave (el agente no pudo usar el modelo)",
}

# "Mejorar calidad" = relevancia pura: sin margen, rotación, marca propia ni
# promo, `apply_sliders` da relevance = 1.0. Es genuinamente distinto del
# default (50 % relevancia) y usa la API del motor sin tocarla.
PURE_RELEVANCE = apply_sliders(margin=0.0, turnover=0.0, private_label=0.0, promo=0.0)

# Cuántas veces se le da al agente la chance de reformular un slot obligatorio
# que el filtro duro dejó sin producto, antes de resignarse a mostrarlo vacío.
# Acotado y separado del presupuesto interno del grafo (`AGENT_MAX_ITERATIONS`):
# cada intento acá es un turno completo de `revise_mission`, no una iteración
# del orquestador.
MAX_CATALOG_RETRIES = 1


def _with_budget(mission: MissionPlan, budget: Decimal | None) -> MissionPlan:
    if budget is None:
        return mission
    return mission.model_copy(
        update={"constraints": mission.constraints.model_copy(update={"budget_total": budget})}
    )


def _say(session: MissionSession, user: str, assistant: str, detail: str | None = None) -> None:
    session.conversation.append(TurnVM(role="user", text=user))
    session.conversation.append(TurnVM(role="assistant", text=assistant, detail=detail))


def _clarification_reply(clarification: ClarificationRequest) -> str:
    """Sin un componente de UI dedicado a chips de sugerencia (docs/03 no lo
    prioriza; se corta antes que responsive), la aclaración se ofrece como
    texto: cada sugerencia numerada, más la opción de describirlo distinto.
    `_resolve_clarification_answer` entiende un número o el texto libre."""
    lines = [clarification.question]
    for i, suggestion in enumerate(clarification.suggestions, start=1):
        lines.append(f"{i}. {suggestion.label}")
    if clarification.suggestions:
        lines.append("Puedes responder con el número de una opción o contarme con tus palabras qué necesitas.")
    return "\n".join(lines)


def _resolve_clarification_answer(session: MissionSession, text: str) -> ClarificationAnswer:
    """Un número (1-based) elige la sugerencia de esa posición; cualquier
    otra cosa viaja como aclaración en texto libre -- el agente sabe
    resolver ambas (`app.agent.graph.nodes.clarify`)."""
    pending = ClarificationRequest.model_validate(session.pending_clarification)
    stripped = text.strip()
    if stripped.isdigit():
        index = int(stripped) - 1
        if 0 <= index < len(pending.suggestions):
            return ClarificationAnswer(suggestion_id=pending.suggestions[index].id)
    return ClarificationAnswer(free_text=text)


async def _resolve_with_catalog_retry(
    agent: AgentService,
    conn: sqlite3.Connection,
    mission: MissionPlan,
    *,
    user_id: str,
    agent_session_id: str,
    weights: ScoringWeights | None = None,
) -> tuple[MissionPlan, Basket]:
    """Resuelve la canasta y, si algún slot obligatorio quedó sin producto,
    le da al agente hasta `MAX_CATALOG_RETRIES` turnos para reformular ESE
    slot (otras keywords o categoría) antes de resignarse.

    Lo que vuelve al agente es sólo texto (`build_retry_hint`): slot_id,
    label, las keywords que el propio LLM ya había propuesto y el motivo
    estructural del descarte. Nunca productos ni precios (CLAUDE.md regla 6)
    -- el filtro duro y el ranking siguen corriendo acá, en Python, cada vez
    que el plan cambia.
    """
    basket = resolve_mission(conn, mission, weights)
    for _ in range(MAX_CATALOG_RETRIES):
        hint = build_retry_hint(basket)
        if hint is None:
            break
        result = await bridge.revise_mission(
            agent,
            user_id=user_id,
            agent_session_id=agent_session_id,
            previous_plan=mission,
            text=hint,
            snapshot=None,
        )
        if result.plan is None:
            break
        mission = result.plan
        basket = resolve_mission(conn, mission, weights)
    return mission, basket


async def _rebuild(
    session: MissionSession,
    conn: sqlite3.Connection,
    agent: AgentService,
    mission: MissionPlan,
    weights: ScoringWeights | None = None,
) -> tuple[int, int]:
    """Re-resuelve la misión (con reintento de catálogo) y reconcilia el carrito.

    - Líneas cuyo producto ya no está en el pool de su slot: se podan.
    - Slots nuevos (o que se quedaron sin línea): reciben su `picked`.

    Devuelve (líneas podadas, líneas agregadas) para que el turno lo cuente.
    """
    mission, basket = await _resolve_with_catalog_retry(
        agent,
        conn,
        mission,
        user_id=session.user_id,
        agent_session_id=session.agent_session_id,
        weights=weights or session.basket.weights,
    )
    session.mission = mission
    session.basket = basket
    return _reconcile_cart(session)


def _reconcile_cart(session: MissionSession) -> tuple[int, int]:
    """Poda las líneas que ya no resuelven contra `session.basket` y le da su
    `picked` a cada slot que quedó sin línea. Devuelve (podadas, agregadas)."""
    cart, dropped = cart_ops.prune(session.cart, session.basket)
    slots_in_cart = {line.slot_id for line in cart.lines}
    added = 0
    for rs in session.basket.slots:
        if rs.picked is not None and rs.slot.slot_id not in slots_in_cart:
            cart = cart_ops.add(cart, rs.slot.slot_id, rs.picked.product.product_id, rs.slot.quantity)
            added += 1
    session.cart = cart
    return len(dropped), added


# ---------------------------------------------------------------------------
# Inicio
# ---------------------------------------------------------------------------


async def start_mission(
    conn: sqlite3.Connection,
    text: str,
    budget: Decimal | None,
    agent: AgentService,
    user_id: str,
) -> MissionSession:
    text = text.strip()
    result = await bridge.start_mission(agent, text, user_id=user_id)
    # `AgentDomain.fallback` (keyword_fallback.fallback_plan) siempre emite
    # algo, así que en la práctica `result.plan` sólo es None si el pedido
    # dio pie a una aclaración -- ver más abajo.
    mission = _with_budget(result.plan, budget) if result.plan else None

    if mission is None:
        # Muy poco frecuente al ARRANCAR una misión (el desambiguador puede
        # pedir aclaración igual, p. ej. texto vacío o sin ninguna pista);
        # se arma con el fallback determinista para no dejar la pantalla sin
        # nada que mostrar.
        draft = MissionPlanDraft.model_validate(fallback_plan(text))
        mission = _with_budget(
            MissionPlan(
                raw_input=text,
                mission_kind=draft.mission_kind,
                title=draft.title,
                slots=draft.slots,
                constraints=draft.constraints,
                entities=draft.entities,
                interpreted_by="keyword_fallback",
            ),
            budget,
        )

    if result.clarification is None:
        # Sólo vale la pena gastar un turno de reintento de catálogo si esta
        # canasta es la que de verdad se va a mostrar. Con aclaración pendiente
        # la canasta de acá abajo es sólo un resguardo para que la pantalla no
        # quede vacía -- lo que se le dice al cliente es la pregunta, no esto.
        mission, basket = await _resolve_with_catalog_retry(
            agent, conn, mission, user_id=user_id, agent_session_id=result.agent_session_id
        )
    else:
        basket = resolve_mission(conn, mission)
    session = MissionSession(
        mission_id=new_mission_id(mission),
        mission=mission,
        basket=basket,
        cart=cart_ops.default_from_basket(basket),
        agent_session_id=result.agent_session_id,
        user_id=user_id,
        pending_clarification=(
            result.clarification.model_dump(mode="json") if result.clarification else None
        ),
    )

    reply = recommendation_reply(basket)
    if result.clarification:
        # Se arma igual una canasta de resguardo (arriba) para que la
        # pantalla nunca quede vacía, pero lo que se le dice al cliente es la
        # pregunta del agente, no el resumen de esa canasta provisoria.
        reply = _clarification_reply(result.clarification)
    # Una aclaración del agente no es un fallo del modelo, aunque la canasta
    # provisional se haya construido con el fallback mientras espera.
    detail = None if result.clarification else INTERPRETED_BY_DETAIL.get(mission.interpreted_by)
    _say(session, text, reply, detail)
    return session


# ---------------------------------------------------------------------------
# WOW
# ---------------------------------------------------------------------------


def optimize_price(session: MissionSession, user_text: str = "Optimizar precio") -> None:
    swaps = cart_ops.cheaper_swaps(session.cart, session.basket)
    if not swaps:
        _say(session, user_text, "Ya tienes la opción más económica de cada ítem entre las que te mostré.")
        return

    session.cart = cart_ops.apply_swaps(session.cart, swaps)
    saving = sum((s.saving for s in swaps), Decimal("0"))
    currency = session.mission.constraints.currency
    n = len(swaps)
    _say(
        session,
        user_text,
        f"Cambié {n} {'ítem' if n == 1 else 'ítems'} por la alternativa más económica "
        f"dentro de las que ya te mostré. Ahorras {money(saving, currency).display}.",
    )


def improve_quality(session: MissionSession, conn: sqlite3.Connection) -> None:
    before = {(line.slot_id, line.product_id) for line in session.cart.lines}
    # Se parte del carrito por defecto: la idea es ver qué elige la relevancia
    # pura, no conservar las elecciones que el orden comercial había hecho.
    basket = resolve_mission(conn, session.mission, PURE_RELEVANCE)
    session.basket = basket
    session.cart = cart_ops.default_from_basket(basket)
    after = {(line.slot_id, line.product_id) for line in session.cart.lines}
    changed = len(after - before)

    _say(
        session,
        "Mejorar calidad",
        f"Reordené cada necesidad sólo por qué tan bien encaja con lo que pediste, sin "
        f"peso de margen, rotación ni promociones. Cambiaron {changed} "
        f"{'producto' if changed == 1 else 'productos'} de tu carrito.",
    )


# ---------------------------------------------------------------------------
# Refinamiento conversacional
# ---------------------------------------------------------------------------


def _drop_category(mission: MissionPlan, category: Category) -> MissionPlan:
    excluded = list(mission.constraints.excluded_categories)
    if category not in excluded:
        excluded.append(category)
    return mission.model_copy(
        update={
            "slots": [s for s in mission.slots if s.target_category is not category],
            "constraints": mission.constraints.model_copy(update={"excluded_categories": excluded}),
        }
    )


def _branded_only(basket: Basket) -> tuple[Basket, int]:
    """Deja en cada slot sólo productos con marca declarada.

    Filtra, no reordena: el orden sigue siendo el del motor. Un slot que se
    queda sin opciones con marca conserva las suyas — vaciarlo sería peor que
    no cumplir el filtro, y el turno lo dice.
    """
    slots, kept_unbranded = [], 0
    for rs in basket.slots:
        pool = ([rs.picked] if rs.picked else []) + list(rs.alternatives)
        branded = [sp for sp in pool if sp.product.brand]
        if not branded:
            kept_unbranded += 1 if pool else 0
            slots.append(rs)
            continue
        slots.append(rs.model_copy(update={"picked": branded[0], "alternatives": branded[1:]}))
    return basket.model_copy(update={"slots": slots}), kept_unbranded


async def apply_turn(
    session: MissionSession,
    conn: sqlite3.Connection,
    text: str,
    action: str | None,
    agent: AgentService,
) -> None:
    text = text.strip()
    if not text:
        return

    # Operaciones que el agente no puede expresar (no ve precios ni el catálogo)
    # o que ya son un comando inequívoco -- nunca pasan por el LLM.
    if action == "cheaper":
        optimize_price(session, user_text=text)
        return

    if action == "branded_only":
        basket, kept = _branded_only(session.basket)
        session.basket = basket
        _reconcile_cart(session)
        reply = "Dejé sólo productos con marca declarada."
        if kept:
            reply += f" En {kept} {'necesidad' if kept == 1 else 'necesidades'} no hay ninguno, así que mantuve las opciones que había."
        _say(session, text, reply)
        return

    deterministic = _deterministic_revision(session.mission, action)
    if deterministic is not None:
        await _apply_revision(session, conn, agent, text, deterministic, detail=None)
        return

    # Si había una aclaración pendiente, este texto la responde -- no es un
    # ajuste nuevo, es la reanudación de la misma decisión del agente.
    if session.pending_clarification is not None:
        result = await bridge.resume_clarification(
            agent,
            user_id=session.user_id,
            agent_session_id=session.agent_session_id,
            raw_input=session.mission.raw_input,
            answer=_resolve_clarification_answer(session, text),
        )
    else:
        result = await bridge.revise_mission(
            agent,
            user_id=session.user_id,
            agent_session_id=session.agent_session_id,
            previous_plan=session.mission,
            text=text,
            snapshot=build_snapshot(session),
        )

    if result.clarification is not None:
        session.pending_clarification = result.clarification.model_dump(mode="json")
        _say(session, text, _clarification_reply(result.clarification))
        return

    session.pending_clarification = None
    if result.plan is None:
        _say(
            session,
            text,
            "No pude interpretar ese ajuste ahora mismo. Mantengo tu canasta como estaba; "
            "prueba con uno de los ajustes rápidos.",
        )
        return

    revised = result.plan
    if revised.constraints.budget_total is None:
        # El presupuesto del formulario es un dato del cliente, no una
        # inferencia: si el agente lo pierde al revisar, se conserva.
        revised = _with_budget(revised, session.mission.constraints.budget_total)

    detail = INTERPRETED_BY_DETAIL.get(revised.interpreted_by)
    if result.warnings:
        detail = f"{detail} ({'; '.join(result.warnings)})" if detail else "; ".join(result.warnings)
    await _apply_revision(session, conn, agent, text, revised, detail=detail)


async def _apply_revision(
    session: MissionSession,
    conn: sqlite3.Connection,
    agent: AgentService,
    text: str,
    revised: MissionPlan,
    detail: str | None,
) -> None:
    await _rebuild(session, conn, agent, revised)
    reply = recommendation_reply(session.basket)
    _say(session, text, reply, detail)


def _deterministic_revision(mission: MissionPlan, action: str | None) -> MissionPlan | None:
    """Ajustes que ya son un comando inequívoco (un botón de acción rápida):
    se resuelven en Python siempre, nunca pasan por el agente. `None` = esta
    acción no es de este tipo (sigue de largo hacia el agente, o es texto
    libre sin `action`)."""
    if action and action.startswith("drop_category:"):
        try:
            category = Category(action.split(":", 1)[1])
        except ValueError:
            return None
        return _drop_category(mission, category)

    if action in ADDON_SLOTS:
        slot = ADDON_SLOTS[action]
        if any(s.slot_id == slot.slot_id for s in mission.slots):
            return mission
        return mission.model_copy(update={"slots": [*mission.slots, slot]})

    return None

    return None
