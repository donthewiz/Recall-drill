"""Per-note learn progress (``progress.json``; pure).

For every Math Path note (by note id): the stage it has reached, the faded level, how many tries
that level has used, the unaided solo count and when it was last seen. A closed window resumes at
the same stage with a fresh problem. Anki owns scheduling; this file only remembers where the
learner is in the learn session.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any, cast

from .storage import PROGRESS, Storage

STUDY = "study"
FADED = "faded"
PLAN = "plan"
SOLO = "solo"
LEARNED = "learned"
STAGES: tuple[str, ...] = (STUDY, FADED, PLAN, SOLO, LEARNED)

STAGE_LABELS: dict[str, str] = {
    STUDY: "Study",
    FADED: "Faded",
    PLAN: "Plan",
    SOLO: "Solo",
    LEARNED: "Learned",
}

MAX_FADED_TRIES = 3
"""After this many tries at a faded level the recipe moves on and is marked "needed help"."""
SOLOS_TO_LEARN = 2
"""Unaided right solos (with another problem between them) that make a recipe Learned."""


@dataclass
class NoteProgress:
    stage: str = STUDY
    faded_level: int = 1
    faded_tries: int = 0
    """Finished problems at the current faded level that needed help or had a wrong answer."""
    solo_clean: int = 0
    """Unaided right solos so far (0, 1; 2 means Learned)."""
    needed_help: bool = False
    """Moved on after three tries at a faded level."""
    handed_off: bool = False
    """The handoff to Anki ran for this note."""
    last_seen: str = ""

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, raw: object) -> NoteProgress:
        """Decode, taking the default for anything missing or mistyped (a hand-edited file)."""
        d: Mapping[str, Any] = cast(Mapping[str, Any], raw) if isinstance(raw, dict) else {}
        base = cls()

        def num(key: str, low: int, high: int, default: int) -> int:
            v = d.get(key)
            return (
                max(low, min(high, v))
                if isinstance(v, int) and not isinstance(v, bool)
                else default
            )

        def flag(key: str) -> bool:
            v = d.get(key)
            return v if isinstance(v, bool) else False

        stage = d.get("stage")
        return cls(
            stage=stage if isinstance(stage, str) and stage in STAGES else base.stage,
            faded_level=num("faded_level", 1, 2, 1),
            faded_tries=num("faded_tries", 0, MAX_FADED_TRIES, 0),
            solo_clean=num("solo_clean", 0, SOLOS_TO_LEARN, 0),
            needed_help=flag("needed_help"),
            handed_off=flag("handed_off"),
            last_seen=d["last_seen"] if isinstance(d.get("last_seen"), str) else "",
        )

    @property
    def is_learned(self) -> bool:
        return self.stage == LEARNED


class ProgressStore:
    """``progress.json`` for one profile: read once, written atomically after every change."""

    def __init__(self, storage: Storage) -> None:
        self.storage = storage
        raw: Any = storage.read_json(PROGRESS, {})
        notes: Any = cast(Mapping[str, Any], raw).get("notes") if isinstance(raw, dict) else None
        self._notes: dict[int, NoteProgress] = {}
        saved: dict[str, Any] = cast(dict[str, Any], notes) if isinstance(notes, dict) else {}
        for key, value in saved.items():
            try:
                self._notes[int(key)] = NoteProgress.from_json(value)
            except ValueError:
                continue

    def get(self, nid: int) -> NoteProgress:
        """The note's progress (a fresh one when it has none; not stored until :meth:`put`)."""
        have = self._notes.get(nid)
        return NoteProgress(**have.to_json()) if have is not None else NoteProgress()

    def has(self, nid: int) -> bool:
        return nid in self._notes

    def put(self, nid: int, progress: NoteProgress) -> None:
        self._notes[nid] = NoteProgress(**progress.to_json())
        self.save()

    def forget(self, nid: int) -> None:
        if self._notes.pop(nid, None) is not None:
            self.save()

    def save(self) -> None:
        self.storage.write_json(
            PROGRESS, {"notes": {str(n): p.to_json() for n, p in sorted(self._notes.items())}}
        )

    def all(self) -> dict[int, NoteProgress]:
        return {n: NoteProgress(**p.to_json()) for n, p in self._notes.items()}
