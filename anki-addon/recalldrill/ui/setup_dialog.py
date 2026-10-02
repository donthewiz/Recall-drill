"""The setup panel: what to drill, the deck's settings, the estimate, Start.

Reads with ``anki_io.panel`` off the main thread (``QueryOp``), shows the
result, and starts or resumes through ``launch``. Saves only:

- the deck's settings, on Start or Save (``deck_settings.json``);
- a manual hint, when one is edited (``hints.json``);
- a mapping, from "Edit mapping…" (``mappings.json``).

The pending banner's **Hand off finished session** runs the handoff
(``handoff_dialog``); nothing else here writes to the collection.

The ``tag:rd::hard`` search ("Recall Drill: my rd::hard cards") leaves out, by
default, the cards whose last handoff found them not hard: the tag is on the
note, so a hard card's siblings (and cloze siblings) carry it too.

With the holdout on (the deck's **Holdout %**, saved with its settings; the
config's ``holdout_pct`` is the default, 0 = off), a deck scope sets some
eligible new cards aside as the measurement control; the panel says how many,
updated as the % changes. Cards tagged ``rd::holdout`` are left out unless
``holdout_exclude`` is off.

**Difficulty** (Phase 6): the card section says how many cards get one more
or one fewer rep, or chunk earlier, from their FSRS difficulty (new cards have
no FSRS data and are unchanged), and how many ``stable`` cards are skipped.
The deck's "Adjust reps by difficulty" toggle is saved with its settings.
"""

from __future__ import annotations

from typing import Any, cast

from anki.decks import DeckId
from aqt import mw
from aqt.operations import QueryOp
from aqt.qt import (
    QCheckBox,
    QCloseEvent,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    Qt,
    QTableWidget,
    QTableWidgetItem,
    QTimer,
    QVBoxLayout,
    QWidget,
    qconnect,
)
from aqt.utils import disable_help_button, restoreGeom, saveGeom, tooltip

from .. import deck_settings, holdout, launch, sessions
from ..anki_io.cards import CARD_CLASSES, DEFAULT_ENABLED, CardClass
from ..anki_io.panel import (
    PanelData,
    SavedInfo,
    hard_exclusions,
    initial_settings,
    options_for,
    read_panel,
    read_saved,
    save_hint,
    scope_key,
    scope_label,
    settings_deck,
)
from ..anki_io.select import INELIGIBLE_REASONS, OrderMode, Scope, scope_to_json
from ..deck_settings import DeckSettings
from ..engine.estimate import ExposureLevel
from .context import AddonContext
from .drill_window import HANDOFF_TOOLTIP, open_drill_window
from .handoff_dialog import offer_handoff
from .mapping_dialog import MappingDialog

GEOM_KEY = "recalldrill_setup"
REFRESH_MS = 300

_REASON_LABELS = {
    "image_occlusion": "image occlusion",
    "marked_ineligible": "marked ineligible",
    "unmapped": "no answer field",
    "empty_answer": "empty answer",
    "filtered_deck": "in a filtered deck",
    "buried": "buried",
}
_EXPOSURE: list[tuple[ExposureLevel, str]] = [
    ("fresh", "First time seeing this material"),
    ("once", "Studied it once or twice"),
    ("familiar", "Reviewed it several times"),
]


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def stable_text(skipped: int, min_stability: float, max_difficulty: float) -> str:
    """The card section's ``stable`` line ("" when none is skipped)."""
    if skipped <= 0:
        return ""
    return (
        f"Stable: {_plural(skipped, 'card')} skipped (FSRS stability ≥ {min_stability:g} days, "
        f"difficulty ≤ {max_difficulty:g}). Tick “stable” to drill "
        f"{'it' if skipped == 1 else 'them'}."
    )


def holdout_text(held: int, pct: int = 1) -> str:
    """The card section's holdout line. ``pct`` 0: off."""
    if pct <= 0:
        return "Holdout: off"
    if held == 1:
        return (
            "Holdout: 1 card skips the drill and goes to Anki as a new card (measurement control)."
        )
    return (
        f"Holdout: {held} cards skip the drill and go to Anki as new cards (measurement control)."
    )


