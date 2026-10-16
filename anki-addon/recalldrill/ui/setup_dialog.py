"""The setup panel: what to drill, the deck's settings, drill time, pacing, Start.

Reads with ``anki_io.panel`` off the main thread (``QueryOp``), shows the
result, and starts or resumes through ``launch``. Saves only:

- the deck's settings, on Start or Save (``deck_settings.json``);
- a manual hint, when one is edited (``hints.json``);
- a mapping, from "Edit mapping…" (``mappings.json``).

The pending banner's **Hand off finished session** runs the handoff
(``handoff_dialog``); the hold-back switch and its **Hold back N** button run the
hold-back (``holdback_ui``, v0.3), and turning the switch off may run a release.
Nothing else here writes to the collection.

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

**Drill time and pacing** (Phase 6): the drill time is measured (Don's own
active time per card; "no estimate yet" until there are 3 timed sessions), never
the web app's cold-start estimate, and the exposure picker is gone. For a deck
scope, the Pacing section takes a target date, the drill weekdays and how many
days early to finish (saved at once in ``pacing.json``), and shows today's N,
the drill minutes, Anki's minutes tomorrow and on the peak day (FSRS simulator,
else the revlog), each with its source, and the new/day or review-limit
warning. "Use N as max cards" fills in Max cards. Pacing is read in its own
background op after the card list.
"""

from __future__ import annotations

from datetime import date
from typing import Any, cast

from anki.decks import DeckId
from aqt import mw
from aqt.operations import QueryOp
from aqt.qt import (
    QCheckBox,
    QCloseEvent,
    QDate,
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    Qt,
    QTableWidget,
    QTableWidgetItem,
    QTimer,
    QVBoxLayout,
    QWidget,
    qconnect,
)
from aqt.utils import disable_help_button, restoreGeom, saveGeom, showWarning, tooltip

