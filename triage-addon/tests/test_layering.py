"""Import-layering rules, checked statically with ast.

- The Qt-free modules (everything at the top of ``card_triage/``) import no anki,
  no aqt and no Qt: the engine, the controllers and the HTML builders run, and are tested, with
  nothing of Anki loaded.
- ``anki_io/`` never touches Qt; from aqt it may use ``aqt.operations`` only.
- ``ui/`` may import anything.
- Nothing in the add-on (or its tests) imports Recall Drill (``recalldrill``) or Math Path
  (``math_path``): Card Triage stands alone.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parent.parent / "card_triage"
ROOT = PACKAGE.parent


def _module_name(path: Path) -> str:
    rel = path.relative_to(ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def imported_modules(source: str, module: str, is_package: bool) -> Iterator[str]:
    """Yield every absolute module name `source` imports, resolving relative imports."""
    package = module if is_package else module.rpartition(".")[0]
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")
                if node.level > 1:
                    base = base[: -(node.level - 1)]
                prefix = ".".join(base)
                target = f"{prefix}.{node.module}" if node.module else prefix
            else:
                target = node.module or ""
            yield target
            for alias in node.names:
                yield f"{target}.{alias.name}"


def _is(name: str, root: str) -> bool:
    return name == root or name.startswith(root + ".")


def _is_qt(name: str) -> bool:
    top = name.split(".")[0]
    return top.startswith(("PyQt", "PySide")) or _is(name, "aqt.qt")


def pure_violations(name: str) -> bool:
    return (
        _is(name, "anki")
        or _is(name, "aqt")
        or _is_qt(name)
        or _is(name, "card_triage.anki_io")
        or _is(name, "card_triage.ui")
    )


def anki_io_violations(name: str) -> bool:
    if _is_qt(name) or _is(name, "card_triage.ui"):
        return True
    return _is(name, "aqt") and not _is(name, "aqt.operations")


def _pure_paths() -> list[Path]:
    return sorted(PACKAGE.glob("*.py"))


def _violations(paths: list[Path], rule: object) -> list[str]:
    assert callable(rule)
    found: list[str] = []
    for path in paths:
        module = _module_name(path)
        source = path.read_text(encoding="utf-8")
        for name in imported_modules(source, module, path.name == "__init__.py"):
            if rule(name):
                found.append(f"{path.relative_to(ROOT)}: {name}")
    return found


def test_there_are_pure_modules_to_check() -> None:
    names = {p.name for p in _pure_paths()}
    assert "__init__.py" in names


def test_pure_modules_are_pure() -> None:
    assert _violations(_pure_paths(), pure_violations) == []


def test_nothing_imports_the_other_add_ons() -> None:
    paths = sorted(PACKAGE.rglob("*.py")) + [ROOT / "__init__.py"]
    paths += [p for p in sorted((ROOT / "tests").rglob("*.py")) if p.name != "test_layering.py"]
    assert _violations(paths, other_addon) == []


def other_addon(name: str) -> bool:
    return _is(name, "recalldrill") or _is(name, "math_path")


def test_anki_io_has_no_qt() -> None:
    paths = sorted((PACKAGE / "anki_io").rglob("*.py"))
    assert paths
    assert _violations(paths, anki_io_violations) == []


# The checker itself, so the tests above can't pass vacuously.


@pytest.mark.parametrize(
    "source",
    [
        "import anki",
        "from anki.collection import Collection",
        "import aqt",
        "from aqt.operations import CollectionOp",
        "from PyQt6.QtWidgets import QWidget",
        "from card_triage.anki_io import triage",
        "from ..anki_io import triage",
        "from .. import ui",
    ],
)
def test_checker_flags_pure_violation(source: str) -> None:
    names = imported_modules(source, "card_triage.sub.mod", is_package=False)
    assert any(pure_violations(n) for n in names), source


@pytest.mark.parametrize(
    "source", ["import json", "from . import common", "from ..keys import normalize_key"]
)
def test_checker_allows_pure_imports(source: str) -> None:
    names = imported_modules(source, "card_triage.sub.mod", is_package=False)
    assert not any(pure_violations(n) for n in names), source


@pytest.mark.parametrize(
    "source",
    [
        "from aqt.qt import QWidget",
        "from PyQt6.QtCore import Qt",
        "from aqt import mw",
        "from ..ui import x",
    ],
)
def test_checker_flags_anki_io_violation(source: str) -> None:
    names = imported_modules(source, "card_triage.anki_io.triage", is_package=False)
    assert any(anki_io_violations(n) for n in names), source


@pytest.mark.parametrize(
    "source",
    ["from aqt.operations import CollectionOp", "from anki.collection import Collection"],
)
def test_checker_allows_anki_io_imports(source: str) -> None:
    names = imported_modules(source, "card_triage.anki_io.triage", is_package=False)
    assert not any(anki_io_violations(n) for n in names), source


@pytest.mark.parametrize(
    "source",
    ["import recalldrill", "from recalldrill.engine import x", "from math_path import y"],
)
def test_checker_flags_other_addons(source: str) -> None:
    names = imported_modules(source, "card_triage.anki_io.triage", is_package=False)
    assert any(other_addon(n) for n in names), source
