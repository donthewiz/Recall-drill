"""A fold for the setup panel (v0.5.1): a full-width row that shows one section's name, a
one-line summary of its current values and a chevron, and opens the section's controls in place.

The row is a real, focusable ``QPushButton`` (Space toggles it; Enter too, as the row is an
auto-default button), with an accessible name of "<section>: <summary>" and a small warning dot
when the section holds an error or a warning. The section's own widgets live in ``body_layout``
and are not touched when it opens or closes.
"""

from __future__ import annotations

from collections.abc import Callable

from aqt.qt import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    Qt,
    QVBoxLayout,
    QWidget,
    qconnect,
)

from . import style

CLOSED_CHEVRON = "▸"
OPEN_CHEVRON = "▾"


class Fold(QFrame):
    def __init__(
        self,
        key: str,
        title: str,
        on_toggled: Callable[[str, bool], None] | None = None,
    ) -> None:
        super().__init__()
        self.key = key
        self.title = title
        self._on_toggled = on_toggled
        self._summary = ""
        self._warning = False
        self.setProperty("rdFold", True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.header = QPushButton()
        self.header.setCheckable(True)
        self.header.setProperty("rdFoldHeader", True)
        self.header.setCursor(style.pointing_hand())
        self.header.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.header.setAutoDefault(True)  # Enter toggles it while it has the focus
        row = QHBoxLayout(self.header)
        row.setContentsMargins(15, 0, 15, 0)
        row.setSpacing(12)
        self.name_label = style.section_label(title)
        self.name_label.setMinimumWidth(78)
        self.summary_label = QLabel()
        self.summary_label.setProperty("rdText", "foldSummary")
        # The summary never widens the panel: a long one is cut off (its tooltip has all of it).
        self.summary_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.dot = QLabel("●")
        self.dot.setProperty("rdText", "warnDot")
        self.dot.setToolTip("Needs a look")
        self.dot.hide()
        self.chevron = QLabel(CLOSED_CHEVRON)
        self.chevron.setProperty("rdText", "muted")
        for label in (self.name_label, self.summary_label, self.dot, self.chevron):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        row.addWidget(self.name_label, 0)
        row.addWidget(self.summary_label, 1)
        row.addWidget(self.dot, 0)
        row.addWidget(self.chevron, 0)
        outer.addWidget(self.header)

        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(15, 4, 15, 14)
        self.body_layout.setSpacing(9)
        self.body.hide()
        outer.addWidget(self.body)
        qconnect(self.header.toggled, self._toggled)
        self._refresh_name()

    def is_open(self) -> bool:
        return self.header.isChecked()

    def set_open(self, opened: bool) -> None:
        self.header.setChecked(opened)

    @property
    def summary(self) -> str:
        return self._summary

    def set_summary(self, text: str) -> None:
        self._summary = text
        self.summary_label.setText(text)
        self.summary_label.setToolTip(text)
        self._refresh_name()

    @property
    def warning(self) -> bool:
        return self._warning

    def set_warning(self, on: bool) -> None:
        self._warning = on
        self.dot.setVisible(on)
        self._refresh_name()

    def _refresh_name(self) -> None:
        name = f"{self.title}: {self._summary}" if self._summary else self.title
        if self._warning:
            name += " (needs a look)"
        self.header.setAccessibleName(name)
        self.header.setAccessibleDescription("open" if self.is_open() else "closed")

    def _toggled(self, opened: bool) -> None:
        self.body.setVisible(opened)
        self.chevron.setText(OPEN_CHEVRON if opened else CLOSED_CHEVRON)
        self._refresh_name()
        if self._on_toggled is not None:
            self._on_toggled(self.key, opened)
