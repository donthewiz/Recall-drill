"""Engine state types: ``TypedDict`` mirrors of ``src/types.ts``.

Keys are the TS camelCase names, so engine state is plain dicts and lists that
serialize to the same JSON values the web app writes.

Representation rule:

- TS ``undefined`` (an optional field that isn't set) means the key is absent.
- TS ``null`` means ``None``.
- An optional field is never stored as ``None``. Where TS spreads an object
  with an undefined field, the Python result has no such key at all.
"""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

ItemStatus = Literal["new", "encoding", "ready", "mastered"]
EncodeStage = Literal["chunks", "combine", "remediate", "full"]
LadderMode = Literal["cumulative", "exhaustive"]
CycleOrder = Literal["shuffled", "inOrder"]
SessionPhase = Literal["encode", "cycle", "batch-done", "final"]
Verdict = Literal["exact", "near", "wrong", "revealed", "presented"]


class RemediateItem(TypedDict):
    text: str
    streak: int
    missCount: int


class CombineSequenceItem(TypedDict):
    start: int
    end: int


class DrillItem(TypedDict):
    id: int
    front: str
    back: str
    extra: NotRequired[str]
    status: ItemStatus
    encodeStreak: int
    cycleStreak: int
    chunks: list[str] | None
    chunkIndex: int
    chunkStreak: int
    combineSeq: list[CombineSequenceItem] | None
    combineSeqIdx: int
    combineStreak: int
    combineMissCount: int
    remediateStack: list[RemediateItem]
    remediateQueue: list[str]
    remediateReturnSeqIdx: int
    stage: EncodeStage
    finalDone: NotRequired[bool]
    finalMisses: NotRequired[int]
    attempts: NotRequired[int]
    misses: NotRequired[int]
    reveals: NotRequired[int]
    nearMisses: NotRequired[int]
    hardSpans: NotRequired[list[str]]
    encodeRepsOverride: NotRequired[int]
    """Add-on only (docs/DECISIONS.md, "Engine extensions"): this card's
    ``encodeReps``, in place of the session's (``items.reps_for``). Absent:
    the session's, exactly as the TS engine."""
    minWordsToChunkOverride: NotRequired[int]
    """Add-on only: this card's ``MIN_WORDS_TO_CHUNK``, in place of the session's
    (``build_item`` and ``edit_current_item``). Absent: the session's."""


class ItemOverrides(TypedDict, total=False):
    """Add-on only: per-card values ``build_items`` stores on each item."""

    encodeRepsOverride: int
    minWordsToChunkOverride: int


class SessionStats(TypedDict):
    attempts: int
    misses: int
    nearMisses: int
    overrides: int
    reveals: NotRequired[int]
    startTime: NotRequired[int]


class WordDiffResult(TypedDict):
    word: str
    matched: bool


class GradeResult(TypedDict):
    verdict: Literal["exact", "near", "wrong"]
    diff: list[WordDiffResult]
    missingWords: list[str]
    extraWords: list[str]
    similarity: float


class DeckItem(TypedDict):
    front: str
    back: str
    extra: NotRequired[str]


class SavedSessionState(TypedDict):
    deckName: str
    phase: SessionPhase
    queue: list[int]
    stats: SessionStats
    items: list[DrillItem]
    encodeReps: int
    chunkDifficulty: NotRequired[float]
    stemTolerance: NotRequired[bool]
    ladderMode: NotRequired[LadderMode]
    cycleOrder: NotRequired[CycleOrder]
    strictPunctuation: NotRequired[bool]
    batchIndex: NotRequired[int]
    batchSize: NotRequired[int]
    batchStartStats: NotRequired[SessionStats]
    finalCheckStartAttempts: NotRequired[int]
    sourceDeckEditable: NotRequired[bool]
    currentId: NotRequired[int]
    timestamp: NotRequired[int]


class SessionConfig(TypedDict):
    encodeReps: int
    chunkDifficulty: float
    stemTolerance: bool
    ladderMode: LadderMode
    batchSize: NotRequired[int]
    cycleOrder: NotRequired[CycleOrder]
    strictPunctuation: NotRequired[bool]
    minWordsToChunk: NotRequired[int]
    """Add-on only (docs/DECISIONS.md, "Engine extensions beyond the TS engine"):
    the session's ``MIN_WORDS_TO_CHUNK``. Absent: the module constant, exactly as
    the TS engine."""


class SessionState(TypedDict):
    items: list[DrillItem]
    phase: SessionPhase
    queue: list[int]
    stats: SessionStats
    currentId: int
    batchIndex: int
    batchStartStats: SessionStats
    finalCheckStartAttempts: NotRequired[int]
    config: SessionConfig


class NoCue(TypedDict):
    kind: Literal["none"]


class FirstLetterCue(TypedDict):
    kind: Literal["firstLetter"]
    pattern: str


class FullCue(TypedDict):
    kind: Literal["full"]
    text: str


class ChoiceCue(TypedDict):
    kind: Literal["choice"]
    options: list[str]


class PresentCue(TypedDict):
    kind: Literal["present"]


Cue = NoCue | FirstLetterCue | FullCue | ChoiceCue | PresentCue


class Feedback(TypedDict):
    text: str
    type: Literal["success", "danger", "info"]
    diff: NotRequired[list[WordDiffResult]]
    dwellKey: str


class Trial(TypedDict):
    itemId: int
    stage: EncodeStage | Literal["cycle", "final"]
    prompt: str
    target: str
    cue: Cue
    label: str
    detail: str
