"""The setup panel's inputs ignore the scroll wheel until they have focus.

Headless Qt (offscreen); skipped where aqt isn't installed or Qt can't start.
"""

from __future__ import annotations

import importlib.util
import os
from typing import Any

import pytest

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("aqt") is None, reason="aqt (Anki's GUI package) isn't installed"
)


@pytest.fixture(scope="module")
def qt_app() -> object:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from aqt.qt import QApplication
    except ImportError as exc:
        pytest.skip(f"Qt can't start here: {exc}")
    return QApplication.instance() or QApplication([])


def _wheel(widget: Any, delta: int = 120) -> bool:
    """Send a wheel event over ``widget``; True if the widget accepted it."""
    from aqt.qt import QApplication, QPoint, QPointF, Qt, QWheelEvent

    pos = QPointF(widget.width() / 2, widget.height() / 2)
    event = QWheelEvent(
        pos,
        pos,
        QPoint(0, 0),
        QPoint(0, delta),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(widget, event)
    return event.isAccepted()


def _focus(widget: Any) -> None:
    from aqt.qt import QApplication

    widget.window().show()
    widget.window().activateWindow()
    widget.setFocus()
    QApplication.processEvents()
    if not widget.hasFocus():
        pytest.skip("this Qt platform can't give a widget focus")


def _built(qt_app: object) -> tuple[Any, dict[str, Any]]:
    from aqt.qt import QVBoxLayout, QWidget

    from recalldrill.ui.widgets import ComboBox, DateEdit, DoubleSpinBox, SpinBox

    host = QWidget()
    box = SpinBox()
    box.setRange(0, 100)
    box.setValue(3)
    dbl = DoubleSpinBox()
    dbl.setRange(0, 10)
    dbl.setValue(1.5)
    combo = ComboBox()
    combo.addItems(["a", "b", "c"])
    combo.setCurrentIndex(1)
    date = DateEdit()
    layout = QVBoxLayout(host)
    for w in (box, dbl, combo, date):
        layout.addWidget(w)
    return host, {"spin": box, "double": dbl, "combo": combo, "date": date}


def test_unfocused_inputs_ignore_the_wheel_and_pass_it_on(qt_app: object) -> None:
    host, w = _built(qt_app)
    before = (
        w["spin"].value(),
        w["double"].value(),
        w["combo"].currentIndex(),
        w["date"].date(),
    )
    for widget in w.values():
        assert not widget.hasFocus()
        assert _wheel(widget) is False  # ignored, so the parent (the scroll area) gets it
    assert (
        w["spin"].value(),
        w["double"].value(),
        w["combo"].currentIndex(),
        w["date"].date(),
    ) == before
    host.close()


@pytest.mark.parametrize("name", ["spin", "double", "combo", "date"])
def test_focused_input_still_takes_the_wheel(qt_app: object, name: str) -> None:
    host, w = _built(qt_app)
    widget = w[name]
    _focus(widget)
    before = {
        "spin": lambda: widget.value(),
        "double": lambda: widget.value(),
        "combo": lambda: widget.currentIndex(),
        "date": lambda: widget.date(),
    }[name]
    start = before()
    _wheel(widget)
    assert before() != start
    host.close()


def test_the_setup_panel_uses_only_guarded_inputs() -> None:
    import ast
    from pathlib import Path

    ui = Path(__file__).resolve().parents[2] / "recalldrill" / "ui"
    plain = {"QSpinBox", "QDoubleSpinBox", "QComboBox", "QDateEdit"}
    for path in ui.glob("*.py"):
        if path.name == "widgets.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in plain, f"{path.name}: use ui/widgets.py"
