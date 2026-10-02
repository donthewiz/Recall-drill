"""Input widgets that ignore the mouse wheel until they have focus.

Scrolling the setup panel with the wheel used to change whatever spin box or
drop-down the pointer passed over, and the next Save kept the change. These
subclasses take focus only by click or Tab (``StrongFocus``), and an unfocused
one ignores the wheel event, which hands it to the parent so the panel scrolls.
Every spin box, drop-down and date field in ``ui/`` is one of these
(tests/test_layering.py checks that no plain one is built).
"""

from aqt.qt import QComboBox, QDateEdit, QDoubleSpinBox, QSpinBox, Qt, QWheelEvent


class _NoWheelUnlessFocused:
    """Mixin: ``wheelEvent`` passes the event on while the widget lacks focus."""

    def _init_wheel_guard(self) -> None:
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)  # type: ignore[attr-defined]

    def wheelEvent(self, e: QWheelEvent | None) -> None:
        if e is None:
            return
        if not self.hasFocus():  # type: ignore[attr-defined]
            e.ignore()
            return
        super().wheelEvent(e)  # type: ignore[misc]


class SpinBox(_NoWheelUnlessFocused, QSpinBox):
    def __init__(self) -> None:
        super().__init__()
        self._init_wheel_guard()


class DoubleSpinBox(_NoWheelUnlessFocused, QDoubleSpinBox):
    def __init__(self) -> None:
        super().__init__()
        self._init_wheel_guard()


class ComboBox(_NoWheelUnlessFocused, QComboBox):
    def __init__(self) -> None:
        super().__init__()
        self._init_wheel_guard()


class DateEdit(_NoWheelUnlessFocused, QDateEdit):
    def __init__(self) -> None:
        super().__init__()
        self._init_wheel_guard()
