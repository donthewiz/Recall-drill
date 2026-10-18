"""A course as the progress map and "Learn next" see it (pure).

A **course** is a top deck that contains Math Path notes. Its **sections** are the decks under it
that hold Math Path notes or whose name starts with a section number (``3.2 Quadratic …``); they
come in textbook order (a natural sort of the deck names: ``Ch 03 …`` before ``Ch 10 …``, ``3.2``
before ``3.10``). Each recipe note is a chip with its stage; NEXT is the first section with a
recipe that can be learned now.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from .config import Config
from .notes import RecipeNote
from .progress import LEARNED, STAGE_LABELS, NoteProgress
from .session import is_learned, learn_order, locked_by, pick_for_session


def natural_key(name: str) -> list[tuple[int, int, str]]:
    """A sort key that compares digit runs as numbers (``3.2`` < ``3.10``), case-insensitively."""
    parts = re.split(r"(\d+)", name.casefold())
    return [(0, int(p), "") if p.isdigit() else (1, 0, p) for p in parts if p != ""]


@dataclass(frozen=True)
class CardState:
    """What Anki says about a note's card, in words."""

    kind: str
    """new, learning, review, suspended or buried."""
    text: str
    """``"new"``, ``"learning"``, ``"review, due Mon Oct 19"``, ``"suspended"``, ``"buried"``."""


@dataclass(frozen=True)
class SectionData:
    did: int
    name: str
    """The full deck name."""
    label: str
    """The last path component (``3.2 Quadratic Equations, …``)."""
    notes: tuple[RecipeNote, ...]
    recall_total: int
    recall_drilled: int
    """Recall Drill cards in the section (``rd::drill``, ``rd::drilled`` or ``rd::undrilled``) and,
    of them, the ``rd::drilled`` or ``rd::undrilled`` ones. Read only."""
    number: str = ""
    """The section number from the deck name (``3.2``), or ``""``."""


@dataclass(frozen=True)
class CourseData:
    did: int
    name: str
    sections: tuple[SectionData, ...]
    states: Mapping[int, CardState] = field(default_factory=dict[int, CardState])
    """Note id -> its first card's state."""
    notes: tuple[RecipeNote, ...] = ()
    """Every Math Path note of the course (for prerequisites across sections)."""


@dataclass(frozen=True)
class ChipModel:
    nid: int
    title: str
    stage: str
    """Locked, Study, Faded, Plan, Solo, Learned, In Anki or Unreadable."""
    detail: str = ""
    """What a Locked chip needs ("needs Solve by factoring"), or Anki's state for In Anki."""
    kind: str = "learning"
    """locked, learning, learned (in Anki or ready to hand off), broken."""
    learnable: bool = False


@dataclass(frozen=True)
class RowModel:
    section: SectionData
    chips: tuple[ChipModel, ...]
    is_next: bool
    can_learn: bool
    """There is something to learn in this row (an unlocked recipe that isn't learned)."""
    recall_warning: str = ""
    """The amber line before Learn; ``""`` when every Recall card is drilled (or there are none)."""

    @property
    def recall_cell(self) -> str:
        return (
            f"{self.section.recall_drilled} / {self.section.recall_total}"
            if self.section.recall_total
            else "—"
        )


@dataclass(frozen=True)
class MapModel:
    course: CourseData
    rows: tuple[RowModel, ...]

    @property
    def next_row(self) -> RowModel | None:
        return next((r for r in self.rows if r.is_next), None)


def chip_for(
    note: RecipeNote,
    course: CourseData,
    progress: Mapping[int, NoteProgress],
    cfg: Config,
) -> ChipModel:
    title = note.title or note.recipe_id
    if note.recipe is None:
        return ChipModel(note.nid, title, "Unreadable", note.error, "broken")
    have = progress.get(note.nid)
    state = course.states.get(note.nid)
    if is_learned(note, progress):
        handed = note.learned_tag or (have is not None and have.handed_off)
        if handed:
            return ChipModel(note.nid, title, "In Anki", state.text if state else "", "learned")
        return ChipModel(note.nid, title, "Learned", "ready to hand off", "learned")
    needs = locked_by(note, course.notes, progress, cfg)
    if needs:
        return ChipModel(note.nid, title, "Locked", "needs " + ", ".join(needs), "locked")
    stage = have.stage if have is not None else "study"
    label = STAGE_LABELS.get(stage, "Study")
    return ChipModel(note.nid, title, label, "", "learning", learnable=stage != LEARNED)


def build_map(course: CourseData, progress: Mapping[int, NoteProgress], cfg: Config) -> MapModel:
    rows: list[RowModel] = []
    next_taken = False
    for section in course.sections:
        chips = tuple(chip_for(n, course, progress, cfg) for n in learn_order(section.notes))
        can_learn = any(c.learnable for c in chips)
        is_next = can_learn and not next_taken
        next_taken = next_taken or is_next
        warning = ""
        if section.recall_total and section.recall_drilled < section.recall_total:
            where = section.number or section.label
            warning = (
                f"Recall cards for {where}: {section.recall_drilled} / {section.recall_total} "
                "drilled. Drilling them first helps."
            )
        rows.append(RowModel(section, chips, is_next, can_learn, warning))
    return MapModel(course, tuple(rows))


def session_notes(
    section: SectionData,
    course: CourseData,
    progress: Mapping[int, NoteProgress],
    cfg: Config,
) -> list[RecipeNote]:
    """The recipes a learn session on this section takes."""
    return pick_for_session(section.notes, course.notes, progress, cfg)


def next_section(
    course: CourseData, progress: Mapping[int, NoteProgress], cfg: Config
) -> SectionData | None:
    row = build_map(course, progress, cfg).next_row
    return row.section if row is not None else None


def unhanded(notes: Sequence[RecipeNote], progress: Mapping[int, NoteProgress]) -> list[RecipeNote]:
    """Notes that reached Learned in a session but were never handed to Anki (a window closed on
    the handoff, or it failed)."""
    out: list[RecipeNote] = []
    for n in notes:
        have = progress.get(n.nid)
        if have is not None and have.is_learned and not have.handed_off and not n.learned_tag:
            out.append(n)
    return out