from .. import deck_settings, holdout, launch, pacing, sessions
from ..anki_io.cards import CARD_CLASSES, DEFAULT_ENABLED, CardClass
from ..anki_io.holdback import hold_back_state
from ..anki_io.panel import (
    PanelData,
    SavedInfo,
    exam_text,
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
from ..anki_io.workload import read_pacing
from ..deck_settings import DeckSettings
from ..holdback import button_label, default_order
from . import exam_tracker, holdback_ui, style
from .context import AddonContext
from .drill_window import HANDOFF_TOOLTIP, open_drill_window
from .handoff_dialog import confirm_finish_early, offer_handoff
from .mapping_dialog import MappingDialog
from .widgets import ComboBox, DateEdit, SpinBox

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


def _next_cards(n: int) -> str:
    return f"Next {n} card" if n == 1 else f"Next {n} cards"


class SetupDialog(QDialog):
    def __init__(
        self,
        ctx: AddonContext,
        deck_id: int | None,
        search: str | None = None,
        order: str | None = None,
        tag: str | None = None,
        classes: frozenset[CardClass] | None = None,
    ) -> None:
        super().__init__(None, Qt.WindowType.Window)
        self.ctx = ctx
        self._forced_tag = tag
        """"Only with tag" asked for by the caller (Drill next: Layer::N); first load only."""
        self._forced_order = order
        """Order asked for by the caller (the progress table's Drill next); None: the default."""
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        disable_help_button(self)
        self.deck_id = deck_id
        self.scope = Scope(search=search) if search else Scope(deck_id=deck_id)
        self.draft: DeckSettings = {}
        self.settings_did: int | None = None
        self.enabled: set[CardClass] = set(DEFAULT_ENABLED if classes is None else classes)
        """Ticked card types: the default, or the caller's (Drill next: new cards only).
        Not saved per deck, so this only sets the boxes once."""
        self.data: PanelData | None = None
        self._scope_text = ""
        """The scope's label (the deck's full name, or the search), for the header."""
        self.pacing_view: pacing.PacingView | None = None
        self._pacing_generation = 0
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
        root = style.install(self)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_header())
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.viewport().setAutoFillBackground(False)  # type: ignore[union-attr]
        body = QWidget()
        body.setObjectName("rdScrollBody")
        self.body = QVBoxLayout(body)
        self.body.setContentsMargins(20, 16, 20, 16)
        self.body.setSpacing(14)
        scroll.setWidget(body)
        body.setAutoFillBackground(
            False
        )  # QScrollArea.setWidget turns it on: keep the window's colour
        outer.addWidget(scroll, 1)

        # Scope
        scope_box, sl = style.section("Scope")
        self.scope_label = QLabel()
        self.scope_label.setWordWrap(True)
        sl.addWidget(self.scope_label)
        row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(
            "Search… e.g. tag:MedTerm_Ch03::Day05 (whole collection)"
        )
        self.search_btn = style.button("Use search")
        self.deck_btn = style.button("Use this deck")
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

        # Saved-session banner: the text on the left, the buttons on the right
        self.banner = style.frame("rdBanner")
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(14, 10, 14, 10)
        bl.setSpacing(10)
        self.banner_text = QLabel()
        self.banner_text.setWordWrap(True)
        bl.addWidget(self.banner_text, 1)
        self.resume_btn = style.button("Resume", "primary")
        self.resume_saved_btn = style.button("Resume with saved text")
        self.fresh_btn = style.button("Start fresh", "ghost")
        self.finish_btn = style.button("Finish with mastered cards")
        self.finish_btn.setToolTip(
            "Give the cards that aren't mastered back to the pool and finish with the "
            "mastered ones: they get the Final check, then you can hand them off"
        )
        self.handoff_btn = style.button("Hand off finished session", "primary")
        self.handoff_btn.setToolTip(HANDOFF_TOOLTIP)
        self.discard_btn = style.button("Don't hand off", "ghost")
        for b, fn in (
            (self.resume_btn, self._resume),
            (self.resume_saved_btn, self._resume),
            (self.fresh_btn, self._start_fresh),
            (self.finish_btn, self._finish_early),
            (self.handoff_btn, self._handoff),
            (self.discard_btn, self._discard_saved),
        ):
            b.setAutoDefault(False)
            qconnect(b.clicked, fn)
        for b in (
            self.discard_btn,
            self.finish_btn,
            self.fresh_btn,
            self.resume_saved_btn,
            self.resume_btn,
            self.handoff_btn,
        ):
            bl.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)
        self.banner.hide()
        self.body.addWidget(self.banner)

        # Cards
        cards_box, cl = style.section("Cards")
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        self.class_boxes: dict[CardClass, QCheckBox] = {}
        for i, c in enumerate(CARD_CLASSES):
            box = style.chip(QCheckBox(c))
            box.setChecked(c in self.enabled)
            qconnect(box.toggled, self._on_class_toggled)
            self.class_boxes[c] = box
            grid.addWidget(box, i // 3, i % 3, Qt.AlignmentFlag.AlignLeft)
        grid.setColumnStretch(3, 1)
        cl.addLayout(grid)
        self.hard_only = style.switch(
            QCheckBox("Only the cards that were hard in their last handoff")
        )
        self.hard_only.setChecked(True)
        self.hard_only.setToolTip(
            "rd::hard is a note tag, so a hard card's siblings carry it too. "
            "Untick to drill every card of the tagged notes."
        )
        self.hard_only.hide()
        qconnect(self.hard_only.toggled, self._schedule)
        cl.addWidget(self.hard_only)
        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)
        self.max_cards = SpinBox()
        self.max_cards.setRange(0, 100_000)
        self.max_cards.setSpecialValueText("all")
        self.max_cards.setFixedWidth(120)
        self.tag_edit = QLineEdit()
        self.tag_edit.setPlaceholderText("optional, an exact tag (e.g. rd::drill::A1)")
        self.order = ComboBox()
        self.order.addItem("Priority first", "priority_first")
        self.order.addItem("Deck order", "deck_order")
        self.order.setMinimumWidth(160)
        form.addRow("Max cards", self.max_cards)
        form.addRow("Only with tag", self.tag_edit)
        form.addRow("Order", self.order)
        cl.addLayout(form)
        qconnect(self.max_cards.valueChanged, self._schedule)
        qconnect(self.tag_edit.textChanged, self._schedule)
        qconnect(self.order.currentIndexChanged, self._schedule)
        self.templates_box = QWidget()
        tbl = QVBoxLayout(self.templates_box)
        tbl.setContentsMargins(0, 0, 0, 0)
        tbl.setSpacing(6)
        tbl.addWidget(style.text_label("Templates", "muted"))
        self.templates_layout = QVBoxLayout()
        self.templates_layout.setSpacing(6)
        tbl.addLayout(self.templates_layout)
        cl.addWidget(self.templates_box)
        self.sibling_label = QLabel()
        self.sibling_label.setWordWrap(True)
        cl.addWidget(self.sibling_label)
        # 2026-10-12: stale drill cards still suspended and waiting in this deck.
        self.waiting_label = style.note(kind="warn")
        self.waiting_label.setVisible(False)
        cl.addWidget(self.waiting_label)
        # v0.3: handed-off cards that still need their first Anki rating.
        self.unrated_label = style.note(kind="warn")
        self.unrated_label.setVisible(False)
        cl.addWidget(self.unrated_label)
        self.difficulty_label = style.text_label(kind="muted")
        cl.addWidget(self.difficulty_label)
        srow = QHBoxLayout()
        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        self.holdout_row = QWidget()
        hrow = QHBoxLayout(self.holdout_row)
        hrow.setContentsMargins(0, 0, 0, 0)
        self.holdout_label = style.text_label(kind="muted")
        self.holdout_pct = SpinBox()
        self.holdout_pct.setRange(0, deck_settings.HOLDOUT_MAX_PCT)
        self.holdout_pct.setSuffix(" %")
        self.holdout_pct.setFixedWidth(100)
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
        self.mapping_btn = style.button("Edit mapping…")
        self.mapping_btn.setAutoDefault(False)
        qconnect(self.mapping_btn.clicked, self._edit_mapping)
        srow.addWidget(self.summary_label, 1)
        srow.addWidget(self.mapping_btn, 0, Qt.AlignmentFlag.AlignTop)
        cl.addLayout(srow)
        self.body.addWidget(cards_box)

        # Settings
        settings_box, stl = style.section("Settings for this deck")
        prow = QHBoxLayout()
        self.proposal_label = style.note(
            "Most answers here are 3 words or fewer: terminology settings fit "
            "(strict punctuation on, word-ending tolerance off, hints on).",
            "info",
        )
        self.proposal_btn = style.button("Use terminology settings")
        self.proposal_btn.setAutoDefault(False)
        qconnect(self.proposal_btn.clicked, self._use_proposal)
        prow.addWidget(self.proposal_label, 1)
        prow.addWidget(self.proposal_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        self.proposal_row = QWidget()
        self.proposal_row.setLayout(prow)
        prow.setContentsMargins(0, 0, 0, 0)
        stl.addWidget(self.proposal_row)
        self.batch_size = SpinBox()
        self.batch_size.setRange(0, 50)
        self.batch_size.setSpecialValueText("Whole deck")
        self.encode_reps = SpinBox()
        self.encode_reps.setRange(1, 10)
        self.cycle_order = ComboBox()
        self.cycle_order.addItem("Shuffled", "shuffled")
        self.cycle_order.addItem("In order", "inOrder")
        self.strict = style.switch(QCheckBox("Punctuation must match (strict)"))
        self.stem = style.switch(QCheckBox("Forgive minor word endings (e.g. plurals)"))
        self.hints = style.switch(QCheckBox("Disambiguation hints on prompts"))
        self.difficulty_adjust = style.switch(
            QCheckBox("Adjust reps by difficulty (cards with review history only)")
        )
        self.difficulty_adjust.setToolTip(
            "Cards Anki finds hard (FSRS difficulty ≥ 7, or many lapses without FSRS) get "
            "one more blind typing and chunk earlier; easy ones (difficulty ≤ 3) one fewer. "
            "New cards have no FSRS data and keep the deck's settings."
        )
        numbers = QGridLayout()  # the number fields, two columns of label + field
        numbers.setHorizontalSpacing(12)
        numbers.setVerticalSpacing(8)
        numbers.addWidget(QLabel("Cards per batch"), 0, 0)
        numbers.addWidget(self.batch_size, 0, 1)
        numbers.addWidget(QLabel("Blind typings required"), 0, 2)
        numbers.addWidget(self.encode_reps, 0, 3)
        numbers.addWidget(QLabel("Cycle review order"), 1, 0)
        numbers.addWidget(self.cycle_order, 1, 1)
        numbers.setColumnStretch(1, 1)
        numbers.setColumnStretch(3, 1)
        stl.addLayout(numbers)
        switches = QGridLayout()  # the on/off options, two columns
        switches.setHorizontalSpacing(16)
        switches.setVerticalSpacing(6)
        switches.addWidget(self.strict, 0, 0)
        switches.addWidget(self.stem, 0, 1)
        switches.addWidget(self.hints, 1, 0)
        switches.addWidget(self.difficulty_adjust, 1, 1)
        stl.addLayout(switches)
        # v0.3: keep a deck's new cards out of Anki until they are drilled.
        self.hold_back_box = QWidget()
        hbl = QHBoxLayout(self.hold_back_box)
        hbl.setContentsMargins(0, 0, 0, 0)
        self.hold_back = style.switch(QCheckBox("Keep new cards out of Anki until drilled"))
        self.hold_back.setToolTip(
            "For this deck and its subdecks. Turning it on offers to suspend the new "
            "cards that are out of Anki undrilled (tagged rd::held; one undo step). The "
            "handoff unsuspends drilled cards; Tools → Recall Drill → More → Waiting cards sends "
            "the rest undrilled. Turning it off offers to release the held cards."
        )
        self.hold_back_btn = style.button(button_label(0))
        self.hold_back_btn.setAutoDefault(False)
        self.hold_back_btn.setToolTip(
            "Suspend this deck's new, unsuspended cards that aren't handed off and waiting "
            "for Anki, and tag their notes rd::held. One undo step."
        )
        self.hold_back_btn.hide()
        hbl.addWidget(self.hold_back)
        hbl.addWidget(self.hold_back_btn)
        hbl.addStretch(1)
        stl.addWidget(self.hold_back_box)
        self.hold_back_note = style.text_label(kind="muted")
        self.hold_back_note.hide()
        stl.addWidget(self.hold_back_note)
        qconnect(self.hold_back.toggled, self._on_hold_back)
        qconnect(self.hold_back_btn.clicked, self._hold_back_now)
        self.settings_note = style.text_label(kind="muted")
        srow2 = QHBoxLayout()
        srow2.addWidget(self.settings_note, 1)
        self.save_settings_btn = style.button("Save settings")
        self.save_settings_btn.setAutoDefault(False)
        qconnect(self.save_settings_btn.clicked, self._save_settings)
        srow2.addWidget(self.save_settings_btn, 0, Qt.AlignmentFlag.AlignRight)
        stl.addLayout(srow2)
        qconnect(self.batch_size.valueChanged, self._on_setting)
        qconnect(self.encode_reps.valueChanged, self._on_setting)
        qconnect(self.cycle_order.currentIndexChanged, self._on_setting)
        qconnect(self.strict.toggled, self._on_setting)
        qconnect(self.stem.toggled, self._on_setting)
        qconnect(self.hints.toggled, self._on_setting)
        qconnect(self.difficulty_adjust.toggled, self._on_setting)
        self.body.addWidget(settings_box)

        # Hints
        self.hints_box, hl = style.section("Hints")
        hl.addWidget(
            style.text_label(
                "Prompts another card shares, which no automatic hint can tell apart. "
                "Type a hint to show after the prompt; empty the cell to remove yours.",
                "muted",
            )
        )
        self.hints_table = QTableWidget(0, 4)
        self.hints_table.setHorizontalHeaderLabels(["PROMPT", "ANSWER", "CONFLICTS WITH", "HINT"])
        self.hints_table.setShowGrid(False)
        header = self.hints_table.horizontalHeader()
        if header is not None:
            header.setStretchLastSection(True)
        qconnect(self.hints_table.itemChanged, self._on_hint_edited)
        hl.addWidget(self.hints_table)
        self.body.addWidget(self.hints_box)

        # Drill time (measured)
        est, el = style.section("Drill time")
        self.estimate_label = QLabel()
        self.estimate_label.setWordWrap(True)
        self.estimate_source = style.text_label(kind="muted")
        el.addWidget(self.estimate_label)
        el.addWidget(self.estimate_source)
        self.body.addWidget(est)

        # Pacing (deck scopes)
        self.pacing_box, pl = style.section("Pacing")
        prow1 = QHBoxLayout()
        self.pace_on = style.switch(QCheckBox("Pace to a target date"))
        self.pace_date = DateEdit()
        self.pace_date.setCalendarPopup(True)
        self.pace_date.setDisplayFormat("ddd d MMM yyyy")
        self.pace_early = SpinBox()
        self.pace_early.setRange(0, 30)
        self.pace_early.setSuffix(" day(s) early")
        self.pace_early.setToolTip("Finish this many days before the target date.")
        prow1.addWidget(self.pace_on)
        prow1.addWidget(self.pace_date)
        prow1.addWidget(QLabel("finish"))
        prow1.addWidget(self.pace_early)
        prow1.addStretch(1)
        pl.addLayout(prow1)
        prow2 = QHBoxLayout()
        prow2.setSpacing(6)
        prow2.addWidget(QLabel("Drill on"))
        self.pace_days: list[QCheckBox] = []
        for name in pacing.WEEKDAY_NAMES:
            box = style.chip(QCheckBox(name))
            self.pace_days.append(box)
            prow2.addWidget(box)
        prow2.addStretch(1)
        pl.addLayout(prow2)
        prow3 = QHBoxLayout()
        self.exam_on = style.switch(QCheckBox("Exam date"))
        self.exam_date = DateEdit()
        self.exam_date.setCalendarPopup(True)
        self.exam_date.setDisplayFormat("ddd d MMM yyyy")
        self.exam_label = style.text_label(kind="muted")
        prow3.addWidget(self.exam_on)
        prow3.addWidget(self.exam_date)
        prow3.addWidget(self.exam_label, 1)
        pl.addLayout(prow3)
        self.pace_line = QLabel()
        self.pace_line.setWordWrap(True)
        self.pace_sources = style.text_label(kind="muted")
        self.pace_warning = style.note(kind="warn")
        self.pace_warning.hide()
        pl.addWidget(self.pace_line)
        pl.addWidget(self.pace_sources)
        pl.addWidget(self.pace_warning)
        self.use_n_btn = style.button("Use N as max cards")
        self.use_n_btn.setAutoDefault(False)
        qconnect(self.use_n_btn.clicked, self._use_pace_n)
        pl.addWidget(self.use_n_btn, 0, Qt.AlignmentFlag.AlignRight)
        qconnect(self.pace_on.toggled, self._on_pacing_edited)
        qconnect(self.pace_date.dateChanged, self._on_pacing_edited)
        qconnect(self.pace_early.valueChanged, self._on_pacing_edited)
        qconnect(self.exam_on.toggled, self._on_pacing_edited)
        qconnect(self.exam_date.dateChanged, self._on_pacing_edited)
        for box in self.pace_days:
            qconnect(box.toggled, self._on_pacing_edited)
        self.pacing_box.hide()
        self.body.addWidget(self.pacing_box)
        self.body.addStretch(1)

        # Footer bar: the count on the left, Sections…, Close and Start on the right
        footer = style.frame("rdBar", "footer")
        bottom = QHBoxLayout(footer)
        bottom.setContentsMargins(20, 10, 20, 10)
        bottom.setSpacing(8)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.sections_btn = style.button("Sections…")
        self.sections_btn.setAutoDefault(False)
        self.sections_btn.setToolTip("Which sections (subdecks) of this deck are drilled.")
        qconnect(self.sections_btn.clicked, self._open_sections)
        self.start_btn = style.button("Start", "primary")
        self.start_btn.setDefault(True)
        close = style.button("Close", "ghost")
        close.setAutoDefault(False)
        qconnect(self.start_btn.clicked, self._start)
        qconnect(close.clicked, self.close)
        bottom.addWidget(self.status_label, 1)
        bottom.addWidget(self.sections_btn)
        bottom.addWidget(close)
        bottom.addWidget(self.start_btn)
        outer.addWidget(footer)

    def _build_header(self) -> QWidget:
        """The strip above the scroll area: the deck's name and path, the exam tracker's pill
        and countdown when the deck has an exam, and up to two tiles."""
        strip = style.frame("rdBar", "header")
        col = QVBoxLayout(strip)
        col.setContentsMargins(20, 14, 20, 14)
        col.setSpacing(10)
        top = QHBoxLayout()
        names = QVBoxLayout()
        names.setSpacing(0)
        self.header_title = style.text_label("", "title", wrap=False)
        self.header_path = style.text_label("", "muted", wrap=False)
        names.addWidget(self.header_title)
        names.addWidget(self.header_path)
        top.addLayout(names, 1)
        self.header_pill = style.status_pill("exam", "")
        self.header_exam = style.text_label("", "strong", wrap=False)
        top.addWidget(self.header_pill, 0, Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(self.header_exam, 0, Qt.AlignmentFlag.AlignVCenter)
        self.header_pill.hide()
        self.header_exam.hide()
        col.addLayout(top)
        tiles = QHBoxLayout()
        tiles.setSpacing(10)
        self.tile_cards, self.tile_cards_value = style.tile("cards to drill")
        self.tile_pace, self.tile_pace_value = style.tile("a day")
        tiles.addWidget(self.tile_cards)
        tiles.addWidget(self.tile_pace)
        tiles.addStretch(1)
        self.tile_cards.hide()
        self.tile_pace.hide()
        self.tiles_row = tiles
        col.addLayout(tiles)
        return strip

    def _show_header(self) -> None:
        """Name, exam and tiles, from what the panel already loaded (the scope's label, the
        panel data, the pacing view, and the exam tracker's cached numbers: no read)."""
        label = self._scope_text
        if self.scope.deck_id is not None:
            *parents, leaf = label.split("::")
            self.header_title.setText(leaf)
            self.header_path.setText(" › ".join(parents))
        else:
            self.header_title.setText(label)
            self.header_path.setText("Search")
        self.header_path.setVisible(bool(self.header_path.text()))
        data = self.data
        numbers = (
            exam_tracker.cached_numbers(data.exam_did, data.today) if data is not None else None
        )
        if numbers is not None:
            pill, line = exam_tracker.panel_summary(numbers)
            self.header_pill.setText(pill)
            style.set_prop(self.header_pill, "rdPill", numbers.status)
            self.header_exam.setText(line)
        self.header_pill.setVisible(numbers is not None)
        self.header_exam.setVisible(numbers is not None)
        self.tile_cards_value.setText(f"{data.drillable:,}" if data is not None else "")
        self.tile_cards.setVisible(data is not None)
        view = self.pacing_view
        pace_n = view.pace.per_day if view is not None and view.pace.status == "ok" else 0
        show_pace = self.scope.deck_id is not None and self.pace_on.isChecked() and pace_n > 0
        self.tile_pace_value.setText(f"{pace_n:,}")
        self.tile_pace.setVisible(show_pace)

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
        ) -> tuple[str, int | None, DeckSettings, SavedInfo | None, frozenset[int], bool]:
            did = settings_deck(col, storage, scope)
            held = (
                hold_back_state(col, storage, scope.deck_id).on
                if scope.deck_id is not None
                else False
            )
            return (
                scope_label(col, scope),
                did,
                initial_settings(storage, did),
                read_saved(col, storage, scope_key(scope)),
                hard_exclusions(storage, scope),
                held,
            )

        def done(
            result: tuple[str, int | None, DeckSettings, SavedInfo | None, frozenset[int], bool],
        ) -> None:
            if self._closed or scope != self.scope:
                return
            label, did, draft, saved, exclude, held = result
            self.settings_did = did
            # A deck that holds cards back drills in deck order (new-queue position) by default.
            self._updating = True
            try:
                wanted = self._forced_order or default_order(held)
                self._forced_order = None  # only for the first load
                if self._forced_tag is not None:
                    self.tag_edit.setText(self._forced_tag)
                    self._forced_tag = None
                self.order.setCurrentIndex(max(0, self.order.findData(wanted)))
            finally:
                self._updating = False
            self.sections_btn.setEnabled((scope.deck_id or self.deck_id) is not None)
            self.draft = draft
            self.hard_exclude = exclude
            self.hard_only.setVisible(bool(exclude))
            if scope.deck_id is not None:
                self._updating = True
                try:
                    self._show_pacing_settings(scope.deck_id)
                finally:
                    self._updating = False
            what = "Deck" if scope.deck_id is not None else "Search"
            self.scope_label.setText(f"<b>{what}:</b> {label}")
            self._scope_text = label
            self.setWindowTitle(f"Recall Drill: {label}")
            self._show_saved(saved)
            self._show_header()
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
        did = self.settings_did

        def op(col: Any) -> PanelData:
            return read_panel(col, storage, scope, options, cast(DeckSettings, draft), did, cfg)

        def done(data: PanelData) -> None:
            if self._closed or gen != self._generation:
                return
            self.data = data
            self._show(data)
            self._set_loading(False)
            self._refresh_pacing()

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
            self._show_header()
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
                rl.setSpacing(6)
                rl.addWidget(style.text_label(nt.name, "strong", wrap=False))
                boxes: list[tuple[int, QCheckBox]] = []
                for ord_, name in nt.templates:
                    box = style.chip(QCheckBox(name))
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
            style.set_prop(self.sibling_label, "rdNote", "warn")
            style.set_prop(self.sibling_label, "rdText", None)
            self.sibling_label.setText(
                f"⚠ Siblings: {sel.sibling_cards} picked cards share a note with another "
                f"picked card ({_plural(sel.sibling_notes, 'note')}). Drilling both directions "
                "at once lets one card give the other away."
            )
        else:
            style.set_prop(self.sibling_label, "rdNote", None)
            style.set_prop(self.sibling_label, "rdText", "muted")
            self.sibling_label.setText("Siblings: 0 picked cards share a note.")
        self.waiting_label.setText(f"⚠ {data.waiting_line}" if data.waiting_line else "")
        self.waiting_label.setVisible(bool(data.waiting_line))
        self.unrated_label.setText(f"⚠ {data.unrated_line}" if data.unrated_line else "")
        self.unrated_label.setVisible(bool(data.unrated_line))

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
        if sel.handed_off:
            lines.append(
                f"Handed off, waiting for Anki: {sel.handed_off} "
                f"({'it stays' if sel.handed_off == 1 else 'they stay'} out until Anki "
                "reviews them)."
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
        self.hold_back_box.setVisible(data.scope.deck_id is not None)
        self.hold_back.setChecked(data.hold_back)
        self.hold_back_note.setText(f"Set on {data.hold_back_from}." if data.hold_back_from else "")
        self.hold_back_note.setVisible(bool(data.hold_back_from))
        offer = data.hold_back and (data.hold_back_count > 0 or data.hold_back_release > 0)
        self.hold_back_btn.setVisible(offer)
        self.hold_back_btn.setText(button_label(data.hold_back_count, data.hold_back_release))
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
        if data.drill_seconds is None:
            self.estimate_label.setText(
                f"{_next_cards(data.drillable)}: {data.drill_source}" if data.drillable else "—"
            )
            self.estimate_source.setText("")
            self.estimate_source.setVisible(False)
        else:
            self.estimate_label.setText(f"{_next_cards(data.drillable)}: {data.estimate_text()}")
            self.estimate_source.setText(f"From {data.drill_source}.")
            self.estimate_source.setVisible(True)

    # -- pacing -----------------------------------------------------------------

    def _show_pacing_settings(self, did: int) -> None:
        s = pacing.load(self.ctx.storage(), did)
        today = QDate.currentDate()
        self.pace_on.setChecked(s.target_date is not None)
        t = s.target_date
        self.pace_date.setDate(QDate(t.year, t.month, t.day) if t else today.addDays(14))
        self.pace_early.setValue(s.finish_days_before)
        for i, box in enumerate(self.pace_days):
            box.setChecked(i in s.drill_weekdays)
        e = s.exam_date
        self.exam_on.setChecked(e is not None)
        self.exam_date.setDate(QDate(e.year, e.month, e.day) if e else today.addDays(14))
        self._enable_pacing_inputs()

    def _enable_pacing_inputs(self) -> None:
        on = self.pace_on.isChecked()
        self.pace_date.setEnabled(on)
        self.pace_early.setEnabled(on)
        for box in self.pace_days:
            box.setEnabled(on)
        self.exam_date.setEnabled(self.exam_on.isChecked())

    def _pacing_from_inputs(self) -> pacing.PacingSettings:
        d = self.pace_date.date()
        target = date(d.year(), d.month(), d.day()) if self.pace_on.isChecked() else None
        days = frozenset(i for i, box in enumerate(self.pace_days) if box.isChecked())
        e = self.exam_date.date()
        exam = date(e.year(), e.month(), e.day()) if self.exam_on.isChecked() else None
        return pacing.PacingSettings(target, days, self.pace_early.value(), exam)

    def _show_exam_line(self) -> None:
        """The exam line: the date field's own value, else the one a parent deck gives."""
        data = self.data
        if data is None or data.today is None:
            self.exam_label.setText("")
            return
        own = self._pacing_from_inputs().exam_date
        self.exam_label.setText(exam_text(own, data.exam_inherited, data.today) or "")

    def _on_pacing_edited(self, *_args: Any) -> None:
        if self._updating or self.scope.deck_id is None:
            return
        self._enable_pacing_inputs()
        pacing.save(self.ctx.storage(), self.scope.deck_id, self._pacing_from_inputs())
        exam_tracker.request_refresh()  # an exam date may have changed
        self._show_exam_line()
        self._refresh_pacing()

    def _refresh_pacing(self) -> None:
        data = self.data
        did = self.scope.deck_id
        self._pacing_generation += 1
        gen = self._pacing_generation
        if data is None or did is None or data.scope.deck_id != did:
            self.pacing_box.hide()
            self.pacing_view = None
            self._show_header()
            return
        self.pacing_box.show()
        self._show_exam_line()
        if not self.pace_on.isChecked():
            self.pacing_view = None
            self.pace_line.setText("Set a target date (a chapter exam) to pace this deck.")
            self.pace_sources.setText("")
            self.pace_sources.setVisible(False)
            self.pace_warning.setText("")
            self.pace_warning.setVisible(False)
            self.use_n_btn.setEnabled(False)
            self._show_header()
            return
        self.pace_line.setText("Working out the pace…")
        self.use_n_btn.setEnabled(False)
        storage, cfg, draft = self.ctx.storage(), self.ctx.config(), dict(self.draft)

        def op(col: Any) -> pacing.PacingView:
            return read_pacing(
                col, storage, did, data.selection, data.card_shapes, data.speed, draft, cfg
            )

        def done(view: pacing.PacingView) -> None:
            if self._closed or gen != self._pacing_generation:
                return
            self._show_pacing(view)

        def failed(exc: Exception) -> None:
            if self._closed or gen != self._pacing_generation:
                return
            self.pace_line.setText(f"Couldn't work out the pace: {exc}")

        QueryOp(parent=self, op=op, success=done).failure(failed).run_in_background()

    def _show_pacing(self, view: pacing.PacingView) -> None:
        self.pacing_view = view
        self.pace_line.setText(view.line())
        ok = view.pace.status == "ok"
        self.pace_sources.setText(view.sources() if ok else "")
        self.pace_sources.setVisible(ok)
        self.pace_warning.setText(f"⚠ {view.warning}" if view.warning else "")
        self.pace_warning.setVisible(bool(view.warning))
        n = view.pace.per_day
        self.use_n_btn.setEnabled(ok and n > 0)
        self.use_n_btn.setText(f"Use {n} as max cards" if ok and n > 0 else "Use N as max cards")
        self._show_header()

    def _use_pace_n(self) -> None:
        view = self.pacing_view
        if view is None or view.pace.per_day <= 0:
            return
        self.max_cards.setValue(view.pace.per_day)  # schedules a refresh

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
            was = _saved_tag(saved.saved)
            now = self.tag_edit.text().strip()
            if was.casefold() != now.casefold():
                # The save is per deck, whatever the tag; say what it was built with.
                text += (
                    f"<br>It was built with tag {was}, the panel now has {now or 'no tag'}."
                    if was
                    else f"<br>It was built with no tag, the panel now has tag {now}."
                )
                text += "<br>Resume continues it as saved; Start fresh builds from the panel."
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
        finish = self._finish_button(saved)
        self.finish_btn.setVisible(finish.show)
        self.finish_btn.setText(finish.label)
        self.banner.show()

    @staticmethod
    def _finish_counts(saved: SavedInfo) -> sessions.FinishEarlyCounts:
        check = saved.check
        return sessions.finish_early_counts(
            saved.saved,
            check.missing if check is not None else (),
            check.changed if check is not None else (),
        )

    def _finish_button(self, saved: SavedInfo) -> sessions.FinishEarlyButton:
        addon = cast(dict[str, Any], saved.saved.get("addon") or {})
        counts = self._finish_counts(saved)
        button = sessions.finish_early_button(
            counts,
            "panel",
            drill_again=addon.get("drillAgainOf") is not None,
            final_check=saved.saved.get("phase") == "final",
        )
        shown = saved.status == "resume" and saved.check is not None
        return sessions.FinishEarlyButton(button.show and shown, button.label)

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

    def _on_hold_back(self, checked: bool) -> None:
        """The switch: saved at once (only this key), then the write it offers."""
        did = self.scope.deck_id
        if self._updating or did is None:
            return
        deck_settings.set_hold_back(self.ctx.storage(), did, checked)
        self.draft["holdBack"] = checked
        if checked:
            self.order.setCurrentIndex(max(0, self.order.findData(default_order(True))))
            holdback_ui.hold_back(self, self.ctx, did, self._refresh)
        else:
            holdback_ui.release_held(self, self.ctx, did, self._refresh)

    def _hold_back_now(self) -> None:
        did = self.scope.deck_id
        if did is not None:
            holdback_ui.hold_back(self, self.ctx, did, self._refresh)

    def _open_sections(self) -> None:
        from .entry import open_setup_for
        from .sections_dialog import open_sections

        open_sections(self.ctx, open_setup_for, self.scope.deck_id or self.deck_id, open_setup_for)

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

    def _finish_early(self) -> None:
        """ "Finish with K mastered cards": confirm, cut the save, and open the
        drill window on its Final check (refused while a window drives the save)."""
        saved = self.saved_info
        if saved is None or not self._finish_button(saved).show or self._already_open():
            return
        counts = self._finish_counts(saved)
        if not confirm_finish_early(self, counts):
            return
        check = saved.check
        assert check is not None
        try:
            ctrl, store = launch.finish_early(
                self.ctx.storage(),
                saved.key,
                saved.saved,
                self.ctx.config(),
                check.missing,
                check.changed,
            )
        except ValueError as exc:
            showWarning(f"Recall Drill couldn't finish the session early: {exc}")
            return
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


def _saved_tag(saved: dict[str, Any]) -> str:
    """The "Only with tag" a saved session was built with ('' for none)."""
    addon = saved.get("addon") or {}
    options = addon.get("selectOptions") or {}
    return str(options.get("extra_tag") or "").strip()


def open_setup(
    ctx: AddonContext,
    deck_id: int | None,
    search: str | None = None,
    order: str | None = None,
    tag: str | None = None,
    classes: frozenset[CardClass] | None = None,
) -> SetupDialog:
    dialog = SetupDialog(ctx, deck_id, search, order, tag, classes)
    dialog.show()
    dialog.activateWindow()
    return dialog
