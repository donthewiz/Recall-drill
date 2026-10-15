"""Tools → "Recall Drill: sections" (v0.3), titled "Recall Drill: progress" (v0.3.1).

A read-only table. With ``Layer::N`` tags in the chosen deck the rows are layers
("Layer 1", "Layer 2", …) with one done/total column per chapter (direct
subdeck); otherwise the rows are the subdecks, in the order their cards were
made. Columns: cards, drilled, released undrilled, held, not yet in Anki, %
drilled, status, can't drill. The first row not done is marked **Next** and
**Drill next** opens the setup panel with Order = Deck order, only the new and
suspended new card types ticked, and, by layer, Only with tag = ``Layer::N``
(v0.3.2), so it picks the cards the table counts as to go. Clicking a row
opens the setup panel on its deck. Read in a ``QueryOp``; nothing is written.
The rules are in ``sections.py``, the reading in ``anki_io/sections.py``.
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
    QPushButton,
    Qt,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    qconnect,
)
from aqt.utils import disable_help_button, restoreGeom, saveGeom

from ..anki_io.sections import read_progress
from ..anki_io.select import PACE_CLASSES
from ..sections import Progress, SectionRow, progress_cells, progress_columns
from .context import AddonContext
from .widgets import ComboBox

TITLE = "Recall Drill: progress"
GEOM_KEY = "recalldrill_sections"


class SectionsDialog(QDialog):
    def __init__(
        self,
        ctx: AddonContext,
        open_setup: Callable[[int], None],
        deck_id: int | None,
        drill_next: Callable[..., None] | None = None,
    ) -> None:
        super().__init__(None)
        self.ctx = ctx
        self._open_setup = open_setup
        self._drill_next = drill_next
        self._closed = False
        self._generation = 0
        self.progress: Progress | None = None
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
        self.table = QTableWidget(0, 0)
        self.table.verticalHeader().setVisible(False)  # type: ignore[union-attr]
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        qconnect(self.table.cellClicked, self._clicked)
        layout.addWidget(self.table, 1)
        note = QLabel(
            "Drilled: handed off by the add-on. Released undrilled: sent to Anki without a "
            "drill (rd::undrilled). Held / waiting: new and suspended (rd::drill or rd::held). "
            "Not in Anki, not held: new cards never drilled. Can't drill: new cards the drill "
            "can never take (e.g. image occlusion); they never block a row. A layer shows "
            "done/total per chapter (drilled + released + introduced). A row is done when "
            "every new card is drilled or released; the first row not done is Next. Click a "
            "row to open its setup panel."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: gray; font-size: small;")
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.next_btn = QPushButton("Drill next")
        self.next_btn.setAutoDefault(False)
        self.next_btn.setToolTip(
            "Opens the setup panel with Order = Deck order and only new cards ticked, "
            "limited to the lowest unfinished layer (Only with tag = Layer::N); for "
            "subdecks, on the next subdeck."
        )
        self.next_btn.setEnabled(False)
        qconnect(self.next_btn.clicked, self._go_next)
        buttons.addButton(self.next_btn, QDialogButtonBox.ButtonRole.ActionRole)
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

        def done(progress: Progress) -> None:
            if not self._closed and gen == self._generation:
                self._show(progress)

        QueryOp(
            parent=self, op=lambda col: read_progress(col, storage, did), success=done
        ).run_in_background()

    @property
    def rows(self) -> list[SectionRow]:
        return list(self.progress.rows) if self.progress is not None else []

    def _show(self, progress: Progress) -> None:
        self.progress = progress
        rows = progress.rows
        finished = sum(1 for r in rows if r.done)
        noun = "layers" if progress.by_layer else "sections"
        nxt = progress.next_row
        self.summary.setText(
            f"{finished} of {len(rows)} {noun} done."
            + (f" Next: {nxt.label}." if nxt is not None else "")
            if rows
            else "This deck has no subdecks and no cards."
        )
        columns = progress_columns(progress)
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels(columns)
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            is_next = progress.next_index == i
            for j, text in enumerate(progress_cells(progress, i)):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if j == 0:
                    item.setToolTip(f"{r.new} new + {r.introduced} introduced")
                if is_next:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                self.table.setItem(i, j, item)
        self.table.resizeColumnsToContents()
        self.next_btn.setEnabled(progress.next_target is not None)

    def _clicked(self, row: int, _column: int) -> None:
        rows = self.rows
        if 0 <= row < len(rows):
            self._open_setup(rows[row].did)

    def _go_next(self) -> None:
        """Drill next: the setup panel on the chosen deck with Order = Deck order,
        "Only with tag" = Layer::N (or on the next subdeck, no tag, when the rows are
        subdecks) and only the new card types ticked (``PACE_CLASSES``): the table's
        "to go" counts new cards only, so reviews (young, lapsed, flagged) stay out."""
        progress = self.progress
        target = progress.next_target if progress is not None else None
        if progress is None or target is None:
            return
        if self._drill_next is not None:
            self._drill_next(target, "deck_order", progress.next_tag, PACE_CLASSES)
        else:
            self._open_setup(target)


def open_sections(
    ctx: AddonContext,
    open_setup: Callable[[int], None],
    deck_id: int | None,
    drill_next: Callable[..., None] | None = None,
) -> SectionsDialog:
    w = SectionsDialog(ctx, open_setup, deck_id, drill_next)
    w.show()
    return w
