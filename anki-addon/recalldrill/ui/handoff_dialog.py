"""The handoff, from the drill window's Done screen or the setup panel's banner.

1. Plan off the main thread (``QueryOp``): fresh snapshots, the forecast.
2. Confirm: **Hand off** / **Not now** (the session stays pending) /
   **Don't hand off** (the save goes, with a declined history line).
3. Hand off: ``apply_handoff`` inside ``CollectionOp``, so it's one undo step
   and the main window refreshes. On success the history line is written and
   the save deleted; on failure the session stays pending and the error shows.

``apply_handoff`` is one of the add-on's three collection writes (the others are
``release.apply_release``, from the waiting-cards dialog, and
``holdback.apply_hold_back``, from the setup panel). After a handoff the light
outcomes export is rewritten (``export_ui``).
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal, cast

from aqt import mw
from aqt.operations import CollectionOp, QueryOp
from aqt.qt import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QMessageBox,
    Qt,
    QVBoxLayout,
    QWidget,
    qconnect,
)
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
from ..layers import section_label
from . import exam_tracker, style
from .context import AddonContext
from .export_ui import export_in_background

Choice = Literal["handoff", "later", "decline"]

_COUNT = re.compile(r"^Hand off (\d+ cards?)")
_FACT = re.compile(r"^([A-Z][A-Za-z ]{1,20}): (.*)$")


def title_for(text: HandoffText) -> tuple[str, str]:
    """("Hand off 6 cards to Anki", what is done to them): the dialog's title from the
    headline's count, and the rest of the headline as its first fact."""
    m = _COUNT.match(text.headline)
    if m is None:
        return text.headline, ""
    rest = text.headline[m.end() :].lstrip(": ").strip()
    return f"Hand off {m.group(1)} to Anki", rest[:1].upper() + rest[1:]


def fact_rows(text: HandoffText) -> list[tuple[str, str]]:
    """The facts as (label, value): the headline's action first, then each line ("Siblings: 6."
    is ("Siblings", "6."); a line with no label has an empty one)."""
    rows: list[tuple[str, str]] = []
    _title, action = title_for(text)
    if action:
        rows.append(("Handoff", action))
    for line in text.lines:
        m = _FACT.match(line)
        rows.append((m.group(1), m.group(2)) if m is not None else ("", line))
    return rows


def where_text(saved: dict[str, Any]) -> str:
    """The deck (parents joined with " › ") and section of a finished session, for the muted
    line under the dialog's title."""
    deck = " › ".join(str(saved.get("deckName") or "").split("::"))
    addon = cast(dict[str, Any], saved.get("addon") or {})
    options = cast(dict[str, Any], addon.get("selectOptions") or {})
    section = section_label(str(options.get("extra_tag") or ""))
    return " · ".join(x for x in (deck, section) if x)


class HandoffDialog(QDialog):
    def __init__(self, parent: QWidget | None, text: HandoffText) -> None:
        super().__init__(parent)
        disable_help_button(self)
        self.setWindowTitle("Recall Drill: hand off to Anki")
        self.choice: Choice = "later"
        self.text = text
        root = style.install(self)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(22, 18, 22, 16)
        layout.setSpacing(12)

        title, _action = title_for(text)
        self.headline = style.text_label(title, "title")
        layout.addWidget(self.headline)
        self.where = style.text_label(text.where, "muted")
        self.where.setVisible(bool(text.where))
        layout.addWidget(self.where)

        # The facts: a small two-column list in a card.
        self.facts_card, fl = style.card_frame()
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)
        for i, (name, value) in enumerate(fact_rows(text)):
            if name:
                grid.addWidget(style.text_label(name, "muted"), i, 0, Qt.AlignmentFlag.AlignTop)
                grid.addWidget(style.text_label(value), i, 1)
            else:
                grid.addWidget(style.text_label(value), i, 0, 1, 2)
        fl.addLayout(grid)
        layout.addWidget(self.facts_card)

        # The forecast, in its own card.
        self.forecast_card, cl = style.card_frame()
        self.forecast = style.text_label("\n".join(text.forecast))
        cl.addWidget(self.forecast)
        self.forecast_card.setVisible(bool(text.forecast))
        self.forecast.setVisible(bool(text.forecast))
        layout.addWidget(self.forecast_card)

        self.warnings = style.note("\n".join(f"⚠ {w}" for w in text.warnings), "warn")
        self.warnings.setVisible(bool(text.warnings))
        layout.addWidget(self.warnings)
        layout.addWidget(
            style.text_label('One undo step: Edit → Undo "Recall Drill handoff".', "muted")
        )

        row = QHBoxLayout()
        row.setSpacing(8)
        self.handoff_btn = style.button("Hand off", "primary")
        self.later_btn = style.button("Not now")
        self.decline_btn = style.button("Don't hand off", "ghost")
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
        self.setMinimumWidth(520)

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
        text = dataclasses.replace(describe(plan, fc, when), where=where_text(saved))
        choice = ask(parent, text)
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
            export_in_background(ctx)  # v0.3: the light outcomes export, quietly
            exam_tracker.request_refresh()  # v0.4: the deck screen's exam numbers
        if on_done is not None:
            on_done()

    def failure(exc: Exception) -> None:
        ctx.handoffs.discard(key)
        mw.update_undo_actions()
        showWarning(failure_text(exc), parent=parent, title="Recall Drill")

    CollectionOp(parent=parent, op=lambda col: apply_handoff(col, plan)).success(success).failure(
        failure
    ).run_in_background()


def confirm_finish_early(parent: QWidget | None, counts: sessions.FinishEarlyCounts) -> bool:
    """ "Finish with K cards?" (the drill window's and the setup panel's button):
    **Finish** cuts the save, **Cancel** leaves it as it is."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle("Recall Drill")
    box.setText(sessions.finish_early_confirmation(counts))
    finish = box.addButton("Finish", QMessageBox.ButtonRole.AcceptRole)
    cancel = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(cancel)
    box.exec()
    return box.clickedButton() is finish
