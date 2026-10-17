"""The progress map window (v0.1): sections in textbook order, a chip per recipe, Learn."""

from __future__ import annotations

from typing import Any

from aqt import gui_hooks, mw
from aqt.utils import tooltip

from ..anki_io import courses
from ..pages import Command, PageView
from ..progress import ProgressStore
from ..progress_controller import (
    EFFECT_CLOSE,
    EFFECT_IMPORT,
    EFFECT_LEARN,
    EFFECT_REFRESH,
    ProgressController,
)
from ..views import progress_view
from .context import AddonContext
from .launch import open_session, remember_course, remembered_course
from .page_window import PageWindow


class ProgressWindow(PageWindow):
    GEOM_KEY = "mathpath_progress"
    DEFAULT_SIZE = (1100, 820)

    def __init__(self, ctx: AddonContext, store: ProgressStore | None = None) -> None:
        super().__init__(ctx, "Math Path: progress")
        self.store = store or ProgressStore(ctx.storage())
        available = self._read_courses()
        start = remembered_course(ctx, available)
        self.ctl = ProgressController(
            available,
            self.store.all(),
            ctx.config(),
            selected=start.name if start is not None else "",
        )
        self.notice = ""
        gui_hooks.operation_did_execute.append(self._on_operation)
        self.redraw()

    # -- data -----------------------------------------------------------------------------

    def _read_courses(self) -> list[Any]:
        return courses.read_courses(mw.col) if mw is not None and mw.col is not None else []

    def reload(self) -> None:
        """Read everything again: the learn window keeps its own store, so ours goes stale."""
        self.store = ProgressStore(self.ctx.storage())
        self.ctl.update(self._read_courses(), self.store.all())
        self.ctl.cfg = self.ctx.config()

    def _on_operation(self, changes: Any, handler: Any) -> None:
        if self._closing:
            return
        self.reload()
        self.redraw()

    # -- the page -------------------------------------------------------------------------

    def page_view(self) -> PageView:
        html = progress_view.render(self.ctl, notice=self.notice)
        return PageView(html=html, night=self.night)

    def on_command(self, cmd: Command) -> None:
        self.notice = ""
        effect = self.ctl.command(cmd)
        if effect == EFFECT_CLOSE:
            self.close()
        elif effect == EFFECT_IMPORT:
            from .import_dialog import open_import_dialog

            open_import_dialog(self.ctx)
        elif effect == EFFECT_REFRESH:
            self.reload()
        elif effect == EFFECT_LEARN:
            self._learn()
        elif cmd.kind == "select":
            if self.ctl.selected:
                remember_course(self.ctx, self.ctl.selected)

    def _learn(self) -> None:
        course = self.ctl.course
        row = self.ctl.row(self.ctl.learn_did)
        if course is None or row is None:
            return
        for w in self.ctx.windows:
            if type(w).__name__ == "LearnWindow":
                w.showNormal()
                w.raise_()
                w.activateWindow()
                tooltip("Finish or close the open learn session first.")
                return
        open_session(self.ctx, course, row.section, self.store)

    def on_escape(self) -> None:
        self.close()

    def on_closed(self) -> None:
        try:
            gui_hooks.operation_did_execute.remove(self._on_operation)
        except ValueError:
            pass


def open_progress(ctx: AddonContext) -> ProgressWindow | None:
    """Tools → Math Path → Progress…: one window, brought forward when it is already open."""
    if mw is None or mw.col is None:
        return None
    for w in ctx.windows:
        if isinstance(w, ProgressWindow):
            w.reload()
            w.redraw()
            w.showNormal()
            w.raise_()
            w.activateWindow()
            return w
    window = ProgressWindow(ctx)
    window.show()
    window.raise_()
    window.activateWindow()
    return window
