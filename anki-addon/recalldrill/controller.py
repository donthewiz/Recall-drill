"""The drill session's behavior without Qt: a port of ``src/components/SessionView.tsx``.

SessionView is not a pure view. It owns the pre-wrong snapshot that "Count as
correct" re-applies, the reveal flag the next answer consumes, the feedback
dwell, the Extra pause, the manual-advance rules for the cycle and the Final
check, editing while a wrong verdict shows, the double-Enter guard, and saving
after every answer. All of that lives here, so it is unit-tested; the Phase 3b
Qt window only renders :meth:`DrillController.view` and runs the returned
effects (start a timer, play audio, show a notice, clear the input).

Each handler sits beside a comment naming the SessionView handler it ports.
The engine (``engine/``) is called exactly as SessionView calls it, and is
never changed here.

What the add-on adds on top of SessionView (none of it reaches the engine):

- the "other card's answer" catch (:data:`COLLISION_MESSAGE`);
- :class:`PlayAnswerAudio` when the feedback shows the full back,
  :class:`StopAudio` when the next trial shows another card, and (config
  ``autoplay_question_audio``) :class:`PlayQuestionAudio` when a card comes up;
- :class:`Flash`, SessionView's ``triggerFlash``, as an effect;
- on an image card, the feedback for the full answer shows Anki's rendered
  answer side in place of the front (``ViewModel.answer_html``);
- an Extra that is only an image (the web app's Extra is text) counts as an
  Extra: it is shown and it holds the pause like a text Extra;
- editing happens in Anki's Browser (``begin_edit`` / ``apply_card_edit`` /
  ``cancel_edit``), so the web app's write-back to a saved deck and its
  "Saved for this session only." notice don't apply;
- **active drill time** (Phase 6): the time between consecutive actions
  (submit, reveal, continue, override, next batch), each gap capped at
  ``ControllerSettings.idle_cap_ms`` so a break doesn't count, is added to
  :attr:`DrillController.active_ms` and to the answered card's share
  (:attr:`DrillController.active_ms_by_item`). The clock starts at
  :meth:`DrillController.start` and stops at Save and stop, so a gap across a
  saved or closed session never counts. Both are saved in the ``addon`` block.

Where this deliberately differs from SessionView:

- After "Count as correct" auto-advances, SessionView leaves its Continue
  button up on the next trial (``handleOverride``'s dwell callback never
  resets ``showNextBtn``); pressing it there runs ``applyNext`` in the cycle.
  The dwell here always ends with Continue down.
- Every action is ignored during a dwell (the busy guard), End session too;
  SessionView's End session also works mid-dwell.

Kept as SessionView has it: End session during the Extra pause saves the state
still on screen (App saves ``sessionState``), so that one answer is lost.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from .card_html import answer_side
from .engine.grading import exact_match
from .engine.history import rank_hardest_cards
from .engine.items import item_overrides, partition_into_batches
from .engine.jscompat import js_round, js_trim
from .engine.progress import compute_session_progress
from .engine.session import (
    DWELL_MS,
    SESSION_COMPLETE_ID,
    advance_to_next_batch,
    apply_answer,
    apply_next,
    compute_accuracy_percent,
    compute_batch_summary,
    edit_current_item,
    select_trial,
)
from .engine.types import (
    DeckItem,
    DrillItem,
    Feedback,
    ItemOverrides,
    SessionState,
    Trial,
    Verdict,
    WordDiffResult,
)
from .pacing import minutes_text
from .sources import SourceRef, source_to_json

log = logging.getLogger(__name__)

COLLISION_MESSAGE = (
    "That's the answer to another card with this prompt. This one wants a different form."
)

# SessionView's BLIND_PLACEHOLDER: stage-specific placeholder while blind.
BLIND_PLACEHOLDER: dict[str, str] = {
    "chunks": "Type this part from memory...",
    "combine": "Type it from memory...",
    "remediate": "Type this from memory...",
    "full": "Type the full answer from memory...",
    "cycle": "Type the answer from memory...",
    "final": "Type the full answer from memory...",
}
BLIND_HINT = "Type from pure active recall • press Esc or click Show Answer if stuck"

# Stages that ask for the whole answer: the collision catch only runs there.
_WHOLE_ANSWER_STAGES = frozenset({"full", "cycle", "final"})

_IMG_RE = re.compile(r"<img\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Effects: what the UI must do after an action
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StartDwell:
    """Start a single-shot timer; call :meth:`DrillController.dwell_elapsed` when it fires."""

    ms: int


@dataclass(frozen=True)
class PlayAnswerAudio:
    """Play the answer side's audio of this card (feedback shows its full back)."""

    cid: int


@dataclass(frozen=True)
class Persisted:
    """The session was saved (``persist`` returned)."""


@dataclass(frozen=True)
class PersistFailed:
    """``persist`` raised. The drill goes on; the UI should say the save failed."""

    error: str


@dataclass(frozen=True)
class SessionComplete:
    """The Final check finished. Emitted once."""


@dataclass(frozen=True)
class SessionStopped:
    """Save and stop / End session: show the done screen for a saved session."""


@dataclass(frozen=True)
class CollisionNotice:
    """The typed text is another card's answer for the same prompt."""

    other_answer: str
    message: str = COLLISION_MESSAGE


