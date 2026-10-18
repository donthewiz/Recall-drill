"""A window that is one ``AnkiWebView`` showing a page Python draws (v0.1)."""

from __future__ import annotations

from typing import Any

from aqt import gui_hooks, mw
from aqt.qt import QCloseEvent, QDialog, Qt, QVBoxLayout, QWidget
from aqt.theme import theme_manager
from aqt.utils import disable_help_button, restoreGeom, saveGeom
from aqt.webview import AnkiWebView

from .. import pages
from ..pages import Command, PageView
from .context import AddonContext


def _parent(parent: Any) -> QWidget | None:
    """The window's Qt parent: the one given, else Anki's main window (None outside Anki)."""
    if isinstance(parent, QWidget):
        return parent
    return mw if isinstance(mw, QWidget) else None


class PageWindow(QDialog):
    """Base for the learn, import and progress windows.

    A subclass implements :meth:`page_view` (the whole screen) and :meth:`on_command`; every
    command from the page is followed by a redraw. Only this window is styled (by the page's own
    CSS): never ``QApplication.setStyleSheet``."""

    GEOM_KEY = "mathpath_window"
    DEFAULT_SIZE = (1000, 860)

    def __init__(self, ctx: AddonContext, title: str, parent: Any = None) -> None:
        super().__init__(_parent(parent))
        self.ctx = ctx
        self._closing = False
        self._shown: pages.Shown | None = None
        self.setWindowTitle(title)
        self.setProperty("mpWindow", True)
        disable_help_button(self)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.web = AnkiWebView(self, title="math path")
        self.web.set_bridge_command(self._on_bridge, self)
        self.web.stdHtml(
            pages.shell_body(),
            css=pages.css_urls(ctx.folder),
            js=pages.script_urls(ctx.folder),
            context=self,
        )
        layout.addWidget(self.web)
        self.resize(*self.DEFAULT_SIZE)
        restoreGeom(self, self.GEOM_KEY)
        gui_hooks.theme_did_change.append(self.redraw)
        ctx.windows.append(self)

    # -- to implement -------------------------------------------------------------

    def page_view(self) -> PageView:
        raise NotImplementedError

    def on_command(self, cmd: Command) -> None:
        raise NotImplementedError

    # -- drawing --------------------------------------------------------------------

    @property
    def night(self) -> bool:
        return bool(theme_manager.night_mode)

    def redraw(self, keep: bool = False) -> None:
        """Draw the whole screen. ``keep`` (after a focus, field or text message) leaves the live
        fields in the page and sends nothing when the screen is unchanged."""
        if self._closing:
            return
        js, self._shown = pages.redraw_call(self.page_view(), keep, self._shown)
        if js is not None:
            self.web.eval(js)

    def _on_bridge(self, cmd: str) -> Any:
        parsed = pages.parse_command(cmd)
        if parsed is None or self._closing:
            return None
        self.on_command(parsed)
        self.redraw(keep=parsed.kind in pages.KEEP_KINDS)
        return None

    # -- closing ----------------------------------------------------------------------

    def on_escape(self) -> None:
        """Esc with the focus outside the page (inside it the page sends ``mp:esc``). A dialog
        closes; the learn and review windows only close their help text, never the window."""
        self.close()

    def reject(self) -> None:
        self.on_escape()

    def on_closed(self) -> None:
        """Called once the window is really closing (after :meth:`allow_close` said yes)."""

    def allow_close(self) -> bool:
        """A subclass may ask first (a session in progress); False keeps the window open."""
        return True

    def closeEvent(self, a0: QCloseEvent | None) -> None:
        if a0 is not None and not self.allow_close():
            a0.ignore()
            return
        self._closing = True
        self.on_closed()
        saveGeom(self, self.GEOM_KEY)
        try:
            gui_hooks.theme_did_change.remove(self.redraw)
        except ValueError:
            pass
        if self in self.ctx.windows:
            self.ctx.windows.remove(self)
        self.web.cleanup()
        if a0 is not None:  # not super(): QDialog's closeEvent calls reject(), which is Esc here
            a0.accept()
