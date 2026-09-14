"""Carga de prompts desde archivos `.md` empaquetados junto al código.

Los system prompts viven en texto plano, no en strings Python embebidos, para
que se puedan leer y editar sin tocar lógica — y para que copiar
`app/agent/` a otro proyecto incluya sus prompts sin buscarlos en otro lado.

`importlib.resources` (no `open()` con una ruta relativa a `__file__`) es lo
que hace que esto funcione también si el paquete termina empaquetado en un
zip/wheel, no sólo corriendo desde el filesystem.
"""

from __future__ import annotations

from importlib import resources


def load_prompt(name: str, **variables: str) -> str:
    """`name` es una ruta relativa a este paquete SIN extensión, p. ej.
    `"orchestrator"` o `"domains/retail_mission/planner"`. `variables` se
    interpolan con `str.format` -- el prompt declara sus placeholders como
    `{esto}`."""
    *parts, filename = name.split("/")
    package = ".".join([__package__, *parts]) if parts else __package__
    text = resources.files(package).joinpath(f"{filename}.md").read_text(encoding="utf-8")
    return text.format(**variables) if variables else text
