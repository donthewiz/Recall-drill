"""Tools → "Recall Drill: sections" (v0.3): which parts of a course are drilled.

A read-only table of the chosen deck's subdecks in deck-tree order (cards,
drilled, released undrilled, held, not yet in Anki, % drilled, done). Clicking a
row opens the setup panel on that subdeck. Read in a ``QueryOp``; nothing is
written. The rules are in ``sections.py``, the reading in ``anki_io/sections.py``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aqt import mw
from aqt.operations import QueryOp
from aqt.qt import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    Qt,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    qconnect,
)
from aqt.utils import disable_help_button, restoreGeom, saveGeom

from ..anki_io.sections import read_sections
from ..sections import COLUMNS, SectionRow, cells
from .context import AddonContext
from .widgets import ComboBox

TITLE = "Recall Drill: sections"
GEOM_KEY = "recalldrill_sections"


class SectionsDialog(QDialog):
    def __init__(
        self, ctx: AddonContext, open_setup: Callable[[int], None], deck_id: int | None
    ) -> None:
        super().__init__(None)
        self.ctx = ctx
        self._open_setup = open_setup
        self._closed = False
        self._generation = 0
        self.rows: list[SectionRow] = []
        self.setWindowTitle(TITLE)
        disable_help_button(self)
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Deck"))
        self.deck_combo = ComboBox()
        decks = mw.col.decks.all_names_and_ids(include_filtered=False) if mw.col else []
        for d in decks:
            self.deck_combo.addItem(d.name, int(d.id))
        index = self.deck_combo.findData(deck_id) if deck_id is not None else -1
        self.deck_combo.setCurrentIndex(max(0, index))
        qconnect(self.deck_combo.currentIndexChanged, self.refresh)
        top.addWidget(self.deck_combo, 1)
        layout.addLayout(top)
        self.summary = QLabel("Reading cards…")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(list(COLUMNS))
        self.table.verticalHeader().setVisible(False)  # type: ignore[union-attr]
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        qconnect(self.table.cellClicked, self._clicked)
        layout.addWidget(self.table, 1)
        note = QLabel(
            "Drilled: handed off by the add-on. Released undrilled: sent to Anki without a "
            "drill (rd::undrilled). Held / waiting: new and suspended (rd::drill or rd::held). "
            "Not in Anki, not held: new cards never drilled. A section is done when every new "
            "card is drilled or released. Click a row to open its setup panel."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: gray; font-size: small;")
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        qconnect(buttons.rejected, self.close)
        layout.addWidget(buttons)
        self.resize(900, 420)
        restoreGeom(self, GEOM_KEY)
        ctx.dialogs.append(self)
        self.refresh()

    def closeEvent(self, a0: Any) -> None:  # noqa: N802 (Qt override)
        self._closed = True
        saveGeom(self, GEOM_KEY)
        if self in self.ctx.dialogs:
            self.ctx.dialogs.remove(self)
        super().closeEvent(a0)

    def deck_id(self) -> int | None:
        data = self.deck_combo.currentData()
        return int(data) if data is not None else None

    def refresh(self, *_args: Any) -> None:
        did = self.deck_id()
        if did is None:
            return
        self._generation += 1
        gen = self._generation
        storage = self.ctx.storage()
        self.summary.setText("Reading cards…")

        def done(rows: list[SectionRow]) -> None:
            if not self._closed and gen == self._generation:
                self._show(rows)

        QueryOp(
            parent=self, op=lambda col: read_sections(col, storage, did), success=done
        ).run_in_background()

    def _show(self, rows: list[SectionRow]) -> None:
        self.rows = rows
        finished = sum(1 for r in rows if r.done)
        self.summary.setText(
            f"{finished} of {len(rows)} sections done."
            if rows
            else "This deck has no subdecks and no cards."
        )
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            for j, text in enumerate(cells(r)):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if j == 0:
                    item.setToolTip(f"{r.new} new + {r.introduced} introduced")
                self.table.setItem(i, j, item)
        self.table.resizeColumnsToContents()

    def _clicked(self, row: int, _column: int) -> None:
        if 0 <= row < len(self.rows):
            self._open_setup(self.rows[row].did)


def open_sections(
    ctx: AddonContext, open_setup: Callable[[int], None], deck_id: int | None
) -> SectionsDialog:
    w = SectionsDialog(ctx, open_setup, deck_id)
    w.show()
    return w
