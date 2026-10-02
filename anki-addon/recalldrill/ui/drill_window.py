"""The drill window: renders ``DrillController.view()``, forwards input, runs effects.

Behavior lives in the controller (``controller.py``) and HTML in
``drill_view.py``. This module only:

- shows the view (an ``AnkiWebView`` for the card area, native widgets for the
  answer box, buttons, progress and stats);
- forwards keys and clicks: Enter submits or continues, Esc reveals,
  Ctrl+Enter counts as correct, Ctrl+E edits in Anki, Ctrl+R replays audio;
- runs the effects: the dwell timer, audio, the flash, clearing the input;
- opens Anki's Browser for "Edit in Anki" and reads the card back when it closes;
- offers the finished session's handoff (``handoff_dialog``, the only write).
"""

from __future__ import annotations

import logging
from typing import Any

import aqt
from anki.cards import CardId
from anki.errors import NotFoundError
from aqt import mw
from aqt.qt import (
    QCloseEvent,
    QDialog,
    QFont,
    QHBoxLayout,
    QKeyEvent,
    QKeySequence,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QShortcut,
    Qt,
    QTimer,
    QVBoxLayout,
    QWidget,
    qconnect,
)
from aqt.sound import av_player, play_clicked_audio
from aqt.theme import theme_manager
from aqt.utils import disable_help_button, restoreGeom, saveGeom, tooltip
from aqt.webview import AnkiWebView

from .. import drill_view, launch, sessions
from ..anki_io.build import rebuild_card
from ..anki_io.notetypes import MappingTable, load_overrides
from ..controller import (
    FLASH_MS,
    ClearInput,
    DrillController,
    Effect,
    Flash,
    PersistFailed,
    PlayAnswerAudio,
    PlayQuestionAudio,
    StartDwell,
    StopAudio,
    ViewModel,
)
from ..sessions import SessionStore
from .context import AddonContext
from .handoff_dialog import offer_handoff

log = logging.getLogger(__name__)

GEOM_KEY = "recalldrill_drill"
HANDOFF_TOOLTIP = "Hand off to Anki: tag, unsuspend and schedule these cards (one undo step)"

_DOT_COLORS = {
    # (light, night): the web app's --text-muted, --warning, --accent, --success.
    "new": ("#8E97A4", "#647082"),
    "encoding": ("#D97706", "#F59E0B"),
    "ready": ("#2563EB", "#3B82F6"),
    "mastered": ("#16A34A", "#22C55E"),
}


def _button(text: str, tip: str = "") -> QPushButton:
    b = QPushButton(text)
    b.setAutoDefault(False)
    b.setDefault(False)
    b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    if tip:
        b.setToolTip(tip)
    return b


