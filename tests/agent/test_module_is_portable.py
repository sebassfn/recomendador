"""`app/agent/` se tiene que poder copiar tal cual a otro proyecto: ningún
archivo del paquete puede importar nada de `app.*` fuera de sí mismo. Lo
único específico de este repo vive en `app/mission_agent/`, que SÍ puede
importar `app.agent` (es el lado anfitrión) pero nunca al revés."""

from __future__ import annotations

import ast
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent.parent / "app" / "agent"


def _imported_top_level_modules(tree: ast.Module) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules


def test_no_file_under_app_agent_imports_outside_the_package() -> None:
    offenders: list[str] = []
    for path in AGENT_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for module in _imported_top_level_modules(tree):
            if module == "app" or module.startswith("app.agent"):
                continue
            if module.startswith("app."):
                offenders.append(f"{path.relative_to(AGENT_ROOT.parent.parent)}: import {module}")

    assert not offenders, "app/agent/ dejó de ser portable:\n" + "\n".join(offenders)


def test_prompts_load_without_touching_the_filesystem_by_path() -> None:
    """Los prompts se leen con `importlib.resources`, no con rutas relativas
    a `__file__` -- así siguen funcionando si el paquete termina empaquetado
    (zip/wheel), no sólo corriendo desde una carpeta."""
    source = (AGENT_ROOT / "prompts" / "__init__.py").read_text(encoding="utf-8")
    assert "importlib" in source
    assert "resources.files" in source
    assert "open(" not in source.split('"""', 2)[-1]  # ignora la mención en el docstring
