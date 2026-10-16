"""Tools → "Recall Drill: tuning report": renders ``tuning.build_report``.

Reads the history and the revlog off the main thread (``QueryOp``), then shows
the header, the comparison table, the breakdowns and the suggestions. A deck
filter re-builds the report from the same inputs.

Nothing changes by itself. A suggestion's **Apply…** asks first, showing old →
new and the evidence; on Yes it writes the add-on's global default
(``config.json``, through ``addonManager.writeConfig``) and a
``type: "tuning"`` history line. **Copy as CSV** puts the per-card outcome
table on the clipboard.
"""

from __future__ import annotations

import html
from typing import Any

from aqt import mw
from aqt.operations import QueryOp
from aqt.qt import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    Qt,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
    qconnect,
)
from aqt.utils import disable_help_button, restoreGeom, saveGeom, showWarning, tooltip

from .. import history_store, launch
from ..anki_io.revlog import ReportInputs, encode_reps_overrides, read_report_inputs
from ..tuning import (
    CONFOUND_WARNING,
    Report,
    ReportSettings,
    Suggestion,
    build_report,
    confirmation_text,
    header_lines,
    render_html,
    to_csv,
    tuning_line,
)
from . import style
from .context import AddonContext
from .widgets import ComboBox

GEOM_KEY = "recalldrill_tuning"
ALL_DECKS = "All decks"


def report_settings(ctx: AddonContext) -> ReportSettings:
    cfg = ctx.config()
    return ReportSettings(
        min_n=cfg.min_n, min_words_to_chunk=cfg.min_words_to_chunk, encode_reps=cfg.encode_reps
    )


def ask_apply(parent: QWidget, text: str) -> bool:
    """The Apply confirmation (tests replace this)."""
    answer = QMessageBox.question(
        parent,
        "Recall Drill: apply suggestion",
        text,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        QMessageBox.StandardButton.Cancel,
    )
    return answer == QMessageBox.StandardButton.Yes


def _table_style(markup: str) -> str:
    """The report's tables without the grid: Qt draws ``border="1"`` as lines on every cell."""
    return markup.replace(
        '<table border="1" cellspacing="0" cellpadding="4">',
        '<table border="0" cellspacing="0" cellpadding="6" width="100%">',
    )


def apply_suggestion(ctx: AddonContext, s: Suggestion, deck_filter: str | None) -> None:
    """Writes the new global default and logs it. Only after a confirmation."""
    conf: dict[str, Any] = dict(mw.addonManager.getConfig(ctx.module) or {})
    conf[s.parameter] = s.proposed
    mw.addonManager.writeConfig(ctx.module, conf)
    history_store.append_tuning(ctx.storage(), tuning_line(s, launch.now_ms(), deck_filter))


