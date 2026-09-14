"""Caché en disco de las 3 misiones semilla exactas del guion de demo
(docs/04-guion-de-demo.md §1-3). Es el `shortcut` de `RetailMissionDomain`:
cero LLM, cero latencia, match por texto literal normalizado — igual que el
Tramo 1 que tenía `app/llm/interpreter.py` antes de que el agente lo
reemplazara.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.domain.schema import MissionPlan, MissionPlanDraft

logger = logging.getLogger(__name__)

SEEDS_DIR = Path(__file__).resolve().parent.parent / "data" / "seeds"

# Texto EXACTO del chip de demo -> nombre de archivo en app/data/seeds/.
# Cualquier otra frase, aunque sea parecida, sigue de largo hacia el agente
# -- este caché es para latencia/costo de demo, no un sistema de similitud.
SEED_MISSION_FILES: dict[str, str] = {
    "Me voy con los niños a la playa este feriado largo, somos 4 y vamos en carro": "playa_con_ninos.json",
    "Necesito hacerle mantenimiento al carro antes de viajar, es un Toyota Yaris 2018": "mantenimiento_yaris.json",
    "Me mudo a un departamento chico y tengo 300 soles para organizarlo": "mudanza_departamento.json",
}


def normalize(text: str) -> str:
    return " ".join(text.strip().split())


def load_cached_seed(text: str) -> dict[str, Any] | None:
    """`None` si `text` no matchea ninguna semilla EXACTA. Si matchea, el
    `dict` ya tiene la forma de `MissionPlanDraft` (lo que
    `AgentDomain.shortcut` debe devolver) -- `raw_input`/`interpreted_by` los
    completa `bridge.py`, no esta caché."""
    filename = SEED_MISSION_FILES.get(normalize(text))
    if filename is None:
        return None

    path = SEEDS_DIR / filename
    if not path.exists():
        logger.warning("Seed cacheada %s declarada pero el archivo no existe", filename)
        return None

    full = MissionPlan.model_validate_json(path.read_text())
    draft = MissionPlanDraft(
        mission_kind=full.mission_kind,
        title=full.title,
        slots=full.slots,
        constraints=full.constraints,
        entities=full.entities,
    )
    return draft.model_dump(mode="json")