@dataclass(frozen=True)
class ClearInput:
    """Empty the answer box (SessionView's ``setTypedValue('')``)."""


@dataclass(frozen=True)
class StopAudio:
    """The trial now on screen is another card's: stop whatever is playing.

    Not emitted between trials of the same card, so a term's answer audio
    isn't cut off by a 500 ms dwell."""


@dataclass(frozen=True)
class PlayQuestionAudio:
    """A card came up (config ``autoplay_question_audio``): play its question audio."""

    cid: int


@dataclass(frozen=True)
class Flash:
    """SessionView's ``triggerFlash``: tint the card green (``ok``) or red for
    :data:`FLASH_MS`."""

    ok: bool


FLASH_MS = 400

Effect = (
    StartDwell
    | PlayAnswerAudio
    | PlayQuestionAudio
    | StopAudio
    | Flash
    | Persisted
    | PersistFailed
    | SessionComplete
    | SessionStopped
    | CollisionNotice
    | ClearInput
)


# ---------------------------------------------------------------------------
# Settings and the view model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ControllerSettings:
    deck_name: str = ""
    """``SavedSessionState.deckName``: what the session is called on screen."""
    collision_catch: bool = True
    """The "other card's answer" catch (config ``collision_catch``)."""
    play_audio_on_feedback: bool = True
    """Play the answer's audio when feedback shows the full back
    (config ``play_audio_on_feedback``)."""
    source_deck_editable: bool = True
    """``SavedSessionState.sourceDeckEditable``: False for a drill-again session."""
    autoplay_question_audio: bool = False
    """Play a card's question audio when it comes up (config ``autoplay_question_audio``)."""
    idle_cap_ms: int = 120_000
    """Active time: the most one gap between actions counts (config ``idle_cap_seconds``)."""


Mode = Literal["trial", "feedback", "batch_done", "done"]
CueKind = Literal["firstLetter", "present", "none"]


@dataclass(frozen=True)
class CueView:
    kind: CueKind
    text: str
    """The first-letter pattern, the presented text, or ``""``."""


@dataclass(frozen=True)
class FeedbackView:
    text: str
    type: Literal["success", "danger", "info"]
    diff: tuple[WordDiffResult, ...] | None
    verdict: Verdict | None


@dataclass(frozen=True)
class Buttons:
    check: bool
    """Check answer (or Continue on a presentation beat): ``submit``."""
    reveal: bool
    """Show target (Esc): ``reveal``."""
    override: bool
    """Count as correct (Ctrl+Enter): ``override``."""
    continue_: bool
    """Continue after feedback: ``continue_``."""
    edit: bool
    """Edit in Anki: ``begin_edit``."""
    next_batch: bool
    save: bool
    """End session / Save and stop: ``save_and_stop``."""


@dataclass(frozen=True)
class StatsLine:
    attempts: int
    misses: int
    near_misses: int
    reveals: int
    overrides: int
    accuracy_percent: int
    text: str
    """SessionView's line: ``Attempts: 3 • Misses: 1`` plus the non-zero rest."""


@dataclass(frozen=True)
class ProgressView:
    total: int
    mastered: int
    ready: int
    encoding: int
    new: int
    mastered_percent: int
    batch_encoded_percent: int
    deck_encoded_percent: int
    batch_number: int
    total_batches: int
    is_batched: bool


@dataclass(frozen=True)
class BatchDoneView:
    """The interstitial between batches."""

    batch_number: int
    total_batches: int
    items_mastered: int
    batch_size: int
    trials_spent: int
    accuracy_percent: int
    remaining: str | None
    """``"Remaining time at your pace in this session: about 5 min"`` or None
    (no active time measured yet)."""


@dataclass(frozen=True)
class Dot:
    item_id: int
    status: str
    current: bool
    title: str


@dataclass(frozen=True)
class ViewModel:
    mode: Mode
    item_id: int | None
    cid: int | None
    prompt: str
    """The trial's prompt (engine text, hint suffix included)."""
    front_html: str
    """Anki's rendered question for display (``SourceRef.front_html``)."""
    hint: str
    """``SourceRef.hint``: the display appends it to ``front_html``."""
    card_ord: int
    """The card's ord, for Anki's ``card cardN`` body class (the note type CSS)."""
    css: str
    label: str
    """The stage pill, e.g. ``Chunk Practice • 1/3``."""
    detail: str
    """The top bar, e.g. ``Encoding • Part 1 of 3`` or ``Batch 1 of 3 complete``."""
    batch_label: str
    """``Batch 1/3`` beside the detail while batched, else ``""``."""
    cue: CueView
    cue_badge: str
    sub_text: str
    blind_hint: str
    placeholder: str
    input_read_only: bool
    """A presentation beat: nothing to type, Enter continues."""
    check_label: str
    revealed: bool
    feedback: FeedbackView | None
    shows_full_back: bool
    extra: str | None
    extra_html: str | None
    image_front: bool
    """``SourceRef.image_front``: the front shows an image (fit to the window)."""
    answer_html: str | None
    """An image card's rendered answer side (``card_html.answer_side``): while
    the feedback shows the full back it replaces the front; else None."""
    audio_side: Literal["q", "a"]
    """What "Replay audio" plays: the answer once the feedback shows the full back."""
    notice: str | None
    editing: bool
    processing: bool
    buttons: Buttons
    stats: StatsLine
    progress: ProgressView
    batch_done: BatchDoneView | None
    dots: tuple[Dot, ...]


