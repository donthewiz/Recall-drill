"""Tools → "Recall Drill: waiting cards" (2026-10-12), and the once-a-day notice.

The drill cards still suspended and waiting, per deck (the cards' home deck), as rounded
rows (v0.5; it was a table): the deck's name over its parent path, waiting, stale (an amber
pill above 0), the pacing target, and two buttons per row: **Drill…** (the setup panel on
that deck) and **Send undrilled…** (``anki_io/release.py``: plan, confirm, apply as one undo
step, then the history line). The oldest added date is in the row's tooltip. Reads run in
``QueryOp``, the write in ``CollectionOp``.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from aqt import mw
from aqt.operations import CollectionOp, QueryOp
from aqt.qt import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QMessageBox,
    QScrollArea,
    Qt,
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
from . import style
from .context import AddonContext

TITLE = "Recall Drill: waiting cards"
GEOM_KEY = "recalldrill_waiting"
EXPLANATION = (
    "Stale: added more than the configured days ago (stale_drill_days), or in a deck "
    "whose pacing target has passed or has no drill days left. Sending to Anki "
    "undrilled offers the stale cards (the default) or all waiting cards: it "
    "unsuspends them (and their notes' suspended new siblings) as new cards in their "
    "current queue place, tags the notes rd::undrilled, and is one undo step."
)


def summary_text(rows: list[WaitingRow]) -> str:
    """ "12 cards suspended and waiting in 3 decks · 4 stale"."""
    if not rows:
        return "No drill cards are waiting."
    stale, _ = stale_total(rows)
    waiting = sum(r.waiting for r in rows)
    return (
        f"{waiting} card{'' if waiting == 1 else 's'} suspended and waiting in "
        f"{len(rows)} deck{'' if len(rows) == 1 else 's'} · {stale} stale"
    )


class WaitingCard(QFrame):
    """One deck's row."""

    def __init__(
        self, row: WaitingRow, drill: Callable[[], None], send: Callable[[], None]
    ) -> None:
        super().__init__()
        self.setProperty("rdRow", "true")
        self.setToolTip(f"Oldest added: {short_date(row.oldest)}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(18)
        *parents, leaf = row.deck.split("::")
        names = QVBoxLayout()
        names.setSpacing(0)
        self.name_label = style.text_label(leaf, "strong", wrap=False)
        names.addWidget(self.name_label)
        self.path_label = style.text_label(" › ".join(parents), "muted", wrap=False)
        self.path_label.setVisible(bool(parents))
        names.addWidget(self.path_label)
        lay.addLayout(names, 1)
        count = QVBoxLayout()
        count.setSpacing(0)
        self.waiting_label = style.text_label(str(row.waiting), "strong", wrap=False)
        self.waiting_label.setMinimumWidth(56)
        count.addWidget(self.waiting_label)
        count.addWidget(style.text_label("waiting", "muted", wrap=False))
        lay.addLayout(count)
        self.stale_label = (
            style.chip_label(f"{row.stale} stale", "warn")
            if row.stale
            else style.text_label("0 stale", "muted", wrap=False)
        )
        self.stale_label.setMinimumWidth(70)
        lay.addWidget(self.stale_label, 0, Qt.AlignmentFlag.AlignVCenter)
        self.target_label = style.text_label(
            f"target {short_date(row.target)}" if row.target else "", "muted", wrap=False
        )
        self.target_label.setMinimumWidth(110)
        lay.addWidget(self.target_label, 0, Qt.AlignmentFlag.AlignVCenter)
        self.drill_btn = style.button("Drill…")
        self.send_btn = style.button("Send undrilled…", "ghost")
        for b, fn in ((self.drill_btn, drill), (self.send_btn, send)):
            b.setAutoDefault(False)
            qconnect(b.clicked, fn)
            lay.addWidget(b)


class WaitingDialog(QDialog):
    def __init__(self, ctx: AddonContext, open_setup: Callable[[int], None]) -> None:
        super().__init__(None)
        self.ctx = ctx
        self._open_setup = open_setup
        self.rows: list[WaitingRow] = []
        self.row_cards: list[WaitingCard] = []
        self.setWindowTitle(TITLE)
        disable_help_button(self)
        root = style.install(self)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(20, 16, 20, 14)
        layout.setSpacing(12)
        layout.addWidget(style.text_label("Waiting cards", "title", wrap=False))
        self.summary = style.text_label("Reading cards…", "muted")
        layout.addWidget(self.summary)
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
        layout.addWidget(style.text_label(EXPLANATION, "muted"))
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
        self.summary.setText(summary_text(rows))
        for card in self.row_cards:
            self.rows_layout.removeWidget(card)
            card.deleteLater()
        self.row_cards = []
        for i, r in enumerate(rows):
            # ``clicked`` passes its ``checked`` flag to the first parameter: swallow it.
            card = WaitingCard(
                r,
                lambda _checked=False, did=r.did: self._drill(did),
                lambda _checked=False, row=r: self._send(row),
            )
            self.row_cards.append(card)
            self.rows_layout.insertWidget(i, card)

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