class DrillWindow(QDialog):
    """A non-modal drill window for one session (or its drill-again follow-up)."""

    def __init__(self, ctx: AddonContext, ctrl: DrillController, store: SessionStore) -> None:
        super().__init__(None, Qt.WindowType.Window)
        self.ctx = ctx
        self.ctrl = ctrl
        self.store = store
        self._closing = False
        self._flash: bool | None = None
        self._edit_browser: Any = None
        self._edit_item: int | None = None
        self._last_mode: str | None = None
        self._handed_off = False

        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        disable_help_button(self)
        self._dwell = QTimer(self)
        self._dwell.setSingleShot(True)
        qconnect(self._dwell.timeout, self._on_dwell)

        self._build_ui()
        for keys, fn in (
            ("Ctrl+E", self._edit),
            ("Ctrl+R", self._replay),
        ):
            sc = QShortcut(QKeySequence(keys), self)
            sc.setContext(Qt.ShortcutContext.WindowShortcut)
            qconnect(sc.activated, fn)

        # Where the reviewer would be: over the main window, until a saved
        # geometry (restoreGeom) says otherwise.
        self.setGeometry(mw.geometry())
        restoreGeom(self, GEOM_KEY)
        ctx.windows.append(self)
        self._update_title()

    # -- layout -------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)

        top = QHBoxLayout()
        self.detail_label = QLabel()
        self.mastered_label = QLabel()
        self.mastered_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        top.addWidget(self.detail_label, 1)
        top.addWidget(self.mastered_label)
        outer.addLayout(top)

        self.batch_bar = QProgressBar()
        self.batch_bar.setTextVisible(False)
        self.batch_bar.setFixedHeight(8)
        self.deck_bar = QProgressBar()
        self.deck_bar.setTextVisible(False)
        self.deck_bar.setFixedHeight(4)
        outer.addWidget(self.batch_bar)
        outer.addWidget(self.deck_bar)

        self.web = AnkiWebView(self, title="recall drill")
        self.web.set_bridge_command(self._on_bridge, self)
        self.web.stdHtml(
            drill_view.shell_body(FLASH_MS),
            css=["css/reviewer.css"],
            js=["js/mathjax.js", "js/vendor/mathjax/tex-chtml-full.js"],
            context=self,
        )
        outer.addWidget(self.web, 1)

        self.input = QLineEdit()
        font = QFont("Consolas")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(13)
        self.input.setFont(font)
        self.input.setMinimumHeight(36)
        outer.addWidget(self.input)

        row = QHBoxLayout()
        self.check_btn = _button("Check answer", "Enter")
        self.continue_btn = _button("Continue →", "Enter")
        self.reveal_btn = _button("Show target", "Esc: reveal the target")
        self.override_btn = _button("Count as correct", "Ctrl+Enter: count this as correct anyway")
        self.replay_btn = _button("▶ Replay", "Ctrl+R: replay the card's audio")
        self.edit_btn = _button("Edit in Anki", "Ctrl+E: open this card in Anki's Browser")
        self.done_edit_btn = _button("Done editing", "Read the card back from Anki now")
        self.end_btn = _button("End session", "Save and stop")
        self.next_batch_btn = _button("Next batch →", "Enter")
        self.save_stop_btn = _button("Save and stop")
        self.again_btn = _button("Drill these cards again")
        self.handoff_btn = _button("Hand off", HANDOFF_TOOLTIP)
        self.close_btn = _button("Close")
        for b, fn in (
            (self.check_btn, self._enter),
            (self.continue_btn, self._enter),
            (self.reveal_btn, self._reveal),
            (self.override_btn, self._override),
            (self.replay_btn, self._replay),
            (self.edit_btn, self._edit),
            (self.done_edit_btn, self._done_editing),
            (self.end_btn, self._end_session),
            (self.next_batch_btn, self._next_batch),
            (self.save_stop_btn, self._end_session),
            (self.again_btn, self._drill_again),
            (self.handoff_btn, self._handoff),
            (self.close_btn, self.close),
        ):
            qconnect(b.clicked, fn)
        for b in (
            self.check_btn,
            self.continue_btn,
            self.reveal_btn,
            self.override_btn,
            self.next_batch_btn,
            self.save_stop_btn,
            self.again_btn,
            self.handoff_btn,
        ):
            row.addWidget(b)
        row.addStretch(1)
        for b in (self.replay_btn, self.edit_btn, self.done_edit_btn, self.end_btn, self.close_btn):
            row.addWidget(b)
        outer.addLayout(row)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        outer.addWidget(self.status_label)
        self.dots_label = QLabel()
        self.dots_label.setWordWrap(True)
        self.dots_label.setTextFormat(Qt.TextFormat.RichText)
        outer.addWidget(self.dots_label)

    def _update_title(self) -> None:
        name = self.ctrl.settings.deck_name
        again = " (drill again)" if self.store.meta.is_drill_again else ""
        self.setWindowTitle(f"Recall Drill: {name}{again}")

    # -- session ------------------------------------------------------------

    def start(self) -> None:
        self.show()
        self._run(self.ctrl.start())
        self.activateWindow()

    def _set_session(self, ctrl: DrillController, store: SessionStore) -> None:
        self._dwell.stop()
        av_player.stop_and_clear_queue()
        self.ctrl = ctrl
        self.store = store
        self.input.clear()
        self._update_title()
        self._run(ctrl.start())

    # -- effects and rendering -----------------------------------------------

    def _run(self, effects: list[Effect]) -> None:
        for e in effects:
            if isinstance(e, StartDwell):
                self._dwell.start(e.ms)
            elif isinstance(e, ClearInput):
                self.input.clear()
            elif isinstance(e, StopAudio):
                av_player.stop_and_clear_queue()
            elif isinstance(e, PlayAnswerAudio):
                self._play(e.cid, "a")
            elif isinstance(e, PlayQuestionAudio):
                self._play(e.cid, "q")
            elif isinstance(e, Flash):
                self._flash = e.ok
            elif isinstance(e, PersistFailed):
                tooltip(f"Recall Drill couldn't save the session: {e.error}", period=6000)
            # Persisted, SessionComplete, SessionStopped, CollisionNotice: the
            # view already shows them.
        self._render()

    def _prepare(self, html: str) -> str:
        if mw.col is None:
            return html
        return mw.prepare_card_text_for_display(html)

    def _render(self) -> None:
        if self._closing:
            return
        v = self.ctrl.view()
        on_card = v.mode in ("trial", "feedback")
        body = (
            theme_manager.body_classes_for_card_ord(v.card_ord)
            if on_card
            else theme_manager.body_class()
        )
        done = self.ctrl.done_summary() if v.mode == "done" else None
        self.web.eval(drill_view.render_call(drill_view.render(v, self._prepare, body, done)))
        if self._flash is not None:
            self.web.eval(f"rdFlash({'true' if self._flash else 'false'});")
            self._flash = None
        self._render_widgets(v, on_card)
        self._last_mode = v.mode

    def _render_widgets(self, v: ViewModel, on_card: bool) -> None:
        p = v.progress
        detail = v.detail + (f" • {v.batch_label}" if v.batch_label else "")
        self.detail_label.setText(detail)
        mastered = f"{p.mastered} / {p.total} Mastered ({p.mastered_percent}%)"
        if p.is_batched:
            mastered += f" • Batch encoded {p.batch_encoded_percent}%"
        self.mastered_label.setText(mastered)
        self.batch_bar.setValue(p.batch_encoded_percent)
        self.deck_bar.setValue(p.deck_encoded_percent)
        self.deck_bar.setVisible(p.is_batched)

        b = v.buttons
        self.input.setVisible(on_card)
        if on_card:
            if v.input_read_only:
                self.input.clear()
            self.input.setReadOnly(v.input_read_only or v.processing or v.editing or b.continue_)
            self.input.setPlaceholderText(v.placeholder)
        self.check_btn.setText(v.check_label)
        self.check_btn.setVisible(on_card and not b.continue_)
        self.check_btn.setEnabled(b.check)
        self.continue_btn.setVisible(on_card and b.continue_)
        self.reveal_btn.setVisible(on_card and b.reveal)
        self.override_btn.setVisible(on_card and b.override)
        self.replay_btn.setVisible(on_card)
        self.edit_btn.setVisible(on_card and not v.editing)
        self.edit_btn.setEnabled(b.edit)
        self.done_edit_btn.setVisible(on_card and v.editing)
        self.end_btn.setVisible(on_card)
        self.end_btn.setEnabled(b.save)
        batch = v.mode == "batch_done"
        self.next_batch_btn.setVisible(batch)
        self.save_stop_btn.setVisible(batch)
        done = v.mode == "done"
        summary = self.ctrl.done_summary() if done else None
        again = summary is not None and bool(summary.drill_again)
        self.again_btn.setVisible(again)
        if summary is not None and again:
            self.again_btn.setText(summary.drill_again_label)
        # A drill-again session has no handoff of its own.
        self.handoff_btn.setVisible(
            done
            and self.ctrl.finished == "complete"
            and not self.store.meta.is_drill_again
            and not self._handed_off
        )
        self.close_btn.setVisible(done)

        s = v.stats
        self.status_label.setText(
            f"New ({p.new})   Encoding ({p.encoding})   Ready ({p.ready})   "
            f"Mastered ({p.mastered})        {s.text}"
        )
        night = 1 if theme_manager.night_mode else 0
        dots = "".join(
            f'<span style="color:{_DOT_COLORS.get(d.status, _DOT_COLORS["new"])[night]};'
            f'font-size:{"20" if d.current else "14"}px">'
            f"{'◉' if d.current else '●'}</span> "
            for d in v.dots
        )
        self.dots_label.setText(dots)
        # Keys go to the answer box (read-only on a presentation beat, where
        # Enter still continues) or, between screens, to the window itself.
        if on_card:
            self.input.setFocus()
        else:
            self.setFocus()

    # -- input --------------------------------------------------------------

    def keyPressEvent(self, a0: QKeyEvent | None) -> None:  # noqa: N802 (Qt override)
        evt = a0
        assert evt is not None
        key = evt.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if evt.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self._override()
            else:
                self._enter()
            return
        if key == Qt.Key.Key_Escape:
            self._reveal()
            return
        super().keyPressEvent(evt)

    def reject(self) -> None:
        # QDialog's Esc closes the dialog; here Esc reveals the target.
        self._reveal()

    def _on_bridge(self, cmd: str) -> Any:
        if cmd.startswith("play:"):
            v = self.ctrl.view()
            card = self._card(v.cid)
            if card is not None:
                play_clicked_audio(cmd, card)
        elif cmd == "rd:enter":
            self._enter()
        elif cmd == "rd:ctrl-enter":
            self._override()
        elif cmd == "rd:edit":
            self._edit()
        elif cmd == "rd:replay":
            self._replay()
        elif cmd == "close":
            # AnkiWebView sends this on Esc in the page.
            self._reveal()
        if self.input.isVisible():
            self.input.setFocus()
        return None

    def _enter(self) -> None:
        v = self.ctrl.view()
        if v.mode == "batch_done":
            self._next_batch()
        elif v.buttons.continue_:
            self._run(self.ctrl.continue_())
        elif v.buttons.check:
            self._run(self.ctrl.submit(self.input.text()))

    def _override(self) -> None:
        if self.ctrl.view().buttons.override:
            self._run(self.ctrl.override())

    def _reveal(self) -> None:
        if self.ctrl.view().mode in ("trial", "feedback"):
            self._run(self.ctrl.reveal())

    def _next_batch(self) -> None:
        self._run(self.ctrl.next_batch())

    def _end_session(self) -> None:
        self._flush_dwell()
        self._run(self.ctrl.save_and_stop())

    def _on_dwell(self) -> None:
        self._run(self.ctrl.dwell_elapsed())

    def _flush_dwell(self) -> None:
        """Commit a pending dwell now (the controller ignores actions during one)."""
        if self._dwell.isActive():
            self._dwell.stop()
            self._run(self.ctrl.dwell_elapsed())

    # -- audio ----------------------------------------------------------------

    def _card(self, cid: int | None) -> Any:
        col = mw.col
        if col is None or cid is None:
            return None
        try:
            return col.get_card(CardId(cid))
        except NotFoundError:
            return None

    def _play(self, cid: int, side: str) -> None:
        card = self._card(cid)
        if card is None:
            return
        av_player.play_tags(card.answer_av_tags() if side == "a" else card.question_av_tags())

    def _replay(self) -> None:
        v = self.ctrl.view()
        if v.mode in ("trial", "feedback") and v.cid is not None:
            self._play(v.cid, v.audio_side)

    # -- Edit in Anki -----------------------------------------------------------

    def _edit(self) -> None:
        if self.ctrl.view().mode not in ("trial", "feedback"):
            return
        req = self.ctrl.begin_edit()
        if req is None:
            return
        self._edit_item = req.item_id
        self._render()
        # card= selects the row, so the editor shows it (a new or a reused Browser).
        browser = aqt.dialogs.open(
            "Browser", mw, card=self._card(req.cid), search=(f"cid:{req.cid}",)
        )
        self._disconnect_browser()
        self._edit_browser = browser
        qconnect(browser.destroyed, self._on_browser_destroyed)

    def _disconnect_browser(self) -> None:
        b = self._edit_browser
        self._edit_browser = None
        if b is None:
            return
        try:
            b.destroyed.disconnect(self._on_browser_destroyed)
        except (TypeError, RuntimeError):
            pass  # already gone

    def _on_browser_destroyed(self, *_args: Any) -> None:
        # Browser.closeEvent saves the note before it tears down and deleteLater()s.
        self._edit_browser = None
        self._finish_edit()

    def _done_editing(self) -> None:
        b = self._edit_browser
        self._disconnect_browser()
        editor = getattr(b, "editor", None) if b is not None else None
        if editor is not None:
            editor.call_after_note_saved(self._finish_edit)
        else:
            self._finish_edit()

    def _finish_edit(self) -> None:
        if self._closing or not self.ctrl.view().editing:
            return
        col = mw.col
        item = self._edit_item
        if col is None or item is None:
            self._run(self.ctrl.cancel_edit())
            return
        src = self.ctrl.sources[item]
        rebuilt = rebuild_card(col, src, MappingTable(col, load_overrides(self.ctx.storage())))
        if rebuilt is None:
            tooltip("That card is gone or its answer is empty now: the drill keeps it as it was.")
            self._run(self.ctrl.cancel_edit())
            self.activateWindow()
            return
        self._run(
            self.ctrl.apply_card_edit(rebuilt.front, rebuilt.back, rebuilt.extra, rebuilt.source)
        )
        self.activateWindow()

    # -- done screen ----------------------------------------------------------

    def _drill_again(self) -> None:
        try:
            ctrl, store = launch.drill_again(
                self.ctx.storage(), self.ctrl, self.store, self.ctx.config()
            )
        except ValueError:
            return
        self._set_session(ctrl, store)

    def _handoff(self) -> None:
        if self.ctrl.finished != "complete" or self.store.meta.is_drill_again:
            return
        offer_handoff(self.ctx, self, self.store.meta.key, on_done=self._after_handoff)

    def _after_handoff(self) -> None:
        self._handed_off = True
        self._render()

    # -- closing ----------------------------------------------------------------

    def closeEvent(self, a0: QCloseEvent | None) -> None:  # noqa: N802 (Qt override)
        evt = a0
        assert evt is not None
        if self._closing or self.ctrl.finished is not None:
            self._cleanup()
            evt.accept()
            return
        if self.store.meta.is_drill_again:
            answer = QMessageBox.question(
                self,
                "Recall Drill",
                "Stop drilling these cards again? This drill-again session isn't kept.",
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Discard:
                evt.ignore()
                return
            self._flush_dwell()
            sessions.discard(self.ctx.storage(), self.store.meta.key)
        else:
            answer = QMessageBox.question(
                self,
                "Recall Drill",
                "Save and stop?\n\nSave keeps your place: Recall Drill this deck again "
                "and choose Resume. Discard deletes this session's progress.",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save,
            )
            if answer == QMessageBox.StandardButton.Save:
                self._flush_dwell()
                self._run(self.ctrl.save_and_stop())
            elif answer == QMessageBox.StandardButton.Discard:
                self._flush_dwell()
                sessions.discard(self.ctx.storage(), self.store.meta.key)
            else:
                evt.ignore()
                return
        self._cleanup()
        evt.accept()

    def save_and_close(self) -> None:
        """Profile closing: save where the session stands and close, no questions."""
        if not self._closing:
            self._flush_dwell()
            if self.ctrl.finished is None:
                self.ctrl.save_and_stop()
        self._closing = True
        self.close()

    def _cleanup(self) -> None:
        if getattr(self, "_cleaned", False):
            return
        self._cleaned = True
        self._closing = True
        self._dwell.stop()
        self._disconnect_browser()
        av_player.stop_and_clear_queue()
        if mw.pm.profile is not None:
            saveGeom(self, GEOM_KEY)
        self.web.cleanup()
        if self in self.ctx.windows:
            self.ctx.windows.remove(self)


def open_drill_window(
    ctx: AddonContext, ctrl: DrillController, store: SessionStore, parent: QWidget | None = None
) -> DrillWindow:
    del parent  # top-level: Anki stays usable beside it
    w = DrillWindow(ctx, ctrl, store)
    w.start()
    return w