@dataclass(frozen=True)
class HardCard:
    item_id: int
    cid: int
    front: str
    back: str
    attempts: int
    parts: str
    """``2 misses • 1 reveal • 1 in final check • 7 tries``."""
    hard_spans: tuple[str, ...]


@dataclass(frozen=True)
class FinalMiss:
    item_id: int
    cid: int
    front: str
    back: str
    final_misses: int


@dataclass(frozen=True)
class DoneSummary:
    """DoneView's data."""

    is_complete: bool
    title: str
    deck_name: str
    mastered: int
    total: int
    attempts: int
    accuracy_percent: int
    accuracy_line: str
    """``1 miss • 2 reveals • 1 near — answers typed after a reveal don't count…``."""
    summary: str
    hardest: tuple[HardCard, ...]
    """Where you struggled: top 5 by ``cardTroubleScore``."""
    missed_in_final: tuple[FinalMiss, ...]
    drill_again: tuple[int, ...]
    """Item ids for "Drill these cards again" (only once the session is complete)."""
    drill_again_label: str


@dataclass(frozen=True)
class EditRequest:
    """Open this card in Anki's Browser; call ``apply_card_edit`` when it closes."""

    cid: int
    item_id: int
    front: str
    back: str
    extra: str


# ---------------------------------------------------------------------------
# The controller
# ---------------------------------------------------------------------------


def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def _json_copy(value: Any) -> Any:
    """A JSON round trip: what the saved file holds (``undefined`` keys dropped)."""
    return json.loads(json.dumps(value, allow_nan=False))


