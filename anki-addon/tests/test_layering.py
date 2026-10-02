"""Import-layering rules, checked statically with ast.

- engine/ is pure: no anki, aqt, PyQt*/PySide*, and nothing from anki_io or ui.
- The top-level helper modules (storage, prompts, deck_settings, sources) and
  the drill controller with its storage (controller, sessions, history_store)
  are pure the same way: no anki, no Qt. They may use engine/ and each other.
- anki_io/ never touches Qt; from aqt it may use aqt.operations only.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest

RECALLDRILL = Path(__file__).resolve().parent.parent / "recalldrill"


def _module_name(path: Path) -> str:
    rel = path.relative_to(RECALLDRILL.parent).with_suffix("")
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
            # `from recalldrill import ui` imports the ui subpackage.
            for alias in node.names:
                yield f"{target}.{alias.name}"


def _is(name: str, root: str) -> bool:
    return name == root or name.startswith(root + ".")


def _is_qt(name: str) -> bool:
    top = name.split(".")[0]
    return top.startswith(("PyQt", "PySide")) or _is(name, "aqt.qt")


def engine_violations(name: str) -> bool:
    return (
        _is(name, "anki")
        or _is(name, "aqt")
        or _is_qt(name)
        or _is(name, "recalldrill.anki_io")
        or _is(name, "recalldrill.ui")
    )


def anki_io_violations(name: str) -> bool:
    if _is_qt(name) or _is(name, "recalldrill.ui"):
        return True
    return _is(name, "aqt") and not _is(name, "aqt.operations")


PURE_MODULES = (
    "storage.py",
    "prompts.py",
    "deck_settings.py",
    "sources.py",
    "controller.py",
    "sessions.py",
    "history_store.py",
)


def _violations(layer: str, rule: object) -> list[str]:
    assert callable(rule)
    found: list[str] = []
    target = RECALLDRILL / layer
    paths = [target] if target.is_file() else sorted(target.rglob("*.py"))
    for path in paths:
        module = _module_name(path)
        source = path.read_text(encoding="utf-8")
        for name in imported_modules(source, module, path.name == "__init__.py"):
            if rule(name):
                found.append(f"{path.relative_to(RECALLDRILL.parent)}: {name}")
    return found


def test_engine_is_pure() -> None:
    assert (RECALLDRILL / "engine" / "__init__.py").exists()
    assert _violations("engine", engine_violations) == []


@pytest.mark.parametrize("module", PURE_MODULES)
def test_pure_modules_are_pure(module: str) -> None:
    assert (RECALLDRILL / module).is_file()
    assert _violations(module, engine_violations) == []


def test_anki_io_has_no_qt() -> None:
    assert (RECALLDRILL / "anki_io" / "__init__.py").exists()
    assert _violations("anki_io", anki_io_violations) == []


# The checker itself, so the two tests above can't pass vacuously.


@pytest.mark.parametrize(
    "source",
    [
        "import anki",
        "from anki.collection import Collection",
        "import aqt",
        "from aqt.operations import CollectionOp",
        "from PyQt6.QtWidgets import QWidget",
        "import PySide6",
        "from recalldrill.anki_io import x",
        "from ..anki_io import x",
        "from .. import ui",
        "from ..ui.widgets import thing",
    ],
)
def test_checker_flags_engine_violation(source: str) -> None:
    names = imported_modules(source, "recalldrill.engine.grading", is_package=False)
    assert any(engine_violations(n) for n in names), source


@pytest.mark.parametrize(
    "source",
    [
        "import json",
        "from . import grading",
        "from .items import parse_deck",
        "import anki_io_like",
    ],
)
def test_checker_allows_engine_imports(source: str) -> None:
    names = imported_modules(source, "recalldrill.engine.session", is_package=False)
    assert not any(engine_violations(n) for n in names), source


@pytest.mark.parametrize(
    "source",
    [
        "from aqt.qt import QWidget",
        "from PyQt6.QtCore import Qt",
        "from aqt import mw",
        "import aqt.utils",
        "from ..ui import dialog",
    ],
)
def test_checker_flags_anki_io_violation(source: str) -> None:
    names = imported_modules(source, "recalldrill.anki_io.handoff", is_package=False)
    assert any(anki_io_violations(n) for n in names), source


@pytest.mark.parametrize(
    "source",
    [
        "from aqt.operations import CollectionOp",
        "import aqt.operations",
        "from anki.collection import Collection",
        "from ..engine import session",
    ],
)
def test_checker_allows_anki_io_imports(source: str) -> None:
    names = imported_modules(source, "recalldrill.anki_io.handoff", is_package=False)
    assert not any(anki_io_violations(n) for n in names), source
