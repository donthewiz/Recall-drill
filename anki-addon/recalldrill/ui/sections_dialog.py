"""Tools → "Recall Drill: sections" (v0.3), titled "Recall Drill: progress" (v0.3.1).

A read-only list of rounded rows (v0.5; it was a table). With ``Layer::N`` tags in the chosen
deck the rows are layers ("Layer 1", "Layer 2", …) with one done/total cell per chapter
(direct subdeck); otherwise the rows are the subdecks, in the order their cards were made. A row
shows its name, a thin bar of done vs to go with "47 of 47", the to-go count, the chapter
cells, and "✓ Done" or, on the first row not done (marked **NEXT**, accent border and tint), the
**Drill next** button. The other counts the table used to show (released undrilled, held /
waiting, not in Anki not held, % drilled, can't drill) are in the row's tooltip.

**Drill next** opens the setup panel with Order = Deck order, only the new and suspended new
card types ticked, and, by layer, Only with tag = ``Layer::N`` (v0.3.2), so it picks the cards
the row counts as to go. Clicking a row opens the setup panel on its deck. Read in a
``QueryOp``; nothing is written. The rules are in ``sections.py``, the reading in
``anki_io/sections.py``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aqt import mw
from aqt.operations import QueryOp
from aqt.qt import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QKeyEvent,
    QLabel,
    QMouseEvent,
    QProgressBar,
    QScrollArea,
    Qt,
    QVBoxLayout,
    QWidget,
    qconnect,
)
from aqt.utils import disable_help_button, restoreGeom, saveGeom

from ..anki_io.sections import read_progress
from ..anki_io.select import PACE_CLASSES
from ..sections import COLUMNS, Progress, SectionRow, cells
from . import style
from .context import AddonContext
from .widgets import ComboBox

TITLE = "Recall Drill: progress"
GEOM_KEY = "recalldrill_sections"
LEGEND = (
    "The bar is done of the cards the drill can take; a chapter shows done/total. Hover a row "
    "for every count. Click a row to open its setup panel."
)


def summary_text(progress: Progress) -> str:
    """ "2 of 4 layers done · Next: Layer 3, 504 to go" ("sections" for subdeck rows)."""
    rows = progress.rows
    if not rows:
        return "This deck has no subdecks and no cards."
    finished = sum(1 for r in rows if r.done)
    noun = "layers" if progress.by_layer else "sections"
    nxt = progress.next_row
    text = f"{finished} of {len(rows)} {noun} done"
    if nxt is not None:
        text += f" · Next: {nxt.label}, {nxt.to_go:,} to go"
    return text


def row_tooltip(r: SectionRow) -> str:
    """The numbers the old table had in its other columns."""
    lines = [f"{r.new} new + {r.introduced} introduced"]
    lines += [f"{name}: {value}" for name, value in zip(COLUMNS[1:7], cells(r)[1:7], strict=True)]
    lines.append(f"Can't drill: {r.cant_drill}")
    return "\n".join(lines)


class RowCard(QFrame):
    """One layer (or subdeck): a rounded row that opens its setup panel when clicked."""

    def __init__(
        self,
        index: int,
        row: SectionRow,
        progress: Progress,
        on_click: Callable[[int], None],
    ) -> None:
        super().__init__()
        self.index = index
        self._on_click = on_click
        is_next = progress.next_index == index
        self.setProperty("rdRow", "next" if is_next else "true")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip(row_tooltip(row))
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(18)

        name = QVBoxLayout()
        name.setSpacing(3)
        self.name_label = style.text_label(row.label, "strong", wrap=False)
        self.name_label.setMinimumWidth(150)
        name.addWidget(self.name_label)
        self.next_marker: QLabel | None = None
        if is_next:
            self.next_marker = style.chip_label("NEXT", "accent")
            name.addWidget(self.next_marker, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addLayout(name, 0)

        total = row.cards - row.cant_drill
        done = total - row.to_go
        bar = QVBoxLayout()
        bar.setSpacing(4)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setRange(0, max(total, 1))
        self.bar.setValue(done if total else 1)
        self.bar.setFixedWidth(150)
        self.bar_label = style.text_label(f"{done} of {total}", "muted", wrap=False)
        bar.addWidget(self.bar)
        bar.addWidget(self.bar_label)
        lay.addLayout(bar, 0)

        togo = QVBoxLayout()
        togo.setSpacing(0)
        self.count_label = style.text_label(f"{row.to_go:,}", "strong", wrap=False)
        self.count_label.setMinimumWidth(56)
        togo.addWidget(self.count_label)
        togo.addWidget(style.text_label("to go", "muted", wrap=False))
        lay.addLayout(togo, 0)

        self.chapter_cells: list[QLabel] = []
        self.chapter_captions: list[QLabel] = []
        if progress.by_layer:
            for chapter, (d, t) in zip(progress.chapters, row.chapters, strict=False):
                cell = QVBoxLayout()
                cell.setSpacing(0)
                num = style.text_label(f"{d}/{t}", "ok" if t and d == t else "strong", wrap=False)
                caption = style.text_label(chapter.label, "muted", wrap=False)
                num.setMinimumWidth(64)
                caption.setMinimumWidth(64)
                self.chapter_captions.append(caption)
                self.chapter_cells.append(num)
                cell.addWidget(num)
                cell.addWidget(caption)
                lay.addLayout(cell, 0)
        lay.addStretch(1)
        self.right = QHBoxLayout()
        self.done_label: QLabel | None = None
        if row.done:
            self.done_label = style.text_label("✓ Done", "ok", wrap=False)
            self.right.addWidget(self.done_label)
        lay.addLayout(self.right, 0)

    def mousePressEvent(self, a0: QMouseEvent | None) -> None:  # noqa: N802 (Qt override)
        if a0 is not None and a0.button() == Qt.MouseButton.LeftButton:
            self._on_click(self.index)
        super().mousePressEvent(a0)

    def keyPressEvent(self, a0: QKeyEvent | None) -> None:  # noqa: N802 (Qt override)
        if a0 is not None and a0.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self._on_click(self.index)
            return
        super().keyPressEvent(a0)


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
        root = style.install(self)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(20, 16, 20, 14)
        layout.setSpacing(12)
        top = QHBoxLayout()
        heading = QVBoxLayout()
        heading.setSpacing(2)
        heading.addWidget(style.text_label("Sections", "title", wrap=False))
        self.summary = style.text_label("Reading cards…", "muted")
        heading.addWidget(self.summary)
        top.addLayout(heading, 1)
        top.addWidget(style.text_label("Deck", "muted", wrap=False), 0, Qt.AlignmentFlag.AlignTop)
        self.deck_combo = ComboBox()
        decks = mw.col.decks.all_names_and_ids(include_filtered=False) if mw.col else []
        for d in decks:
            self.deck_combo.addItem(d.name, int(d.id))
        index = self.deck_combo.findData(deck_id) if deck_id is not None else -1
        self.deck_combo.setCurrentIndex(max(0, index))
        self.deck_combo.setMinimumWidth(220)
        qconnect(self.deck_combo.currentIndexChanged, self.refresh)
        top.addWidget(self.deck_combo, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(top)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.viewport().setAutoFillBackground(False)  # type: ignore[union-attr]
        holder = QWidget()
        holder.setObjectName("rdScrollBody")
        self.rows_layout = QVBoxLayout(holder)
        self.rows_layout.setContentsMargins(0, 0, 4, 0)
        self.rows_layout.setSpacing(8)
        self.rows_layout.addStretch(1)
        scroll.setWidget(holder)
        holder.setAutoFillBackground(False)
        layout.addWidget(scroll, 1)
        self.row_cards: list[RowCard] = []
        self.next_btn = style.button("Drill next", "primary")
        self.next_btn.setAutoDefault(False)
        self.next_btn.setToolTip(
            "Opens the setup panel with Order = Deck order and only new cards ticked, "
            "limited to the lowest unfinished layer (Only with tag = Layer::N); for "
            "subdecks, on the next subdeck."
        )
        self.next_btn.setEnabled(False)
        self.next_btn.setParent(root)
        self.next_btn.hide()
        qconnect(self.next_btn.clicked, self._go_next)
        layout.addWidget(style.text_label(LEGEND, "muted"))
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        close = style.button("Close", "ghost")
        close.setAutoDefault(False)
        qconnect(close.clicked, self.close)
        bottom.addWidget(close)
        layout.addLayout(bottom)
        self.resize(900, 460)
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
        self.summary.setText(summary_text(progress))
        # The persistent Drill next button leaves its row before the rows are rebuilt.
        self.next_btn.hide()
        self.next_btn.setParent(self)
        for card in self.row_cards:
            self.rows_layout.removeWidget(card)
            card.deleteLater()
        self.row_cards = []
        for i, r in enumerate(progress.rows):
            card = RowCard(i, r, progress, self._clicked)
            self.row_cards.append(card)
            self.rows_layout.insertWidget(i, card)
            if progress.next_index == i:
                card.right.addWidget(self.next_btn)
                self.next_btn.show()
        self.next_btn.setEnabled(progress.next_target is not None)

    def _clicked(self, row: int, _column: int = 0) -> None:
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
