"""The learn session window (v0.1): Study → Faded → Plan → Solo, then the handoff to Anki."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from anki.collection import Collection, OpChanges
from aqt.operations import CollectionOp
from aqt.qt import QMessageBox, QTimer, qconnect
from aqt.utils import showWarning, tooltip

from ..anki_io import handoff
from ..anki_io.undo import StepFailed
from ..notes import RecipeNote
from ..pages import Command, PageView
from ..progress import ProgressStore
from ..session import (
    EFFECT_CLOSE,
    EFFECT_END,
    EFFECT_HANDOFF,
    EFFECT_PROGRESS,
    PREPARING,
    SUMMARY,
    HistorySink,
    LearnSession,
)
from ..storage import HISTORY, Storage
from ..views import learn_view
from .context import AddonContext
from .page_window import PageWindow

POLL_MS = 150
"""How often a screen that is "Preparing…" asks whether its problem is ready."""


class StorageHistory(HistorySink):
    """History lines appended to ``history.jsonl``; a write that fails never stops the session."""

    def __init__(self, storage: Storage) -> None:
        self.storage = storage

    def append(self, record: dict[str, Any]) -> None:
        try:
            self.storage.append_jsonl(HISTORY, record)
        except OSError:
            pass


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_ms() -> int:
    return int(time.monotonic() * 1000)


@dataclass
class _Outcome:
    """What ``CollectionOp`` needs (the changes) plus the plan, for the session."""

    changes: OpChanges
    plan: handoff.HandoffPlan


class LearnWindow(PageWindow):
    GEOM_KEY = "mathpath_learn"
    DEFAULT_SIZE = (1040, 900)

    def __init__(
        self,
        ctx: AddonContext,
        notes: list[RecipeNote],
        section: str = "",
        store: ProgressStore | None = None,
        pending: list[int] | None = None,
    ) -> None:
        super().__init__(ctx, "Math Path: learn")
        storage = ctx.storage()
        self.store = store or ProgressStore(storage)
        for n in notes:
            if n.recipe is not None:
                ctx.bank.prepare(n.recipe)  # all the first problems are made while the window opens
        self.session = LearnSession(
            notes,
            self.store,
            StorageHistory(storage),
            ctx.bank.take,
            clock=now_ms,
            now_iso=now_iso,
            section=section,
            pending=pending or (),
        )
        self._handoff_running = False
        self._close_after_handoff = False
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        qconnect(self._timer.timeout, self._poll)
        self.setWindowTitle(f"Math Path: learn {section}".strip())
        self._sync_timer()
        self.redraw()

    # -- the page -----------------------------------------------------------------------

    def page_view(self) -> PageView:
        screen = learn_view.render(self.session, show_progress=self.ctx.progress_opener is not None)
        return PageView(
            html=screen.html,
            fields=screen.fields,
            texts=screen.texts,
            readonly=screen.readonly,
            focus=screen.focus,
            night=self.night,
        )

    def on_command(self, cmd: Command) -> None:
        effect = self.session.command(cmd)
        self._effect(effect)
        self._sync_timer()

    def _effect(self, effect: str) -> None:
        if effect == EFFECT_CLOSE:
            self.close()
        elif effect == EFFECT_PROGRESS:
            if self.ctx.progress_opener is not None:
                self.ctx.progress_opener()
        elif effect == EFFECT_END:
            self.end_session()
        elif effect == EFFECT_HANDOFF:
            self.run_handoff()

    # -- waiting for a problem -----------------------------------------------------------------

    def _sync_timer(self) -> None:
        if self.session.screen == PREPARING:
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()

    def _poll(self) -> None:
        if self.session.problem_ready():
            self._timer.stop()
            self.redraw()
        elif self.session.screen != PREPARING:
            self._timer.stop()

    # -- ending ----------------------------------------------------------------------------------

    def _ask_handoff(self) -> bool | None:
        """ "Hand off the N learned problems now?" (default yes); None for Cancel."""
        n = len(self.session.learned_notes)
        box = QMessageBox(self)
        box.setWindowTitle("Math Path")
        box.setText(f"Hand off the {n} learned problem{'' if n == 1 else 's'} now?")
        box.setInformativeText(
            "They go to the front of Anki's new cards and come back in your reviews tomorrow. "
            "Edit → Undo takes the handoff back."
        )
        yes = box.addButton("Hand off", QMessageBox.ButtonRole.YesRole)
        no = box.addButton("Not now", QMessageBox.ButtonRole.NoRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(yes)
        box.exec()
        clicked = box.clickedButton()
        if clicked is yes:
            return True
        if clicked is no:
            return False
        return None

    def end_session(self) -> None:
        """End session: ask about the handoff if something was learned, then show the summary."""
        if self.session.learned_notes:
            answer = self._ask_handoff()
            if answer is None:
                return
            effect = self.session.end_early()
            if answer:
                self._effect(effect)
            return
        self.session.end_early()

    def allow_close(self) -> bool:
        if self._handoff_running:
            tooltip("Handing the problems to Anki…")
            return False
        if self.session.learned_notes:
            answer = self._ask_handoff()
            if answer is None:
                return False
            if answer:
                self._close_after_handoff = True
                self.session.end_early()
                self.run_handoff()
                return False
        return True

    # -- the handoff -----------------------------------------------------------------------------

    def run_handoff(self) -> None:
        nids = list(self.session.learned_notes)
        if not nids or self._handoff_running:
            return
        self._handoff_running = True

        def op(col: Collection) -> _Outcome:
            plan = handoff.plan_handoff(col, nids)
            return _Outcome(handoff.apply_handoff(col, plan), plan)

        def done(result: _Outcome) -> None:
            self._handoff_running = False
            self.session.handoff_done(result.plan.nids, result.plan.cids)
            self.redraw()
            if self._close_after_handoff:
                QTimer.singleShot(0, self.close)  # after the close event that started this

        def failed(exc: Exception) -> None:
            self._handoff_running = False
            self._close_after_handoff = False
            self.session.handoff_failed(_failure_text(exc))
            self.redraw()
            showWarning(f"Math Path: the handoff failed.\n\n{_failure_text(exc)}")

        CollectionOp(self, op).success(done).failure(failed).run_in_background()

    def on_escape(self) -> None:
        self.on_command(Command("esc"))  # closes the help text; never the window
        self.redraw()

    def on_closed(self) -> None:
        self._timer.stop()


def _failure_text(exc: Exception) -> str:
    if isinstance(exc, StepFailed):
        if exc.rolled_back:
            return f"What it had done was undone, so nothing changed in Anki. ({exc})"
        return (
            "It failed partway and undoing it failed too. Check Edit → Undo: "
            f"“{handoff.UNDO_LABEL}” reverts what it did. ({exc})"
        )
    return str(exc)


__all__ = ["LearnWindow", "SUMMARY"]