class TuningDialog(QDialog):
    def __init__(self, ctx: AddonContext) -> None:
        super().__init__(None, Qt.WindowType.Window)
        self.ctx = ctx
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        disable_help_button(self)
        self.setWindowTitle("Recall Drill: tuning report")
        self.inputs: ReportInputs | None = None
        self.report: Report | None = None
        self._closed = False

        root = style.install(self)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(20, 16, 20, 14)
        layout.setSpacing(12)
        row = QHBoxLayout()
        row.addWidget(style.text_label("Tuning report", "title", wrap=False), 1)
        row.addWidget(style.text_label("Deck", "muted", wrap=False))
        self.deck = ComboBox()
        self.deck.addItem(ALL_DECKS, None)
        self.deck.setMinimumWidth(220)
        qconnect(self.deck.currentIndexChanged, self._render)
        row.addWidget(self.deck)
        layout.addLayout(row)
        # The top facts as three tiles, then the caution as an info note.
        tiles = QHBoxLayout()
        tiles.setSpacing(10)
        self.tile_sessions, self.sessions_value = style.tile("sessions")
        self.tile_rated, self.rated_value = style.tile("drilled cards rated")
        self.tile_waiting, self.waiting_value = style.tile("still waiting")
        for t in (self.tile_sessions, self.tile_rated, self.tile_waiting):
            tiles.addWidget(t, 1)
        layout.addLayout(tiles)
        self.facts = style.text_label(kind="muted")
        layout.addWidget(self.facts)
        self.caution = style.note(CONFOUND_WARNING, "info")
        layout.addWidget(self.caution)
        self.body = QTextBrowser()
        self.body.setOpenExternalLinks(False)
        self.body.setHtml("Reading the history and the review log…")
        layout.addWidget(self.body, 3)
        sug_box = QWidget()
        sb = QVBoxLayout(sug_box)
        sb.setContentsMargins(0, 0, 0, 0)
        sb.setSpacing(6)
        sb.addWidget(style.section_label("Suggestions"))
        sb.addWidget(style.text_label("Nothing changes unless you apply one.", "muted"))
        self.suggestions = QVBoxLayout()  # one card per suggestion
        self.suggestions.setSpacing(8)
        sb.addLayout(self.suggestions)
        layout.addWidget(sug_box, 1)
        bottom = QHBoxLayout()
        self.csv_btn = style.button("Copy as CSV")
        self.csv_btn.setEnabled(False)
        qconnect(self.csv_btn.clicked, self._copy_csv)
        close = style.button("Close", "ghost")
        qconnect(close.clicked, self.close)
        bottom.addWidget(self.csv_btn)
        bottom.addStretch(1)
        bottom.addWidget(close)
        layout.addLayout(bottom)
        style.apply(self, self._restyle)
        self._set_report_css()
        restoreGeom(self, GEOM_KEY, default_size=(860, 900))
        ctx.dialogs.append(self)
        self._load()

    def _set_report_css(self) -> None:
        doc = self.body.document()
        if doc is not None:
            doc.setDefaultStyleSheet(style.report_css(style.is_night()))

    def _restyle(self) -> None:
        """Anki's theme changed: the tables take their colours from a sheet, so reload them."""
        self._set_report_css()
        if self.report is not None:
            self._render()

    def _load(self) -> None:
        storage = self.ctx.storage()

        def op(col: Any) -> ReportInputs:
            return read_report_inputs(col, storage)

        def done(inputs: ReportInputs) -> None:
            if self._closed:
                return
            self.inputs = inputs
            self._render()

        def failed(exc: Exception) -> None:
            if not self._closed:
                showWarning(f"Recall Drill couldn't build the report: {exc}", parent=self)

        QueryOp(parent=self, op=op, success=done).failure(failed).run_in_background()

    def _render(self, *_args: Any) -> None:
        if self.inputs is None:
            return
        deck_filter = self.deck.currentData()
        i = self.inputs
        report = build_report(
            i.lines,
            i.revlog,
            deck_filter if isinstance(deck_filter, str) else None,
            cards=i.cards,
            rollover=i.rollover,
            settings=report_settings(self.ctx),
        )
        self.report = report
        self._fill_decks(report.decks)
        _cards, outcomes, _late, pending = report.counts("drilled")
        self.sessions_value.setText(str(report.sessions))
        self.rated_value.setText(str(outcomes))
        self.waiting_value.setText(str(pending))
        self.facts.setText("\n".join(header_lines(report)[1:]))
        self.body.setHtml(_table_style(render_html(report, facts=False)))
        self.csv_btn.setEnabled(bool(report.rows))
        self._show_suggestions(report)

    def _fill_decks(self, decks: list[str]) -> None:
        have = [self.deck.itemData(i) for i in range(1, self.deck.count())]
        if have == decks:
            return
        current = self.deck.currentData()
        self.deck.blockSignals(True)
        try:
            self.deck.clear()
            self.deck.addItem(ALL_DECKS, None)
            for d in decks:
                self.deck.addItem(d, d)
            idx = self.deck.findData(current) if current is not None else 0
            self.deck.setCurrentIndex(max(0, idx))
        finally:
            self.deck.blockSignals(False)

    def _show_suggestions(self, report: Report) -> None:
        while self.suggestions.count():
            item = self.suggestions.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                w.deleteLater()
        if not report.suggestions:
            self.suggestions.addWidget(style.text_label("No suggestions yet.", "muted"))
        for s in report.suggestions:
            card, cl = style.card_frame()
            rl = QHBoxLayout()
            cl.addLayout(rl)
            lines = [f"<b>{html.escape(s.label)}</b> (now {s.current}): {html.escape(s.verdict)}"]
            lines += [f"&nbsp;&nbsp;{html.escape(e)}" for e in s.evidence]
            if s.caveat:
                lines.append(f"<i>{html.escape(s.caveat)}</i>")
            text = QLabel("<br>".join(lines))
            text.setWordWrap(True)
            text.setTextFormat(Qt.TextFormat.RichText)
            rl.addWidget(text, 1)
            if s.actionable:
                btn = style.button(f"Apply {s.current} → {s.proposed}…", "primary")
                qconnect(btn.clicked, lambda _=False, sug=s: self._apply(sug))
                rl.addWidget(btn, 0, Qt.AlignmentFlag.AlignTop)
            self.suggestions.addWidget(card)

    def _apply(self, s: Suggestion) -> None:
        report = self.report
        if report is None or not s.actionable or s.proposed is None:
            return
        overrides: list[str] = []
        if s.parameter == "encode_reps" and mw.col is not None:
            overrides = encode_reps_overrides(mw.col, self.ctx.storage(), s.proposed)
        if not ask_apply(self, confirmation_text(s, report.deck_filter, overrides)):
            return
        try:
            apply_suggestion(self.ctx, s, report.deck_filter)
        except OSError as exc:
            showWarning(f"Recall Drill couldn't save the change: {exc}", parent=self)
            return
        tooltip(f"{s.label} is now {s.proposed} for new sessions.", parent=self)
        self._render()

    def _copy_csv(self) -> None:
        if self.report is None:
            return
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(to_csv(self.report))
            tooltip(f"Copied {len(self.report.rows)} rows as CSV.", parent=self)

    def closeEvent(self, a0: Any) -> None:  # noqa: N802 (Qt override)
        self._closed = True
        if mw.pm.profile is not None:
            saveGeom(self, GEOM_KEY)
        if self in self.ctx.dialogs:
            self.ctx.dialogs.remove(self)
        if a0 is not None:
            a0.accept()


def open_tuning_report(ctx: AddonContext) -> TuningDialog:
    dialog = TuningDialog(ctx)
    dialog.show()
    dialog.activateWindow()
    return dialog
