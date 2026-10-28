"""Tools → Card Triage → Settings…: the key and the two prompts."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aqt.qt import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    qconnect,
)

from ..config import MAX_AGAINS, MAX_SECONDS, MIN_AGAINS, MIN_SECONDS, Config
from ..keys import check_key

TITLE = "Card Triage settings"


class SettingsDialog(QDialog):
    """``on_save`` gets the new config as a ``config.json`` dict once the key is accepted.
    ``live_keys`` adds the keys Anki is using right now (answer keys the user rebound, say)."""

    def __init__(
        self,
        config: Config,
        on_save: Callable[[dict[str, Any]], None],
        live_keys: Callable[[], dict[str, str]] = dict,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_save = on_save
        self._live_keys = live_keys
        self.setWindowTitle(TITLE)

        self.key = QLineEdit(config.set_aside_key)
        self.key.setMaxLength(24)
        self.key.setFixedWidth(120)
        key_hint = QLabel("One key, such as X, or Ctrl+X. Used in the reviewer.")
        key_hint.setWordWrap(True)

        self.timer_on = QCheckBox("Offer to set a card aside when I'm stuck on it for")
        self.timer_on.setChecked(config.timer_prompt)
        self.timer_seconds = QSpinBox()
        self.timer_seconds.setRange(MIN_SECONDS, MAX_SECONDS)
        self.timer_seconds.setSuffix(" seconds")
        self.timer_seconds.setValue(config.timer_seconds)

        self.again_on = QCheckBox("Offer to set a learning card aside after")
        self.again_on.setChecked(config.again_prompt)
        self.again_count = QSpinBox()
        self.again_count.setRange(MIN_AGAINS, MAX_AGAINS)
        self.again_count.setSuffix(" Agains")
        self.again_count.setValue(config.again_count)

        self.error = QLabel("")
        self.error.setWordWrap(True)
        font = self.error.font()
        font.setBold(True)
        self.error.setFont(font)

        form = QFormLayout()
        form.addRow("Set-aside key", self.key)
        form.addRow("", key_hint)
        timer_row = QHBoxLayout()
        timer_row.addWidget(self.timer_on)
        timer_row.addWidget(self.timer_seconds)
        timer_row.addStretch(1)
        again_row = QHBoxLayout()
        again_row.addWidget(self.again_on)
        again_row.addWidget(self.again_count)
        again_row.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        qconnect(buttons.accepted, self.try_accept)
        qconnect(buttons.rejected, self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(timer_row)
        layout.addLayout(again_row)
        layout.addWidget(self.error)
        layout.addWidget(buttons)

    def try_accept(self) -> bool:
        """Save and close if the key is allowed; otherwise say why and stay open."""
        checked = check_key(self.key.text(), self._live_keys())
        if not checked.ok:
            self.error.setText(checked.message)
            return False
        self.error.setText("")
        self._on_save(
            {
                "set_aside_key": checked.key,
                "timer_prompt": self.timer_on.isChecked(),
                "timer_seconds": self.timer_seconds.value(),
                "again_prompt": self.again_on.isChecked(),
                "again_count": self.again_count.value(),
            }
        )
        self.accept()
        return True
