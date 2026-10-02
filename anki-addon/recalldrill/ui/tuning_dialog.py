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
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
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
    Report,
    ReportSettings,
    Suggestion,
    build_report,
    confirmation_text,
    render_html,
    to_csv,
    tuning_line,
)
from .context import AddonContext

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

        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel("Deck"))
        self.deck = QComboBox()
        self.deck.addItem(ALL_DECKS, None)
        qconnect(self.deck.currentIndexChanged, self._render)
        row.addWidget(self.deck, 1)
        layout.addLayout(row)
        self.body = QTextBrowser()
        self.body.setOpenExternalLinks(False)
        self.body.setHtml("Reading the history and the review log…")
        layout.addWidget(self.body, 3)
        self.suggestions = QVBoxLayout()
        box = QFrame()
        box.setFrameShape(QFrame.Shape.StyledPanel)
        box.setLayout(self.suggestions)
        layout.addWidget(box, 1)
        bottom = QHBoxLayout()
        self.csv_btn = QPushButton("Copy as CSV")
        self.csv_btn.setEnabled(False)
        qconnect(self.csv_btn.clicked, self._copy_csv)
        close = QPushButton("Close")
        qconnect(close.clicked, self.close)
        bottom.addWidget(self.csv_btn)
        bottom.addStretch(1)
        bottom.addWidget(close)
        layout.addLayout(bottom)
        restoreGeom(self, GEOM_KEY, default_size=(820, 860))
        ctx.dialogs.append(self)
        self._load()

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
        self.body.setHtml(render_html(report))
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
        title = QLabel("<b>Suggestions</b> (nothing changes unless you apply one)")
        self.suggestions.addWidget(title)
        for s in report.suggestions:
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            lines = [f"<b>{html.escape(s.label)}</b> (now {s.current}): {html.escape(s.verdict)}"]
            lines += [f"&nbsp;&nbsp;{html.escape(e)}" for e in s.evidence]
            if s.caveat:
                lines.append(f"<i>{html.escape(s.caveat)}</i>")
            text = QLabel("<br>".join(lines))
            text.setWordWrap(True)
            text.setTextFormat(Qt.TextFormat.RichText)
            rl.addWidget(text, 1)
            if s.actionable:
                btn = QPushButton(f"Apply {s.current} → {s.proposed}…")
                qconnect(btn.clicked, lambda _=False, sug=s: self._apply(sug))
                rl.addWidget(btn, 0, Qt.AlignmentFlag.AlignTop)
            self.suggestions.addWidget(row)

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
