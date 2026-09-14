"""Los dos niveles de capacidad entre los que el orquestador puede elegir.

`STANDARD` es el modelo por defecto de cada rol (rápido y barato).
`REASONING` es al que el orquestador escala UN turno puntual de UN subagente
cuando el revisor encuentra un error en su respuesta anterior — nunca una
elección fija del subagente, siempre una decisión del grafo en runtime.
"""

from __future__ import annotations

from enum import Enum


class ModelTier(str, Enum):
    STANDARD = "standard"
    REASONING = "reasoning"