class SetupDialog(QDialog):
    def __init__(self, ctx: AddonContext, deck_id: int | None, search: str | None = None) -> None:
        super().__init__(None, Qt.WindowType.Window)
        self.ctx = ctx
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        disable_help_button(self)
        self.deck_id = deck_id
        self.scope = Scope(search=search) if search else Scope(deck_id=deck_id)
        self.draft: DeckSettings = {}
        self.settings_did: int | None = None
        self.enabled: set[CardClass] = set(DEFAULT_ENABLED)
        self.exposure: ExposureLevel = "fresh"
        self.data: PanelData | None = None
        self.saved_info: SavedInfo | None = None
        self._generation = 0
        self._closed = False
        self._updating = False
        self._loading = False
        self._template_boxes: dict[int, list[tuple[int, QCheckBox]]] = {}
        self.hard_exclude: frozenset[int] = frozenset()
        """For the ``tag:rd::hard`` scope: cards not hard in their last handoff."""

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        qconnect(self._timer.timeout, self._refresh)

        self._build_ui()
        restoreGeom(self, GEOM_KEY, default_size=(760, 860))
        ctx.dialogs.append(self)
        self._load_scope()

    # -- layout -------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        self.body = QVBoxLayout(body)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        # Scope
        scope_box = QGroupBox("Scope")
        sl = QVBoxLayout(scope_box)
        self.scope_label = QLabel()
        self.scope_label.setWordWrap(True)
        sl.addWidget(self.scope_label)
        row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(
            "Search… e.g. tag:MedTerm_Ch03::Day05 (whole collection)"
        )
        self.search_btn = QPushButton("Use search")
        self.deck_btn = QPushButton("Use this deck")
        for b in (self.search_btn, self.deck_btn):
            b.setAutoDefault(False)
        row.addWidget(self.search_edit, 1)
        row.addWidget(self.search_btn)
        row.addWidget(self.deck_btn)
        sl.addLayout(row)
        qconnect(self.search_edit.returnPressed, self._use_search)
        qconnect(self.search_btn.clicked, self._use_search)
        qconnect(self.deck_btn.clicked, self._use_deck)
        self.body.addWidget(scope_box)

        # Saved-session banner
        self.banner = QFrame()
        self.banner.setFrameShape(QFrame.Shape.StyledPanel)
        bl = QVBoxLayout(self.banner)
        self.banner_text = QLabel()
        self.banner_text.setWordWrap(True)
        bl.addWidget(self.banner_text)
        brow = QHBoxLayout()
        self.resume_btn = QPushButton("Resume")
        self.resume_saved_btn = QPushButton("Resume with saved text")
        self.fresh_btn = QPushButton("Start fresh")
        self.handoff_btn = QPushButton("Hand off finished session")
        self.handoff_btn.setToolTip(HANDOFF_TOOLTIP)
        self.discard_btn = QPushButton("Don't hand off")
        for b, fn in (
            (self.resume_btn, self._resume),
            (self.resume_saved_btn, self._resume),
            (self.fresh_btn, self._start_fresh),
            (self.handoff_btn, self._handoff),
            (self.discard_btn, self._discard_saved),
        ):
            b.setAutoDefault(False)
            qconnect(b.clicked, fn)
        for b in (
            self.resume_btn,
            self.fresh_btn,
            self.resume_saved_btn,
            self.handoff_btn,
            self.discard_btn,
        ):
            brow.addWidget(b)
        brow.addStretch(1)
        bl.addLayout(brow)
        self.banner.hide()
        self.body.addWidget(self.banner)

        # Cards
        cards = QGroupBox("Cards")
        cl = QVBoxLayout(cards)
        grid = QGridLayout()
        self.class_boxes: dict[CardClass, QCheckBox] = {}
        for i, c in enumerate(CARD_CLASSES):
            box = QCheckBox(c)
            box.setChecked(c in self.enabled)
            qconnect(box.toggled, self._on_class_toggled)
            self.class_boxes[c] = box
            grid.addWidget(box, i // 3, i % 3)
        cl.addLayout(grid)
        self.hard_only = QCheckBox("Only the cards that were hard in their last handoff")
        self.hard_only.setChecked(True)
        self.hard_only.setToolTip(
            "rd::hard is a note tag, so a hard card's siblings carry it too. "
            "Untick to drill every card of the tagged notes."
        )
        self.hard_only.hide()
        qconnect(self.hard_only.toggled, self._schedule)
        cl.addWidget(self.hard_only)
        form = QFormLayout()
        self.max_cards = QSpinBox()
        self.max_cards.setRange(0, 100_000)
        self.max_cards.setSpecialValueText("all")
        self.tag_edit = QLineEdit()
        self.tag_edit.setPlaceholderText("optional, an exact tag (e.g. rd::drill::A1)")
        self.order = QComboBox()
        self.order.addItem("Priority first", "priority_first")
        self.order.addItem("Deck order", "deck_order")
        form.addRow("Max cards", self.max_cards)
        form.addRow("Only with tag", self.tag_edit)
        form.addRow("Order", self.order)
        cl.addLayout(form)
        qconnect(self.max_cards.valueChanged, self._schedule)
        qconnect(self.tag_edit.textChanged, self._schedule)
        qconnect(self.order.currentIndexChanged, self._schedule)
        self.templates_box = QGroupBox("Templates")
        self.templates_layout = QVBoxLayout(self.templates_box)
        cl.addWidget(self.templates_box)
        self.sibling_label = QLabel()
        self.sibling_label.setWordWrap(True)
        cl.addWidget(self.sibling_label)
        self.difficulty_label = QLabel()
        self.difficulty_label.setWordWrap(True)
        cl.addWidget(self.difficulty_label)
        srow = QHBoxLayout()
        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        self.holdout_row = QWidget()
        hrow = QHBoxLayout(self.holdout_row)
        hrow.setContentsMargins(0, 0, 0, 0)
        self.holdout_label = QLabel()
        self.holdout_label.setWordWrap(True)
        self.holdout_pct = QSpinBox()
        self.holdout_pct.setRange(0, deck_settings.HOLDOUT_MAX_PCT)
        self.holdout_pct.setSuffix(" %")
        self.holdout_pct.setToolTip(
            "Share of eligible new cards that skip the drill and go to Anki as plain new "
            "cards, as a fair comparison (tuning report). Saved for this deck. "
            "Which cards is fixed by a hash: changing it only changes who is held out "
            "from now on; cards already handed off as rd::holdout stay out."
        )
        qconnect(self.holdout_pct.valueChanged, self._on_setting)
        hrow.addWidget(self.holdout_label, 1)
        hrow.addWidget(QLabel("Holdout %"))
        hrow.addWidget(self.holdout_pct)
        self.holdout_row.hide()
        cl.addWidget(self.holdout_row)
        self.mapping_btn = QPushButton("Edit mapping…")
        self.mapping_btn.setAutoDefault(False)
        qconnect(self.mapping_btn.clicked, self._edit_mapping)
        srow.addWidget(self.summary_label, 1)
        srow.addWidget(self.mapping_btn)
        cl.addLayout(srow)
        self.body.addWidget(cards)

        # Settings
        settings = QGroupBox("Settings for this deck")
        stl = QVBoxLayout(settings)
        prow = QHBoxLayout()
        self.proposal_label = QLabel(
            "Most answers here are 3 words or fewer: terminology settings fit "
            "(strict punctuation on, word-ending tolerance off, hints on)."
        )
        self.proposal_label.setWordWrap(True)
        self.proposal_btn = QPushButton("Use terminology settings")
        self.proposal_btn.setAutoDefault(False)
        qconnect(self.proposal_btn.clicked, self._use_proposal)
        prow.addWidget(self.proposal_label, 1)
        prow.addWidget(self.proposal_btn)
        self.proposal_row = QWidget()
        self.proposal_row.setLayout(prow)
        stl.addWidget(self.proposal_row)
        sform = QFormLayout()
        self.batch_size = QSpinBox()
        self.batch_size.setRange(0, 50)
        self.batch_size.setSpecialValueText("Whole deck")
        self.encode_reps = QSpinBox()
        self.encode_reps.setRange(1, 10)
        self.cycle_order = QComboBox()
        self.cycle_order.addItem("Shuffled", "shuffled")
        self.cycle_order.addItem("In order", "inOrder")
        self.strict = QCheckBox("Punctuation must match (strict)")
        self.stem = QCheckBox("Forgive minor word endings (e.g. plurals)")
        self.hints = QCheckBox("Disambiguation hints on prompts")
        self.difficulty_adjust = QCheckBox(
            "Adjust reps by difficulty (cards with review history only)"
        )
        self.difficulty_adjust.setToolTip(
            "Cards Anki finds hard (FSRS difficulty ≥ 7, or many lapses without FSRS) get "
            "one more blind typing and chunk earlier; easy ones (difficulty ≤ 3) one fewer. "
            "New cards have no FSRS data and keep the deck's settings."
        )
        sform.addRow("Cards per batch", self.batch_size)
        sform.addRow("Blind typings required", self.encode_reps)
        sform.addRow("Cycle review order", self.cycle_order)
        sform.addRow("", self.strict)
        sform.addRow("", self.stem)
        sform.addRow("", self.hints)
        sform.addRow("", self.difficulty_adjust)
        stl.addLayout(sform)
        self.settings_note = QLabel()
        self.settings_note.setWordWrap(True)
        stl.addWidget(self.settings_note)
        self.save_settings_btn = QPushButton("Save settings")
        self.save_settings_btn.setAutoDefault(False)
        qconnect(self.save_settings_btn.clicked, self._save_settings)
        stl.addWidget(self.save_settings_btn, 0, Qt.AlignmentFlag.AlignRight)
        qconnect(self.batch_size.valueChanged, self._on_setting)
        qconnect(self.encode_reps.valueChanged, self._on_setting)
        qconnect(self.cycle_order.currentIndexChanged, self._on_setting)
        qconnect(self.strict.toggled, self._on_setting)
        qconnect(self.stem.toggled, self._on_setting)
        qconnect(self.hints.toggled, self._on_setting)
        qconnect(self.difficulty_adjust.toggled, self._on_setting)
        self.body.addWidget(settings)

        # Hints
        self.hints_box = QGroupBox("Hints")
        hl = QVBoxLayout(self.hints_box)
        hl.addWidget(
            QLabel(
                "Prompts another card shares, which no automatic hint can tell apart. "
                "Type a hint to show after the prompt; empty the cell to remove yours."
            )
        )
        self.hints_table = QTableWidget(0, 4)
        self.hints_table.setHorizontalHeaderLabels(["Prompt", "Answer", "Conflicts with", "Hint"])
        header = self.hints_table.horizontalHeader()
        if header is not None:
            header.setStretchLastSection(True)
        qconnect(self.hints_table.itemChanged, self._on_hint_edited)
        hl.addWidget(self.hints_table)
        self.body.addWidget(self.hints_box)

        # Estimate
        est = QGroupBox("Estimate")
        el = QFormLayout(est)
        self.estimate_label = QLabel()
        self.exposure_combo = QComboBox()
        for level, label in _EXPOSURE:
            self.exposure_combo.addItem(label, level)
        qconnect(self.exposure_combo.currentIndexChanged, self._on_exposure)
        self.exposure_row_label = QLabel("How familiar are you with this material?")
        el.addRow("Estimated time", self.estimate_label)
        el.addRow(self.exposure_row_label, self.exposure_combo)
        self.body.addWidget(est)
        self.body.addStretch(1)

        # Bottom
        bottom = QHBoxLayout()
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.start_btn = QPushButton("Start")
        self.start_btn.setDefault(True)
        close = QPushButton("Close")
        close.setAutoDefault(False)
        qconnect(self.start_btn.clicked, self._start)
        qconnect(close.clicked, self.close)
        bottom.addWidget(self.status_label, 1)
        bottom.addWidget(self.start_btn)
        bottom.addWidget(close)
        outer.addLayout(bottom)

    # -- scope --------------------------------------------------------------

    def _use_search(self) -> None:
        text = self.search_edit.text().strip()
        if not text:
            return
        self.scope = Scope(search=text)
        self._load_scope()

    def _use_deck(self) -> None:
        if self.deck_id is None:
            return
        self.scope = Scope(deck_id=self.deck_id)
        self.search_edit.clear()
        self._load_scope()

    def _load_scope(self) -> None:
        """A new scope: its settings deck, the saved draft and the saved session."""
        self._set_loading(True)
        self.banner.hide()
        scope = self.scope
        storage = self.ctx.storage()
        self.deck_btn.setEnabled(self.deck_id is not None and scope.deck_id is None)

        def op(
            col: Any,
        ) -> tuple[str, int | None, DeckSettings, SavedInfo | None, frozenset[int]]:
            did = settings_deck(col, storage, scope)
            return (
                scope_label(col, scope),
                did,
                initial_settings(storage, did),
                read_saved(col, storage, scope_key(scope)),
                hard_exclusions(storage, scope),
            )

        def done(
            result: tuple[str, int | None, DeckSettings, SavedInfo | None, frozenset[int]],
        ) -> None:
            if self._closed or scope != self.scope:
                return
            label, did, draft, saved, exclude = result
            self.settings_did = did
            self.draft = draft
            self.hard_exclude = exclude
            self.hard_only.setVisible(bool(exclude))
            what = "Deck" if scope.deck_id is not None else "Search"
            self.scope_label.setText(f"<b>{what}:</b> {label}")
            self.setWindowTitle(f"Recall Drill: {label}")
            self._show_saved(saved)
            self._refresh()

        QueryOp(parent=self, op=op, success=done).failure(self._failed).run_in_background()

    def _failed(self, exc: Exception) -> None:
        if self._closed:
            return
        self._set_loading(False)
        self.status_label.setText(f"Couldn't read the cards: {exc}")
        self.start_btn.setEnabled(False)

    # -- refresh --------------------------------------------------------------

    def _schedule(self, *_args: Any) -> None:
        if self._updating:
            return
        self._timer.start(REFRESH_MS)

    def _options(self) -> Any:
        tag = self.tag_edit.text().strip()
        cfg = self.ctx.config()
        # Deck scopes only (select.holdout_spec): a search never holds cards out.
        pct = launch.resolved(self.draft, cfg)["holdoutPct"] if self.scope.deck_id else 0
        return options_for(
            self.draft,
            enabled=frozenset(self.enabled),
            max_cards=self.max_cards.value() or None,
            extra_tag=tag or None,
            order=cast(OrderMode, self.order.currentData()),
            exclude_cids=self.hard_exclude if self.hard_only.isChecked() else frozenset(),
            holdout_pct=pct,
            holdout_salt=holdout.salt_for(self.ctx.storage(), pct),
            exclude_holdout_tag=cfg.holdout_exclude,
            skip_min_stability=cfg.skip_min_stability,
            skip_max_difficulty=cfg.skip_max_difficulty,
        )

    def _refresh(self) -> None:
        self._generation += 1
        gen = self._generation
        self._set_loading(True)
        storage = self.ctx.storage()
        cfg = self.ctx.config()
        scope, options, draft = self.scope, self._options(), dict(self.draft)
        did, exposure = self.settings_did, self.exposure

        def op(col: Any) -> PanelData:
            return read_panel(
                col, storage, scope, options, cast(DeckSettings, draft), did, cfg, exposure
            )

        def done(data: PanelData) -> None:
            if self._closed or gen != self._generation:
                return
            self.data = data
            self._show(data)
            self._set_loading(False)

        QueryOp(parent=self, op=op, success=done).failure(self._failed).run_in_background()

    def _set_loading(self, loading: bool) -> None:
        self._loading = loading
        if loading:
            self.status_label.setText("Reading cards…")
            self.start_btn.setEnabled(False)

    # -- showing ----------------------------------------------------------------

    def _show(self, data: PanelData) -> None:
        self._updating = True
        try:
            self._show_cards(data)
            self._show_settings(data)
            self._show_hints(data)
            self._show_estimate(data)
            self._show_start(data)
        finally:
            self._updating = False

    def _show_cards(self, data: PanelData) -> None:
        sel = data.selection
        for c, box in self.class_boxes.items():
            box.setText(f"{c.replace('_', ' ')} ({sel.eligible_counts[c]})")
        # Template filter: note types with more than one template.
        multi = [nt for nt in data.note_types if nt.kind == "standard" and len(nt.templates) > 1]
        if set(self._template_boxes) != {nt.ntid for nt in multi}:
            while self.templates_layout.count():
                item = self.templates_layout.takeAt(0)
                w = item.widget() if item is not None else None
                if w is not None:
                    w.deleteLater()
            self._template_boxes = {}
            for nt in multi:
                row = QWidget()
                rl = QHBoxLayout(row)
                rl.setContentsMargins(0, 0, 0, 0)
                rl.addWidget(QLabel(nt.name))
                boxes: list[tuple[int, QCheckBox]] = []
                for ord_, name in nt.templates:
                    box = QCheckBox(name)
                    qconnect(box.toggled, self._on_template_toggled)
                    rl.addWidget(box)
                    boxes.append((ord_, box))
                rl.addStretch(1)
                self._template_boxes[nt.ntid] = boxes
                self.templates_layout.addWidget(row)
        ords = self.draft.get("card_ords", {})
        for ntid, boxes in self._template_boxes.items():
            allowed = ords.get(str(ntid))
            for ord_, box in boxes:
                box.setChecked(allowed is None or ord_ in allowed)
        self.templates_box.setVisible(bool(multi))
        if sel.sibling_cards:
            self.sibling_label.setText(
                f"⚠ Siblings: {sel.sibling_cards} picked cards share a note with another "
                f"picked card ({_plural(sel.sibling_notes, 'note')}). Drilling both directions "
                "at once lets one card give the other away."
            )
        else:
            self.sibling_label.setText("Siblings: 0 picked cards share a note.")

        b = data.build
        lines = [
            f"{_plural(sel.total, 'card')} in scope; {len(sel.picked)} picked; "
            f"<b>{len(b.deck_items)} drillable</b>."
        ]
        reasons = [
            f"{_REASON_LABELS[r]} {sel.ineligible[r]}"
            for r in INELIGIBLE_REASONS
            if sel.ineligible[r]
        ]
        if b.empty_answers:
            reasons.append(f"empty answer at build {b.empty_answers}")
        if reasons:
            lines.append(f"Ineligible ({data.ineligible_total}): " + ", ".join(reasons) + ".")
        if sel.template_excluded:
            lines.append(f"{sel.template_excluded} left out by the template filter.")
        if sel.excluded:
            lines.append(
                f"{_plural(sel.excluded, 'card')} left out: not hard in "
                f"{'its' if sel.excluded == 1 else 'their'} last handoff."
            )
        if sel.holdout_tagged:
            lines.append(
                f"{_plural(sel.holdout_tagged, 'card')} tagged rd::holdout left out "
                "(earlier measurement controls)."
            )
        self.holdout_row.setVisible(data.scope.deck_id is not None)
        self.holdout_label.setText(holdout_text(len(sel.holdout), sel.options.holdout_pct))
        diff_lines = [data.difficulty.text()] if data.difficulty is not None else []
        cfg = self.ctx.config()
        stable = stable_text(data.stable_skipped, cfg.skip_min_stability, cfg.skip_max_difficulty)
        if stable:
            diff_lines.append(stable)
        self.difficulty_label.setText("<br>".join(diff_lines))
        self.difficulty_label.setVisible(bool(diff_lines))
        image_fronts = sum(1 for s in b.sources if s.image_front)
        if image_fronts:
            lines.append(f"{image_fronts} show an image on the front (no hints for them).")
        self.summary_label.setText("<br>".join(lines))
        self.mapping_btn.setEnabled(bool(sel.mappings))

    def _show_settings(self, data: PanelData) -> None:
        r = launch.resolved(self.draft, self.ctx.config())
        self.batch_size.setValue(r["batchSize"])
        self.encode_reps.setValue(r["encodeReps"])
        self.cycle_order.setCurrentIndex(0 if r["cycleOrder"] == "shuffled" else 1)
        self.strict.setChecked(r["strictPunctuation"])
        self.stem.setChecked(r["stemTolerance"])
        self.stem.setEnabled(not r["strictPunctuation"])
        self.hints.setChecked(data.build.hints_on)
        self.holdout_pct.setValue(r["holdoutPct"])
        self.difficulty_adjust.setChecked(r["difficultyAdjust"])
        proposal = data.proposal
        self.proposal_row.setVisible(
            proposal is not None and any(self.draft.get(k) != v for k, v in proposal.items())
        )
        if data.settings_did is None:
            note = "No deck holds these cards: settings can't be saved."
        elif data.saved_settings is not None:
            note = "Saved settings for this deck."
        else:
            note = "Nothing saved for this deck yet: saved when you press Start or Save."
        if data.scope.deck_id is None and data.settings_did is not None:
            name = mw.col.decks.name(DeckId(data.settings_did)) if mw.col is not None else ""
            note += f" (Settings deck: {name}, the deck holding most of these cards.)"
        self.settings_note.setText(note)
        self.save_settings_btn.setEnabled(data.settings_did is not None)

    def _show_hints(self, data: PanelData) -> None:
        rows = data.hint_rows
        self.hints_box.setVisible(bool(rows))
        self.hints_table.setRowCount(len(rows))
        for i, h in enumerate(rows):
            cells = [h.prompt, h.term, ", ".join(h.conflicts), h.hint or ""]
            for j, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if j < 3:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                else:
                    item.setData(Qt.ItemDataRole.UserRole, h.key)
                self.hints_table.setItem(i, j, item)
        self.hints_table.resizeColumnsToContents()

    def _show_estimate(self, data: PanelData) -> None:
        self.estimate_label.setText(data.estimate_text() or "—")
        if data.personal_history:
            self.exposure_row_label.setText("Based on your last session with these cards.")
            self.exposure_combo.hide()
        else:
            self.exposure_row_label.setText("How familiar are you with this material?")
            self.exposure_combo.show()

    def _show_start(self, data: PanelData) -> None:
        n = data.drillable
        if n == 0:
            self.status_label.setText(
                f"Nothing eligible: {data.ineligible_total} ineligible, see reasons above."
                if data.ineligible_total
                else "Nothing to drill: no picked cards (check the classes, tag and search)."
            )
            self.start_btn.setEnabled(False)
            return
        self.status_label.setText(f"{_plural(n, 'card')} to drill.")
        self.start_btn.setEnabled(True)

    def _show_saved(self, saved: SavedInfo | None) -> None:
        self.saved_info = saved
        if saved is None:
            self.banner.hide()
            return
        resume = saved.status == "resume"
        problems = saved.check is not None and not saved.check.ok
        if not resume:
            text = (
                f"<b>A finished session is waiting for its handoff</b> "
                f"({_plural(saved.total, 'card')})."
            )
        else:
            text = f"<b>Saved session:</b> {saved.mastered} of {saved.total} mastered."
            if problems:
                lines = [f"Missing: {m}" for m in saved.missing] + [
                    f"Changed: {c}" for c in saved.changed
                ]
                text += (
                    "<br>Some cards changed since it was saved:<br>"
                    + "<br>".join(lines[:20])
                    + ("<br>…" if len(lines) > 20 else "")
                    + "<br>Start fresh is recommended."
                )
        self.banner_text.setText(text)
        self.handoff_btn.setVisible(not resume)
        self.discard_btn.setVisible(not resume)
        self.resume_btn.setVisible(resume and not problems)
        self.resume_saved_btn.setVisible(resume and problems)
        self.fresh_btn.setVisible(resume)
        self.fresh_btn.setText("Start fresh (recommended)" if problems else "Start fresh")
        self.banner.show()

    # -- edits ------------------------------------------------------------------

    def _on_class_toggled(self, _checked: bool) -> None:
        if self._updating:
            return
        self.enabled = {c for c, box in self.class_boxes.items() if box.isChecked()}
        self._schedule()

    def _on_template_toggled(self, _checked: bool) -> None:
        if self._updating:
            return
        ords = dict(self.draft.get("card_ords", {}))
        for ntid, boxes in self._template_boxes.items():
            on = [o for o, box in boxes if box.isChecked()]
            if len(on) == len(boxes):
                ords.pop(str(ntid), None)
            else:
                ords[str(ntid)] = on
        self.draft["card_ords"] = ords
        self._schedule()

    def _on_setting(self, *_args: Any) -> None:
        if self._updating:
            return
        d = self.draft
        d["batchSize"] = self.batch_size.value()
        d["encodeReps"] = self.encode_reps.value()
        d["cycleOrder"] = cast(Any, self.cycle_order.currentData())
        d["strictPunctuation"] = self.strict.isChecked()
        d["stemTolerance"] = self.stem.isChecked()
        d["holdoutPct"] = self.holdout_pct.value()
        d["difficultyAdjust"] = self.difficulty_adjust.isChecked()
        if self.data is None or self.hints.isChecked() != self.data.build.hints_on:
            d["hints"] = self.hints.isChecked()
        self.stem.setEnabled(not self.strict.isChecked())
        self._schedule()

    def _use_proposal(self) -> None:
        if self.data is None or self.data.proposal is None:
            return
        self.draft.update(self.data.proposal)
        self._refresh()

    def _save_settings(self) -> None:
        if self.settings_did is None:
            return
        deck_settings.save(self.ctx.storage(), self.settings_did, self.draft)
        tooltip("Settings saved for this deck.", parent=self)
        self._refresh()

    def _on_exposure(self, _index: int) -> None:
        if self._updating:
            return
        self.exposure = cast(ExposureLevel, self.exposure_combo.currentData())
        self._schedule()

    def _on_hint_edited(self, item: QTableWidgetItem | None) -> None:
        if self._updating or item is None or item.column() != 3:
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(key, str):
            return
        text = item.text().strip()
        save_hint(self.ctx.storage(), key, text or None)
        self._schedule()

    def _edit_mapping(self) -> None:
        if self.data is None:
            return
        maps = list(self.data.selection.mappings.values())
        first = next(
            ((m.ntid, m.template_ord) for m in maps if m.ineligible or m.answer_field is None),
            None,
        )
        dialog = MappingDialog(self, self.ctx.storage(), maps, self.data.note_types, first)
        dialog.exec()
        if dialog.saved:
            self._refresh()

    # -- start / resume ---------------------------------------------------------

    def _confirm_replace(self) -> bool:
        saved = self.saved_info
        if saved is None:
            return True
        what = (
            "a finished session waiting for its handoff"
            if saved.status == "handoff"
            else "a saved session"
        )
        answer = QMessageBox.question(
            self,
            "Recall Drill",
            f"These cards have {what}. Starting replaces it. Start fresh?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _already_open(self) -> bool:
        key = scope_key(self.scope)
        if self.ctx.raise_window(key):
            tooltip("This session is already open in its drill window.")
            return True
        return False

    def _start(self) -> None:
        if self._loading or self.data is None or not self.data.drillable:
            return
        if self._already_open() or not self._confirm_replace():
            return
        saved = self.saved_info
        if saved is not None and saved.status == "handoff":
            # Starting over a finished session declines its handoff.
            sessions.decline_handoff(self.ctx.storage(), saved.key, saved.saved, launch.now_ms())
            self._show_saved(None)
        self._launch_new()

    def _launch_new(self) -> None:
        data = self.data
        if data is None or not data.drillable:
            return
        ctrl, store = launch.start(
            self.ctx.storage(),
            scope=cast(sessions.ScopeJson, scope_to_json(data.scope)),
            deck_name=data.label,
            deck_items=data.build.deck_items,
            sources=data.build.sources,
            settings_did=data.settings_did,
            settings=self.draft,
            select_options=data.select_options,
            hints=data.build.hints_on,
            cfg=self.ctx.config(),
            holdout=data.holdout,
            overrides=data.build.overrides(),
        )
        open_drill_window(self.ctx, ctrl, store)
        self.close()

    def _start_fresh(self) -> None:
        if self._already_open():
            return
        saved = self.saved_info
        if saved is not None:
            sessions.discard(self.ctx.storage(), saved.key)
            self._show_saved(None)
        if self.data is not None and self.data.drillable and not self._loading:
            self._launch_new()

    def _resume(self) -> None:
        saved = self.saved_info
        if saved is None or saved.status != "resume" or self._already_open():
            return
        ctrl, store = launch.resume(self.ctx.storage(), saved.key, saved.saved, self.ctx.config())
        open_drill_window(self.ctx, ctrl, store)
        self.close()

    def _handoff(self) -> None:
        saved = self.saved_info
        if saved is None or saved.status != "handoff":
            return
        offer_handoff(self.ctx, self, saved.key, on_done=self._after_handoff)

    def _after_handoff(self) -> None:
        if self._closed:
            return
        self._show_saved(None)
        self._refresh()

    def _discard_saved(self) -> None:
        """ "Don't hand off": the finished session goes, nothing is written to Anki."""
        saved = self.saved_info
        if saved is None or saved.status != "handoff":
            return
        answer = QMessageBox.question(
            self,
            "Recall Drill",
            "Clear the finished session without handing it off? Nothing is written to Anki.",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Discard:
            return
        sessions.decline_handoff(self.ctx.storage(), saved.key, saved.saved, launch.now_ms())
        self._show_saved(None)

    # -- closing ----------------------------------------------------------------

    def closeEvent(self, a0: QCloseEvent | None) -> None:  # noqa: N802 (Qt override)
        self._timer.stop()
        self._closed = True  # drop late results
        if mw.pm.profile is not None:
            saveGeom(self, GEOM_KEY)
        if self in self.ctx.dialogs:
            self.ctx.dialogs.remove(self)
        if a0 is not None:
            a0.accept()


def open_setup(ctx: AddonContext, deck_id: int | None, search: str | None = None) -> SetupDialog:
    dialog = SetupDialog(ctx, deck_id, search)
    dialog.show()
    dialog.activateWindow()
    return dialog
