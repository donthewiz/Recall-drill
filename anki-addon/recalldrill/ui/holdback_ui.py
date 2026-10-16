"""Hold back and release held cards (v0.3): the setup panel's two flows.

- **Hold back**: plan (``QueryOp``), confirm, apply as one undo step
  (``CollectionOp``, ``anki_io/holdback.py``). Never runs without the click that
  asks for it (turning the switch on, or **Hold back N**).
- **Release held**: turning the switch off asks "Release N held cards to Anki
  now?". Yes plans and applies the existing release (``anki_io/release.py``,
  all held cards, queue positions kept) and writes its history line; No leaves
  them suspended, listed as waiting.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from aqt.operations import CollectionOp, QueryOp
from aqt.qt import QMessageBox, QWidget
from aqt.utils import showWarning, tooltip

from .. import history_store
from ..anki_io import holdback as hb
from ..anki_io.release import apply_release, history_line, plan_release
from ..anki_io.release import failure_text as release_failure
from ..holdback import release_question
from .context import AddonContext

TITLE = "Recall Drill: hold back"


def confirm_hold_back(parent: QWidget, plan: hb.HoldBackPlan) -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle(TITLE)
    box.setIcon(QMessageBox.Icon.Question)
    box.setText(hb.describe(plan))
    box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    box.setDefaultButton(QMessageBox.StandardButton.No)
    return box.exec() == QMessageBox.StandardButton.Yes


def ask_release_held(parent: QWidget, n: int) -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle(TITLE)
    box.setIcon(QMessageBox.Icon.Question)
    box.setText(release_question(n))
    box.setInformativeText(
        "Yes unsuspends them as plain new cards, keeping their place in the new queue. "
        "No leaves them suspended; they stay listed in Tools → Recall Drill → More → Waiting cards."
    )
    box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    box.setDefaultButton(QMessageBox.StandardButton.No)
    return box.exec() == QMessageBox.StandardButton.Yes


def hold_back(parent: QWidget, ctx: AddonContext, did: int, then: Callable[[], None]) -> None:
    """Plan, confirm, apply. ``then`` runs after the write or when nothing is written."""
    storage = ctx.storage()

    def planned(plan: hb.HoldBackPlan) -> None:
        if not plan.has_changes:
            tooltip("Nothing to hold back: no new card is out of Anki undrilled.", parent=parent)
            then()
            return
        if not confirm_hold_back(parent, plan):
            then()
            return

        def done(_changes: Any) -> None:
            try:
                history_store.append_holdback(
                    storage, str(plan.did), hb.history_line(plan, time.time() * 1000)
                )
            except Exception as exc:
                showWarning(f"The cards were held back, but the history line failed: {exc}")
            freed = f", released {plan.undrillable_held} undrillable" if plan.release else ""
            tooltip(f"Held back {plan.cards} cards{freed}. Edit → Undo reverts it.", parent=parent)
            then()

        CollectionOp(parent, lambda col: hb.apply_hold_back(col, plan)).success(done).failure(
            lambda exc: showWarning(hb.failure_text(exc))
        ).run_in_background()

    QueryOp(
        parent=parent, op=lambda col: hb.plan_hold_back(col, storage, did), success=planned
    ).run_in_background()


def release_held(parent: QWidget, ctx: AddonContext, did: int, then: Callable[[], None]) -> None:
    """Turning the switch off: offer to release the deck's held cards now."""
    storage = ctx.storage()

    def op(col: Any) -> Any:
        cids = hb.held_cards(col, did)
        return plan_release(col, did, cids, "all") if cids else None

    def planned(plan: Any) -> None:
        if plan is None or not plan.has_changes:
            then()
            return
        if not ask_release_held(parent, plan.cards):
            then()
            return

        def done(_changes: Any) -> None:
            try:
                history_store.append_release(
                    storage, str(plan.did), history_line(plan, time.time() * 1000)
                )
            except Exception as exc:
                showWarning(f"The cards were released, but the history line failed: {exc}")
            tooltip(f"Released {plan.cards} cards to Anki. Edit → Undo reverts it.", parent=parent)
            then()

        CollectionOp(parent, lambda col: apply_release(col, plan)).success(done).failure(
            lambda exc: showWarning(release_failure(exc))
        ).run_in_background()

    QueryOp(parent=parent, op=op, success=planned).run_in_background()
