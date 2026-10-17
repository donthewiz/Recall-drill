"""The Math Path window that opens when the reviewer shows a Math Path card (v0.1)."""

from __future__ import annotations

from typing import Any

from aqt import mw
from aqt.qt import QTimer, qconnect
from aqt.utils import tooltip

from ..notes import RecipeNote
from ..pages import Command, PageView
from ..review import EFFECT_CLOSE, EFFECT_RATE, ReviewSession
from ..views import review_view
from . import review_bridge
from .context import AddonContext
from .learn_window import POLL_MS, StorageHistory, now_iso, now_ms
from .page_window import PageWindow


class ReviewWindow(PageWindow):
    GEOM_KEY = "mathpath_review"
    DEFAULT_SIZE = (1000, 880)

    def __init__(self, ctx: AddonContext, note: RecipeNote, card_id: int) -> None:
        super().__init__(ctx, "Math Path: review")
        assert note.recipe is not None
        self.card_id = card_id
        self.note = note
        ctx.bank.prepare(note.recipe)
        self.session = ReviewSession(
            note,
            card_id,
            ctx.bank.take,
            StorageHistory(ctx.storage()),
            clock=now_ms,
            now_iso=now_iso,
        )
        self._notice = ""
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        qconnect(self._timer.timeout, self._poll)
        self._sync_timer()
        self.redraw()

    def page_view(self) -> PageView:
        screen = review_view.render(self.session, notice=self._notice)
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
        if effect == EFFECT_CLOSE:
            self.close()
        elif effect == EFFECT_RATE:
            self.rate()
        self._sync_timer()

    def rate(self) -> None:
        """Next: apply the rating to this card through the reviewer, then close."""
        ok, why = review_bridge.rate_current(self.card_id, self.session.rating)
        self.session.applied_rating(ok, why)
        if ok:
            self.close()
            return
        self._notice = why
        self.redraw()
        tooltip(why)

    def _sync_timer(self) -> None:
        from ..review import PREPARING

        if self.session.screen == PREPARING:
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()

    def _poll(self) -> None:
        if self.session.problem_ready():
            self._timer.stop()
            self.redraw()

    def on_closed(self) -> None:
        self._timer.stop()
        self.session.log()  # a finished problem that was never rated still goes in the history


def open_review(ctx: AddonContext, note: RecipeNote, card_id: int) -> ReviewWindow | None:
    """Open (or bring forward) the review window for a card; a window for another card closes."""
    if mw is None or mw.col is None:  # pyright: ignore[reportUnnecessaryComparison]
        return None
    for w in list(ctx.windows):
        if isinstance(w, ReviewWindow):
            if w.card_id == card_id:
                w.showNormal()
                w.raise_()
                w.activateWindow()
                return w
            w.close()
    window = ReviewWindow(ctx, note, card_id)
    window.show()
    window.raise_()
    window.activateWindow()
    return window


def current_math_path_note(card: Any) -> RecipeNote | None:
    """The Math Path note of ``card`` (None for any other card)."""
    from ..anki_io import notetype

    note = card.note()
    if not notetype.is_math_path_note(note):
        return None
    return notetype.read_note(note)
