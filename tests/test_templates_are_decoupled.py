"""Protege la arquitectura: las plantillas del asesor sólo conocen `AdvisorVM`.

Si este test falla, alguien hizo que una plantilla lea el dominio directo. El
arreglo NO es relajar el test: es agregar el dato a un view-model y llenarlo en
el proyector.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARTIALS = ROOT / "app" / "templates" / "partials"

ADVISOR_TEMPLATES = [
    ROOT / "app" / "templates" / "mission.html",
    *(
        PARTIALS / name
        for name in (
            "advisor_body.html", "conversation.html", "understanding_chips.html",
            "recommendation_group.html", "product_card.html", "cart_panel.html", "cart_line.html",
            "budget_meter.html", "quick_actions.html", "turn_input.html", "session_expired.html",
        )
    ),
]

FORBIDDEN = re.compile(
    r"\b(basket|picked|scored|resolved|ResolvedSlot|ScoredProduct|Decimal)\b|\.signals\b|\.price\.amount|\.product\."
)


def test_plantillas_del_asesor_no_leen_el_dominio():
    offenders = []
    for path in ADVISOR_TEMPLATES:
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if "{#" in line:  # comentarios de Jinja pueden nombrar el dominio
                continue
            if FORBIDDEN.search(line):
                offenders.append(f"{path.name}:{n}: {line.strip()}")
    assert not offenders, "\n".join(offenders)


def test_viewmodel_no_importa_el_dominio():
    tree = ast.parse((ROOT / "app" / "presentation" / "viewmodel.py").read_text())
    modules = [
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    ] + [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    assert not [m for m in modules if m.startswith("app")], modules
