"""The handoff, from the drill window's Done screen or the setup panel's banner.

1. Plan off the main thread (``QueryOp``): fresh snapshots, the forecast.
2. Confirm: **Hand off** / **Not now** (the session stays pending) /
   **Don't hand off** (the save goes, with a declined history line).
3. Hand off: ``apply_handoff`` inside ``CollectionOp``, so it's one undo step
   and the main window refreshes. On success the history line is written and
   the save deleted; on failure the session stays pending and the error shows.

``apply_handoff`` is the only collection write in the add-on.
"""

from __future__ import annotations

import html
from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal, cast

from aqt import mw
from aqt.operations import CollectionOp, QueryOp
from aqt.qt import QDialog, QHBoxLayout, QLabel, QPushButton, Qt, QVBoxLayout, QWidget, qconnect
from aqt.theme import theme_manager
from aqt.utils import disable_help_button, showWarning, tooltip

from .. import launch, sessions
from ..anki_io.handoff import (
    DONE_MESSAGE,
    Forecast,
    HandoffPlan,
    HandoffSettings,
    HandoffText,
    apply_handoff,
    describe,
    failure_text,
    forecast,
    handoff_line,
    next_day_start,
    plan_handoff,
    top_deck_for,
)
from .context import AddonContext

Choice = Literal["handoff", "later", "decline"]

AMBER = ("#D97706", "#F59E0B")
"""The web app's --warning, light and night."""


class HandoffDialog(QDialog):
    def __init__(self, parent: QWidget | None, text: HandoffText) -> None:
        super().__init__(parent)
        disable_help_button(self)
        self.setWindowTitle("Recall Drill: hand off to Anki")
        self.choice: Choice = "later"
        self.text = text
        layout = QVBoxLayout(self)

        def label(markup: str) -> QLabel:
            lab = QLabel(markup)
            lab.setWordWrap(True)
            lab.setTextFormat(Qt.TextFormat.RichText)
            layout.addWidget(lab)
            return lab

        self.headline = label(f"<b>{html.escape(text.headline)}</b>")
        self.body = label("<br>".join(html.escape(x) for x in text.lines))
        self.forecast = label("<br>".join(html.escape(x) for x in text.forecast))
        self.forecast.setVisible(bool(text.forecast))
        amber = AMBER[1 if theme_manager.night_mode else 0]
        self.warnings = label(
            "<br>".join(
                f'<span style="color:{amber}">⚠ {html.escape(w)}</span>' for w in text.warnings
            )
        )
        self.warnings.setVisible(bool(text.warnings))
        label('<span style="color:gray">One undo step: Edit → Undo "Recall Drill handoff".</span>')

        row = QHBoxLayout()
        self.handoff_btn = QPushButton("Hand off")
        self.later_btn = QPushButton("Not now")
        self.decline_btn = QPushButton("Don't hand off")
        self.decline_btn.setToolTip(
            "Clear this finished session without handing it off. Nothing is written to Anki."
        )
        self.handoff_btn.setDefault(True)
        for b, choice in (
            (self.handoff_btn, "handoff"),
            (self.later_btn, "later"),
            (self.decline_btn, "decline"),
        ):
            qconnect(b.clicked, lambda _=False, c=choice: self._choose(cast(Choice, c)))
        row.addWidget(self.decline_btn)
        row.addStretch(1)
        row.addWidget(self.later_btn)
        row.addWidget(self.handoff_btn)
        layout.addLayout(row)

    def _choose(self, choice: Choice) -> None:
        self.choice = choice
        self.accept()


def ask(parent: QWidget | None, text: HandoffText) -> Choice:
    """The confirmation (tests replace this)."""
    dialog = HandoffDialog(parent, text)
    dialog.exec()
    return dialog.choice


def offer_handoff(
    ctx: AddonContext,
    parent: QWidget,
    key: str,
    on_done: Callable[[], None] | None = None,
) -> None:
    """Plan, confirm and run the handoff of the finished session saved under
    ``key``. ``on_done`` runs once the session is no longer pending (handed
    off or declined), not on "Not now" or a failure."""
    if key in ctx.handoffs:
        tooltip("This session's handoff is already running.", parent=parent)
        return
    storage = ctx.storage()
    saved = sessions.load(storage, key)
    if saved is None or sessions.save_status(saved) != "handoff":
        tooltip("Nothing to hand off: this session was handed off or cleared already.")
        if on_done is not None:
            on_done()
        return
    settings = HandoffSettings.from_config(ctx.config())
    scope = cast(dict[str, Any], saved["addon"].get("scope") or {})
    scope_deck = scope.get("deckId")

    def op(col: Any) -> tuple[HandoffPlan, Forecast | None, datetime]:
        plan = plan_handoff(col, saved, settings)
        top = top_deck_for(col, plan, scope_deck if isinstance(scope_deck, int) else None)
        fc = forecast(col, plan, top) if top is not None else None
        when = (
            fc.available_from
            if fc is not None
            else next_day_start(datetime.now(), col.get_preferences().scheduling.rollover)
        )
        return plan, fc, when

    def planned(result: tuple[HandoffPlan, Forecast | None, datetime]) -> None:
        plan, fc, when = result
        choice = ask(parent, describe(plan, fc, when))
        if choice == "handoff":
            _run(ctx, parent, key, saved, plan, fc, on_done)
        elif choice == "decline":
            sessions.decline_handoff(storage, key, saved, launch.now_ms())
            tooltip("Not handed off: the finished session was cleared.")
            if on_done is not None:
                on_done()

    def failed(exc: Exception) -> None:
        showWarning(f"Recall Drill couldn't plan the handoff: {exc}", parent=parent)

    QueryOp(parent=parent, op=op, success=planned).failure(failed).run_in_background()


def _run(
    ctx: AddonContext,
    parent: QWidget,
    key: str,
    saved: dict[str, Any],
    plan: HandoffPlan,
    fc: Forecast | None,
    on_done: Callable[[], None] | None,
) -> None:
    ctx.handoffs.add(key)
    storage = ctx.storage()

    def success(_changes: Any) -> None:
        ctx.handoffs.discard(key)
        try:
            sessions.complete_handoff(storage, key, saved, handoff_line(plan, fc, launch.now_ms()))
        except OSError as exc:
            showWarning(
                f"Handed off, but Recall Drill couldn't write its history line: {exc}",
                parent=parent,
            )
        else:
            tooltip(DONE_MESSAGE, period=8000)
        if on_done is not None:
            on_done()

    def failure(exc: Exception) -> None:
        ctx.handoffs.discard(key)
        mw.update_undo_actions()
        showWarning(failure_text(exc), parent=parent, title="Recall Drill")

    CollectionOp(parent=parent, op=lambda col: apply_handoff(col, plan)).success(success).failure(
        failure
    ).run_in_background()