class DrillController:
    """One drill session. Every action returns the effects the UI must run."""

    def __init__(
        self,
        state: SessionState,
        sources: Sequence[SourceRef],
        settings: ControllerSettings,
        persist: Callable[[dict[str, Any]], None],
        now_ms: Callable[[], int],
        *,
        on_finish: Callable[[DrillController, bool], None] | None = None,
        collisions: int = 0,
        active_ms: int = 0,
        active_ms_by_item: dict[int, int] | None = None,
    ) -> None:
        """``state`` comes from ``init_session`` (a new or resumed session).

        ``on_finish(controller, complete)`` ports SessionView's ``finishSession`` /
        ``onFinishSession``: called once, when the Final check completes
        (``complete`` True) or on Save and stop / End session (False). Its state
        is ``controller.state``.

        Raises ``ValueError`` on a session with no items: the engine's empty-deck
        path enters the Final check with no current card and never completes.
        """
        if not state["items"]:
            raise ValueError("a drill session needs at least one card")
        ids = [i["id"] for i in state["items"]]
        if any(not 0 <= i < len(sources) for i in ids):
            raise ValueError("every item id must index into sources")
        self._state: SessionState = state
        self._sources: list[SourceRef] = list(sources)
        self.settings = settings
        self._persist_cb = persist
        self._now_ms = now_ms
        self._on_finish = on_finish
        self.collisions = collisions
        self._active_ms = active_ms
        self._active_by_item: dict[int, int] = dict(active_ms_by_item or {})
        self._last_action_ms: int | None = None  # None: the clock isn't running

        # SessionView's useState / useRef fields.
        self._revealed = False  # userRevealedAnswer
        self._show_next = False  # showNextBtn
        self._feedback: Feedback | None = None
        self._last_verdict: Verdict | None = None  # lastVerdict (C2)
        self._processing = False  # isProcessing
        self._editing = False  # isEditing
        self._edit_reveals_on_close = False  # editRevealsOnClose
        self._pending_dwell_state: SessionState | None = None  # the setTimeout's result.state
        self._pending_advance_state: SessionState | None = None  # pendingAdvanceStateRef
        self._pre_wrong_state: SessionState | None = None  # preWrongStateRef
        self._notice: str | None = None
        self._finished: Literal["complete", "stopped"] | None = None
        self._last_persisted: SessionState | None = None
        self._shown_item: int | None = None  # the card of the last trial on screen

    # -- read-only accessors ------------------------------------------------

    @property
    def state(self) -> SessionState:
        """The committed engine state (SessionView's ``sessionState``)."""
        return self._state

    @property
    def sources(self) -> tuple[SourceRef, ...]:
        return tuple(self._sources)

    @property
    def pre_wrong_state(self) -> SessionState | None:
        return self._pre_wrong_state

    @property
    def pending_advance_state(self) -> SessionState | None:
        return self._pending_advance_state

    @property
    def processing(self) -> bool:
        return self._processing

    @property
    def finished(self) -> Literal["complete", "stopped"] | None:
        return self._finished

    @property
    def active_ms(self) -> int:
        """Active drill time so far (resumed sessions included), in ms."""
        return self._active_ms

    @property
    def active_ms_by_item(self) -> dict[int, int]:
        """Each card's share of :attr:`active_ms`, by item id (cards with none left out)."""
        return dict(self._active_by_item)

    def _tick(self, item_id: int | None) -> None:
        """An action: add the capped gap since the last one, to ``item_id``'s share too."""
        now = self._now_ms()
        if self._last_action_ms is not None:
            gap = max(0, min(now - self._last_action_ms, self.settings.idle_cap_ms))
            self._active_ms += gap
            if item_id is not None and gap:
                self._active_by_item[item_id] = self._active_by_item.get(item_id, 0) + gap
        self._last_action_ms = now

    def _trial_item_id(self) -> int | None:
        trial = self._trial()
        return trial["itemId"] if trial is not None else None

    # -- derived values (SessionView's render-time consts) ------------------

    def _trial(self) -> Trial | None:
        return select_trial(self._state)

    def _item(self, item_id: int) -> DrillItem | None:
        return next((i for i in self._state["items"] if i["id"] == item_id), None)

    def _current_item(self) -> DrillItem | None:
        trial = self._trial()
        return self._item(trial["itemId"]) if trial is not None else None

    def _has_extra(self, item: DrillItem | None) -> bool:
        if item is None:
            return False
        if item.get("extra"):
            return True
        return bool(_IMG_RE.search(self._sources[item["id"]].extra_html))

    def _shows_full_back(self) -> bool:
        # SessionView's showsFullBack, exactly.
        trial = self._trial()
        if trial is None:
            return False
        if trial["stage"] in ("full", "cycle", "final"):
            return True
        item = self._current_item()
        if trial["stage"] != "combine" or item is None:
            return False
        seq = item["combineSeq"]
        return seq is not None and item["combineSeqIdx"] == len(seq) - 1

    def _should_pause_for_extra(self) -> bool:
        # shouldPauseForExtra
        return self._shows_full_back() and self._has_extra(self._current_item())

    def _is_presentation(self) -> bool:
        trial = self._trial()
        return trial is not None and trial["cue"]["kind"] == "present" and not self._revealed

    def _can_override(self) -> bool:
        # canOverride, plus handleOverride's own `!pre` guard.
        return self._last_verdict == "wrong" and self._pre_wrong_state is not None

    def _can_edit(self) -> bool:
        # canEdit
        return (
            self._trial() is not None
            and not self._processing
            and not self._editing
            and self._pending_advance_state is None
            and self._state["phase"] != "final"
            and self._finished is None
        )

    def _blocked(self) -> bool:
        """The busy guard (B5) plus a finished session."""
        return self._processing or self._finished is not None

    # -- persistence and completion -----------------------------------------

    def saved_dict(self, state: SessionState | None = None) -> dict[str, Any]:
        """SessionView's ``persistState`` shape, JSON-clean, plus the controller's
        part of the ``addon`` block (``sessions.py`` adds the rest)."""
        s = self._state if state is None else state
        config = s["config"]
        saved: dict[str, Any] = {
            "deckName": self.settings.deck_name,
            "phase": s["phase"],
            "queue": s["queue"],
            "stats": s["stats"],
            "items": s["items"],
            "encodeReps": config["encodeReps"],
            "chunkDifficulty": config.get("chunkDifficulty"),
            "stemTolerance": config.get("stemTolerance"),
            "ladderMode": config.get("ladderMode"),
            "strictPunctuation": config.get("strictPunctuation"),
            "cycleOrder": config.get("cycleOrder"),
            # Add-on extension; absent (None, dropped below) unless the session set it.
            "minWordsToChunk": config.get("minWordsToChunk"),
            "batchIndex": s["batchIndex"],
            "batchSize": config.get("batchSize"),
            "batchStartStats": s["batchStartStats"],
            "finalCheckStartAttempts": s.get("finalCheckStartAttempts"),
            "currentId": s["currentId"],
            "sourceDeckEditable": self.settings.source_deck_editable,
            "timestamp": self._now_ms(),
        }
        out: dict[str, Any] = _json_copy({k: v for k, v in saved.items() if v is not None})
        out["addon"] = {
            "sources": [source_to_json(src) for src in self._sources],
            "collisions": self.collisions,
            "activeMs": self._active_ms,
            "activeMsByItem": {str(k): v for k, v in sorted(self._active_by_item.items())},
        }
        return out

    def _persist(self, state: SessionState, effects: list[Effect]) -> None:
        # persistState
        self._last_persisted = state
        try:
            self._persist_cb(self.saved_dict(state))
        except Exception as exc:  # a failed save must not stop the drill
            log.exception("Recall Drill: saving the session failed")
            effects.append(PersistFailed(str(exc)))
            return
        effects.append(Persisted())

    def _set_state(self, state: SessionState, effects: list[Effect]) -> None:
        """``setSessionState``, with the persist and completion effects that hang off it."""
        self._state = state
        if state is not self._last_persisted:
            self._persist(state, effects)
        self._check_complete(effects)
        self._track_trial(effects)

    def _track_trial(self, effects: list[Effect]) -> None:
        """StopAudio / PlayQuestionAudio when the trial on screen is another card's."""
        trial = self._trial()
        if trial is None or self._finished is not None:
            return
        item = trial["itemId"]
        if item == self._shown_item:
            return
        first = self._shown_item is None
        self._shown_item = item
        if not first:
            effects.append(StopAudio())
        if self.settings.autoplay_question_audio:
            effects.append(PlayQuestionAudio(self._sources[item].cid))

    def _check_complete(self, effects: list[Effect]) -> None:
        # The useEffect on [currentId, phase]: SESSION_COMPLETE_ID outside the
        # interstitial means the Final check is done.
        s = self._state
        if (
            self._finished is None
            and s["phase"] != "batch-done"
            and s["currentId"] == SESSION_COMPLETE_ID
            and s["items"]
        ):
            self._finished = "complete"
            effects.append(SessionComplete())
            if self._on_finish is not None:
                self._on_finish(self, True)

    def _audio_effect(self, effects: list[Effect]) -> None:
        if not self.settings.play_audio_on_feedback or self._feedback is None:
            return
        if not self._shows_full_back():
            return
        trial = self._trial()
        assert trial is not None  # _shows_full_back() implies a trial
        src = self._sources[trial["itemId"]]
        if src.has_audio:
            effects.append(PlayAnswerAudio(src.cid))

    def _clear_trial_ui(self, effects: list[Effect]) -> None:
        # setTypedValue(''), setUserRevealedAnswer(false), setFeedback(null),
        # setLastVerdict(null)
        effects.append(ClearInput())
        self._revealed = False
        self._feedback = None
        self._last_verdict = None

    # -- actions ------------------------------------------------------------

    def start(self) -> list[Effect]:
        """SessionView's mount: persists the initial state (and finishes a session
        that is already complete)."""
        effects: list[Effect] = []
        if self._finished is None:
            self._last_action_ms = self._now_ms()  # the window is up: the clock runs
            self._persist(self._state, effects)
            self._check_complete(effects)
            self._track_trial(effects)
        return effects

    def reveal(self) -> list[Effect]:
        # handleShowAnswer, under the Esc / Show target conditions.
        if (
            self._blocked()
            or self._editing
            or self._show_next
            or self._revealed
            or self._trial() is None
            or self._is_presentation()
        ):
            return []
        self._tick(self._trial_item_id())
        self._revealed = True
        self._notice = None
        return []

    def submit(self, typed: str) -> list[Effect]:
        # handleCheck
        trial = self._trial()
        if self._blocked() or self._editing or self._show_next or trial is None:
            return []
        self._tick(trial["itemId"])
        effects: list[Effect] = []
        # C8b: the input is read-only on a presentation beat, so nothing was typed.
        if self._is_presentation():
            typed = ""

        # The "other card's answer" catch: before the engine, and nothing changes.
        if self.settings.collision_catch and trial["stage"] in _WHOLE_ANSWER_STAGES:
            other = self._colliding_answer(typed, trial)
            if other is not None:
                self.collisions += 1
                self._notice = COLLISION_MESSAGE
                return [CollisionNotice(other), ClearInput()]

        self._notice = None
        self._processing = True
        pause_for_extra = self._should_pause_for_extra()  # this render's value
        pre = self._state
        result = apply_answer(pre, typed, revealed=self._revealed)
        self._pre_wrong_state = pre if result["verdict"] == "wrong" else None
        self._feedback = result["feedback"]
        self._last_verdict = result["verdict"]
        # C8b: acknowledging a presentation is neither a success nor a failure.
        if result["verdict"] != "presented":
            effects.append(Flash(result["verdict"] in ("exact", "near")))
        self._persist(result["state"], effects)
        self._after_answer(result["state"], result["advance"], pause_for_extra, effects)
        return effects

    def _colliding_answer(self, typed: str, trial: Trial) -> str | None:
        strict = self._state["config"].get("strictPunctuation") or False
        if exact_match(typed, trial["target"], strict):
            return None
        src = self._sources[trial["itemId"]]
        for answer in src.colliding_answers:
            if exact_match(typed, answer, strict):
                return answer
        return None

    def _after_answer(
        self,
        new_state: SessionState,
        advance: Literal["auto", "manual"],
        pause_for_extra: bool,
        effects: list[Effect],
    ) -> None:
        """The three branches shared by handleCheck and handleOverride."""
        if advance == "auto" and not pause_for_extra:
            assert self._feedback is not None
            self._pending_dwell_state = new_state
            self._audio_effect(effects)
            effects.append(StartDwell(DWELL_MS.get(self._feedback["dwellKey"], 0)))
        elif advance == "auto":
            # Would have auto-advanced, but the Extra is showing: hold the
            # already-advanced state until Continue.
            self._pending_advance_state = new_state
            self._show_next = True
            self._processing = False
            self._audio_effect(effects)
        else:
            self._show_next = True
            self._processing = False
            self._set_state(new_state, effects)
            self._audio_effect(effects)

    def dwell_elapsed(self) -> list[Effect]:
        # The setTimeout bodies in handleCheck / handleOverride.
        pending = self._pending_dwell_state
        if pending is None:
            return []
        effects: list[Effect] = []
        self._pending_dwell_state = None
        self._clear_trial_ui(effects)
        self._show_next = False  # see the module docstring (handleOverride)
        self._processing = False
        self._set_state(pending, effects)
        return effects

    def override(self) -> list[Effect]:
        # handleOverride ("Count as correct")
        pre = self._pre_wrong_state
        if self._blocked() or self._editing or not self._can_override() or pre is None:
            return []
        pre_trial = select_trial(pre)
        if pre_trial is None:
            return []
        self._tick(pre_trial["itemId"])
        effects: list[Effect] = []
        self._processing = True
        self._pre_wrong_state = None
        pause_for_extra = self._should_pause_for_extra()
        # The trial that was answered, on the pre-answer snapshot.
        result = apply_answer(pre, pre_trial["target"], revealed=False, override=True)
        self._feedback = result["feedback"]
        self._last_verdict = result["verdict"]
        effects.append(Flash(True))
        self._persist(result["state"], effects)
        self._after_answer(result["state"], result["advance"], pause_for_extra, effects)
        return effects

    def continue_(self) -> list[Effect]:
        # handleNext (B5: guarded against a double Enter)
        if self._blocked() or self._editing or not self._show_next:
            return []
        self._tick(self._trial_item_id())
        effects: list[Effect] = []
        self._processing = True
        self._show_next = False
        self._pre_wrong_state = None
        self._notice = None
        if self._pending_advance_state is not None:
            # The Extra-pause case: the held, already-advanced state.
            pending = self._pending_advance_state
            self._pending_advance_state = None
            self._clear_trial_ui(effects)
            self._processing = False
            self._set_state(pending, effects)
            return effects
        self._clear_trial_ui(effects)
        self._processing = False
        if self._state["phase"] in ("cycle", "final"):
            # Only the cycle and Final check advance with applyNext.
            self._set_state(apply_next(self._state), effects)
        return effects

    def next_batch(self) -> list[Effect]:
        # handleNextBatch
        if self._blocked() or self._state["phase"] != "batch-done":
            return []
        self._tick(None)
        effects: list[Effect] = []
        self._show_next = False
        self._notice = None
        self._clear_trial_ui(effects)
        self._set_state(advance_to_next_batch(self._state), effects)
        return effects

    def save_and_stop(self) -> list[Effect]:
        # "Save and stop" on the interstitial and "End session": finishSession,
        # then App.handleFinishSession's save of the state as it stands.
        if self._blocked():
            return []
        self._last_action_ms = None  # a gap across Save and stop never counts
        effects: list[Effect] = []
        self._persist(self._state, effects)
        self._finished = "stopped"
        self._editing = False
        effects.append(SessionStopped())
        if self._on_finish is not None:
            self._on_finish(self, False)
        return effects

    # -- editing (Anki's Browser) -------------------------------------------

    def begin_edit(self) -> EditRequest | None:
        # handleOpenEditor
        if not self._can_edit():
            return None
        item = self._item(self._state["currentId"])
        if item is None:
            return None
        self._edit_reveals_on_close = (
            not self._is_presentation()
            and not self._show_next
            and self._last_verdict is None
            and not self._revealed
        )
        self._editing = True
        return EditRequest(
            cid=self._sources[item["id"]].cid,
            item_id=item["id"],
            front=item["front"],
            back=item["back"],
            extra=item.get("extra", ""),
        )

    def _close_editor(self, restarted: bool) -> None:
        # closeEditor: seeing the full answer and then typing it is copy-typing,
        # so an attempt that was pending when the editor opened counts as revealed.
        if self._edit_reveals_on_close and not restarted:
            self._revealed = True
        self._editing = False

    def cancel_edit(self) -> list[Effect]:
        # The editor's Cancel / Esc: closeEditor(false).
        if not self._editing:
            return []
        self._close_editor(False)
        return []

    def apply_card_edit(
        self, front: str, back: str, extra: str, source: SourceRef | None = None
    ) -> list[Effect]:
        """handleSaveEdit with the card as Anki now has it (``source``: its rebuilt
        :class:`SourceRef`, kept for display and later resume checks)."""
        if not self._editing:
            return []
        # canSaveEdit: an empty front or answer can't be saved, so it's a cancel.
        if not js_trim(front) or not js_trim(back):
            return self.cancel_edit()
        before = self._item(self._state["currentId"])
        if before is None:
            return self.cancel_edit()
        effects: list[Effect] = []
        if source is not None:
            self._sources[before["id"]] = source
        result = edit_current_item(self._state, {"front": front, "back": back, "extra": extra})
        restarted = result["restarted"]
        if restarted:
            self._show_next = False
            self._clear_trial_ui(effects)
        # A pending "Count as correct" must credit the edited card, not undo the
        # edit (a restart already cleared lastVerdict: nothing left to offer).
        if self._pre_wrong_state is not None:
            self._pre_wrong_state = (
                None
                if restarted
                else edit_current_item(
                    self._pre_wrong_state, {"front": front, "back": back, "extra": extra}
                )["state"]
            )
        if result["state"] is not self._state:
            self._set_state(result["state"], effects)  # saves the new source too
        self._close_editor(restarted)
        return effects

    # -- the view -----------------------------------------------------------

    def view(self) -> ViewModel:
        s = self._state
        items = s["items"]
        trial = self._trial()
        item = self._current_item()
        src = self._sources[trial["itemId"]] if trial is not None else None
        revealed = self._revealed
        presentation = self._is_presentation()

        cue = CueView("none", "")
        sub_text = ""
        placeholder = ""
        if trial is not None:
            engine_cue = trial["cue"]
            if engine_cue["kind"] == "firstLetter":
                cue = CueView("firstLetter", engine_cue["pattern"])
            elif engine_cue["kind"] == "present":
                cue = CueView("present", trial["target"])
            if revealed:
                sub_text = trial["target"]
                placeholder = trial["target"]
            elif cue.kind == "present":
                sub_text = trial["target"]
                placeholder = "Press Enter to continue"
            elif cue.kind == "firstLetter":
                sub_text = cue.text
                placeholder = cue.text
            else:
                placeholder = BLIND_PLACEHOLDER.get(trial["stage"], "Type from memory...")

        cue_badge = ""
        if presentation:
            cue_badge = "Read & Continue"
        elif not revealed and cue.kind == "firstLetter":
            cue_badge = "First-Letter Cue"
        elif not revealed and cue.kind == "none" and trial is not None:
            cue_badge = "Blind Recall"

        shows_full_back = self._shows_full_back()
        extra: str | None = None
        extra_html: str | None = None
        if self._feedback is not None and shows_full_back and self._has_extra(item):
            assert item is not None and src is not None
            extra = item.get("extra", "")
            extra_html = src.extra_html
        answer_html: str | None = None
        if self._feedback is not None and shows_full_back and src is not None and src.image_front:
            answer_html = answer_side(src.front_html, src.answer_html)

        feedback = None
        if self._feedback is not None:
            diff = self._feedback.get("diff")
            feedback = FeedbackView(
                self._feedback["text"],
                self._feedback["type"],
                tuple(diff) if diff is not None else None,
                self._last_verdict,
            )

        batch = compute_batch_summary(s)
        is_batched = batch["totalBatches"] > 1
        if s["phase"] == "batch-done":
            detail = f"Batch {batch['batchNumber']} of {batch['totalBatches']} complete"
        else:
            detail = trial["detail"] if trial is not None else ""
        batch_label = (
            f"Batch {batch['batchNumber']}/{batch['totalBatches']}"
            if is_batched and s["phase"] != "batch-done"
            else ""
        )

        if self._finished is not None:
            mode: Mode = "done"
        elif s["phase"] == "batch-done":
            mode = "batch_done"
        elif self._feedback is not None:
            mode = "feedback"
        else:
            mode = "trial"

        busy = self._blocked()
        buttons = Buttons(
            check=trial is not None and not busy and not self._editing and not self._show_next,
            reveal=(
                trial is not None
                and not busy
                and not self._editing
                and not revealed
                and not self._show_next
                and not presentation
            ),
            override=not busy and not self._editing and self._can_override(),
            continue_=not busy and not self._editing and self._show_next,
            edit=self._can_edit(),
            next_batch=not busy and s["phase"] == "batch-done",
            save=not busy,
        )

        batch_done = None
        if s["phase"] == "batch-done":
            remaining = self._remaining_text()
            batch_done = BatchDoneView(
                batch["batchNumber"],
                batch["totalBatches"],
                batch["itemsMastered"],
                batch["batchSize"],
                batch["trialsSpent"],
                batch["accuracyPercent"],
                remaining,
            )

        return ViewModel(
            mode=mode,
            item_id=trial["itemId"] if trial is not None else None,
            cid=src.cid if src is not None else None,
            prompt=trial["prompt"] if trial is not None else "",
            front_html=src.front_html if src is not None else "",
            hint=src.hint if src is not None else "",
            card_ord=src.ord if src is not None else 0,
            css=src.css if src is not None else "",
            label=trial["label"] if trial is not None else "",
            detail=detail,
            batch_label=batch_label,
            cue=cue,
            cue_badge=cue_badge,
            sub_text=sub_text,
            blind_hint=(
                BLIND_HINT
                if trial is not None and not sub_text and not revealed and cue.kind == "none"
                else ""
            ),
            placeholder=placeholder,
            input_read_only=presentation,
            check_label="Continue" if presentation else "Check answer",
            revealed=revealed,
            feedback=feedback,
            shows_full_back=shows_full_back,
            extra=extra,
            extra_html=extra_html,
            image_front=src.image_front if src is not None else False,
            answer_html=answer_html,
            audio_side="a" if self._feedback is not None and shows_full_back else "q",
            notice=self._notice,
            editing=self._editing,
            processing=self._processing,
            buttons=buttons,
            stats=self._stats_line(),
            progress=self._progress(items, batch["batchNumber"], batch["totalBatches"]),
            batch_done=batch_done,
            dots=tuple(
                Dot(
                    it["id"],
                    it["status"],
                    trial is not None and it["id"] == trial["itemId"],
                    f"{it['front']}: {it['status']}",
                )
                for it in items
            ),
        )

    def _remaining_text(self) -> str | None:
        """The interstitial's remaining time, from this session's own pace: active
        time per card in the batches done so far, times the cards in the batches
        after this one (Phase 6; no fixed typing-speed constants)."""
        s = self._state
        items = s["items"]
        size = s["config"].get("batchSize")
        batches = partition_into_batches(items, len(items) if size is None else size)
        done = sum(len(b) for b in batches[: s["batchIndex"] + 1])
        later = sum(len(b) for b in batches[s["batchIndex"] + 1 :])
        if self._active_ms <= 0 or done <= 0 or later <= 0:
            return None
        seconds = self._active_ms / 1000 / done * later
        return f"Remaining time at your pace in this session: {minutes_text(seconds)}"

    def _stats_line(self) -> StatsLine:
        st = self._state["stats"]
        reveals = st.get("reveals", 0)
        text = f"Attempts: {st['attempts']} • Misses: {st['misses']}"
        if st["nearMisses"] > 0:
            text += f" • Near: {st['nearMisses']}"
        if st["overrides"] > 0:
            text += f" • Overrides: {st['overrides']}"
        if reveals > 0:
            text += f" • Reveals: {reveals}"
        return StatsLine(
            st["attempts"],
            st["misses"],
            st["nearMisses"],
            reveals,
            st["overrides"],
            compute_accuracy_percent(st),
            text,
        )

    def _progress(
        self, items: Sequence[DrillItem], batch_number: int, total_batches: int
    ) -> ProgressView:
        s = self._state
        size = s["config"].get("batchSize")
        batches = partition_into_batches(items, len(items) if size is None else size)
        idx = s["batchIndex"]
        current = batches[idx] if 0 <= idx < len(batches) else list(items)
        p = compute_session_progress(items, s["config"]["encodeReps"], current)

        def count(status: str) -> int:
            return len([i for i in items if i["status"] == status])

        mastered = count("mastered")
        return ProgressView(
            total=len(items),
            mastered=mastered,
            ready=count("ready"),
            encoding=count("encoding"),
            new=count("new"),
            mastered_percent=js_round(mastered / len(items) * 100) if items else 0,
            batch_encoded_percent=js_round(p["batchFraction"] * 100),
            deck_encoded_percent=js_round(p["deckFraction"] * 100),
            batch_number=batch_number,
            total_batches=total_batches,
            is_batched=total_batches > 1,
        )

    # -- the done screen ----------------------------------------------------

    def done_summary(self) -> DoneSummary:
        """DoneView, for the state the session finished (or stopped) on."""
        s = self._state
        items = s["items"]
        stats = s["stats"]
        mastered = len([i for i in items if i["status"] == "mastered"])
        missed = [i for i in items if i.get("finalMisses", 0) > 0]
        is_complete = bool(items) and all(i.get("finalDone") for i in items)
        reveals = stats.get("reveals", 0)
        misses = stats["misses"]

        line = (
            f"{misses} miss{_plural(misses, '', 'es')} • "
            f"{reveals} reveal{_plural(reveals, '', 's')}"
        )
        if stats["nearMisses"] > 0:
            line += f" • {stats['nearMisses']} near"
        if stats["overrides"] > 0:
            line += f" • {stats['overrides']} override{_plural(stats['overrides'], '', 's')}"
        if reveals > 0:
            line += " — answers typed after a reveal don’t count toward accuracy"

        hardest: list[HardCard] = []
        for it in rank_hardest_cards(items):
            parts: list[str] = []
            m, r, f = it.get("misses", 0), it.get("reveals", 0), it.get("finalMisses", 0)
            if m > 0:
                parts.append(f"{m} miss{_plural(m, '', 'es')}")
            if r > 0:
                parts.append(f"{r} reveal{_plural(r, '', 's')}")
            if f > 0:
                parts.append(f"{f} in final check")
            parts.append(f"{it.get('attempts', 0)} tries")
            hardest.append(
                HardCard(
                    it["id"],
                    self._sources[it["id"]].cid,
                    it["front"],
                    it["back"],
                    it.get("attempts", 0),
                    " • ".join(parts),
                    tuple(it.get("hardSpans", [])),
                )
            )

        if is_complete:
            summary = (
                f"Terrific work! All {len(items)} items were successfully encoded and "
                "verified through spaced retrieval."
            )
        else:
            summary = (
                f"{mastered} of {len(items)} items mastered so far ({misses} misses). "
                "You can resume this session from the deck's Recall Drill panel."
            )
        n_missed = len(missed)
        return DoneSummary(
            is_complete=is_complete,
            title="Deck Mastered!" if is_complete else "Session Saved",
            deck_name=self.settings.deck_name,
            mastered=mastered,
            total=len(items),
            attempts=stats["attempts"],
            accuracy_percent=compute_accuracy_percent(stats),
            accuracy_line=line,
            summary=summary,
            hardest=tuple(hardest),
            missed_in_final=tuple(
                FinalMiss(
                    i["id"],
                    self._sources[i["id"]].cid,
                    i["front"],
                    i["back"],
                    i.get("finalMisses", 0),
                )
                for i in missed
            ),
            drill_again=tuple(i["id"] for i in missed) if is_complete else (),
            drill_again_label=(
                "Drill this card again" if n_missed == 1 else f"Drill these {n_missed} cards again"
            ),
        )

    def drill_again_input(self) -> tuple[list[DeckItem], list[SourceRef]]:
        """DoneView's ``onDrillAgain`` cards (front, back, extra) and their sources."""
        ids = self.done_summary().drill_again
        deck: list[DeckItem] = []
        sources: list[SourceRef] = []
        for item_id in ids:
            it = self._item(item_id)
            assert it is not None
            card: DeckItem = {"front": it["front"], "back": it["back"]}
            if "extra" in it:
                card["extra"] = it["extra"]
            deck.append(card)
            sources.append(self._sources[item_id])
        return deck, sources

    def drill_again_overrides(self) -> list[ItemOverrides]:
        """The per-card overrides of :meth:`drill_again_input`'s cards, in the same
        order: the same Anki cards keep their reps and chunk threshold."""
        out: list[ItemOverrides] = []
        for item_id in self.done_summary().drill_again:
            it = self._item(item_id)
            assert it is not None
            out.append(item_overrides(it))
        return out
