"""Tools → "Recall Drill: waiting cards" (2026-10-12), and the once-a-day notice.

A table of the drill cards still suspended and waiting, per deck (the cards'
home deck): waiting, stale, oldest added, pacing target, and two buttons per
row: **Drill…** (the setup panel on that deck) and **Send to Anki undrilled…**
(``anki_io/release.py``: plan, confirm, apply as one undo step, then the
history line). Reads run in ``QueryOp``, the write in ``CollectionOp``.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from aqt import mw
from aqt.operations import CollectionOp, QueryOp
from aqt.qt import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    Qt,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    qconnect,
)
from aqt.utils import disable_help_button, restoreGeom, saveGeom, showWarning, tooltip

from .. import history_store
from ..anki_io.release import (
    ReleasePlan,
    apply_release,
    describe_choices,
    failure_text,
    history_line,
    plan_release,
)
from ..anki_io.waiting import read_waiting
from ..measure import anki_day
from ..pacing import short_date
from ..waiting import (
    ReleaseChoice,
    WaitingRow,
    load_last_shown,
    notice_due,
    notice_text,
    release_choices,
    save_last_shown,
    stale_total,
)
from .context import AddonContext

TITLE = "Recall Drill: waiting cards"
GEOM_KEY = "recalldrill_waiting"
COLUMNS = ("Deck", "Waiting", "Stale", "Oldest added", "Pacing target", "", "")


class WaitingDialog(QDialog):
    def __init__(self, ctx: AddonContext, open_setup: Callable[[int], None]) -> None:
        super().__init__(None)
        self.ctx = ctx
        self._open_setup = open_setup
        self.rows: list[WaitingRow] = []
        self.setWindowTitle(TITLE)
        disable_help_button(self)
        layout = QVBoxLayout(self)
        self.summary = QLabel("Reading cards…")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(list(COLUMNS))
        self.table.verticalHeader().setVisible(False)  # type: ignore[union-attr]
        layout.addWidget(self.table, 1)
        note = QLabel(
            "Stale: added more than the configured days ago (stale_drill_days), or in a deck "
            "whose pacing target has passed or has no drill days left. Sending to Anki "
            "undrilled offers the stale cards (the default) or all waiting cards: it "
            "unsuspends them (and their notes' suspended new siblings) as new cards in their "
            "current queue place, tags the notes rd::undrilled, and is one undo step."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: gray; font-size: small;")
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        qconnect(buttons.rejected, self.close)
        layout.addWidget(buttons)
        self.resize(820, 420)
        restoreGeom(self, GEOM_KEY)
        ctx.dialogs.append(self)
        self.refresh()

    def closeEvent(self, a0: Any) -> None:  # noqa: N802 (Qt override)
        saveGeom(self, GEOM_KEY)
        if self in self.ctx.dialogs:
            self.ctx.dialogs.remove(self)
        super().closeEvent(a0)

    def refresh(self) -> None:
        storage, cfg = self.ctx.storage(), self.ctx.config()
        QueryOp(
            parent=self,
            op=lambda col: read_waiting(col, storage, cfg),
            success=self._show,
        ).run_in_background()

    def _show(self, rows: list[WaitingRow]) -> None:
        self.rows = rows
        stale, _ = stale_total(rows)
        waiting = sum(r.waiting for r in rows)
        self.summary.setText(
            f"{waiting} drill cards suspended and waiting, {stale} of them stale."
            if rows
            else "No drill cards are waiting."
        )
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            cells = (
                r.deck,
                str(r.waiting),
                str(r.stale),
                short_date(r.oldest),
                short_date(r.target) if r.target else "",
            )
            for j, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(i, j, item)
            drill = self._button("Drill…", lambda did=r.did: self._drill(did))
            self.table.setCellWidget(i, 5, drill)
            self.table.setCellWidget(
                i, 6, self._button("Send to Anki undrilled…", lambda row=r: self._send(row))
            )
        self.table.resizeColumnsToContents()

    def _button(self, text: str, fn: Callable[[], None]) -> QWidget:
        b = QPushButton(text)
        qconnect(b.clicked, fn)
        box = QWidget()
        hl = QHBoxLayout(box)
        hl.setContentsMargins(2, 0, 2, 0)
        hl.addWidget(b)
        return box

    def _drill(self, did: int) -> None:
        self._open_setup(did)

    def _send(self, row: WaitingRow) -> None:
        choices = release_choices(row)
        QueryOp(
            parent=self,
            op=lambda col: [plan_release(col, row.did, c.cids, c.scope) for c in choices],
            success=lambda plans: self._confirm(choices, plans),
        ).run_in_background()

    def _confirm(self, choices: list[ReleaseChoice], plans: list[ReleasePlan]) -> None:
        offered = [(c, p) for c, p in zip(choices, plans, strict=True) if p.has_changes]
        if not offered:
            tooltip("Nothing to send: those cards are no longer waiting.")
            self.refresh()
            return
        picked = ask_send(self, [(c.label, p) for c, p in offered])
        if picked is None:
            return
        plan = picked
        storage = self.ctx.storage()

        def done(_changes: Any) -> None:
            try:
                history_store.append_release(
                    storage, str(plan.did), history_line(plan, time.time() * 1000)
                )
            except Exception as exc:
                showWarning(f"The cards were sent, but the history line failed: {exc}")
            tooltip(f"Sent {plan.cards} cards to Anki. Edit → Undo reverts it.")
            self.refresh()

        CollectionOp(self, lambda col: apply_release(col, plan)).success(done).failure(
            lambda exc: showWarning(failure_text(exc))
        ).run_in_background()


def ask_send(parent: QWidget, offered: list[tuple[str, ReleasePlan]]) -> ReleasePlan | None:
    """The release's confirmation: one button per choice ("Stale only (N)" first and
    the default, then "All waiting (M)"; only "All waiting" when nothing is stale)
    and Cancel. Returns the chosen plan, or None."""
    box = QMessageBox(parent)
    box.setWindowTitle(TITLE)
    box.setIcon(QMessageBox.Icon.Question)
    box.setText(describe_choices([p for _label, p in offered]))
    buttons = [
        (box.addButton(label, QMessageBox.ButtonRole.AcceptRole), plan) for label, plan in offered
    ]
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(buttons[0][0])
    box.exec()
    clicked = box.clickedButton()
    for button, plan in buttons:
        if clicked is button:
            return plan
    return None


def open_waiting(ctx: AddonContext, open_setup: Callable[[int], None]) -> WaitingDialog:
    w = WaitingDialog(ctx, open_setup)
    w.show()
    return w


def maybe_notify(ctx: AddonContext) -> None:
    """After the profile opens: the notice, once per Anki day, when stale cards wait."""
    cfg = ctx.config()
    if not cfg.waiting_notice or mw.col is None:
        return
    storage = ctx.storage()

    def op(col: Any) -> tuple[Any, str | None]:
        today = anki_day(time.time() * 1000, col.get_preferences().scheduling.rollover)
        if not notice_due(cfg.waiting_notice, load_last_shown(storage), today):
            return today, None
        stale, oldest = stale_total(read_waiting(col, storage, cfg))
        return today, notice_text(stale, oldest) if stale and oldest else None

    def done(result: tuple[Any, str | None]) -> None:
        today, text = result
        if text is None:
            return
        save_last_shown(storage, today)
        tooltip(text, period=8000)

    QueryOp(parent=mw, op=op, success=done).run_in_background()
