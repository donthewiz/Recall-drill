"""The progress map's state machine (pure). The window carries out what ``command`` returns."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from .config import Config
from .course_model import CourseData, MapModel, RowModel, build_map
from .pages import Command
from .progress import NoteProgress

SELECT_PREFIX = "course"
"""The course list's id (``data-id``)."""

EFFECT_NONE = ""
EFFECT_CLOSE = "close"
EFFECT_IMPORT = "import"
EFFECT_REFRESH = "refresh"
EFFECT_LEARN = "learn"
"""Open a learn session on ``ProgressController.learn_did`` of ``course`` (nothing else asks)."""


@dataclass
class ProgressController:
    courses: list[CourseData]
    progress: Mapping[int, NoteProgress]
    cfg: Config = field(default_factory=Config)
    selected: str = ""
    """The course (top deck name) on screen."""
    confirm: int | None = None
    """The section deck id whose Recall line is asking "Learn anyway / Cancel"."""
    learn_did: int = 0
    """The section the last EFFECT_LEARN is for."""

    def __post_init__(self) -> None:
        if not any(c.name == self.selected for c in self.courses):
            self.selected = self.courses[0].name if self.courses else ""

    # -- the data -------------------------------------------------------------------------

    @property
    def course(self) -> CourseData | None:
        return next((c for c in self.courses if c.name == self.selected), None)

    def model(self) -> MapModel | None:
        course = self.course
        return build_map(course, self.progress, self.cfg) if course is not None else None

    def update(self, courses: list[CourseData], progress: Mapping[int, NoteProgress]) -> None:
        """New data (the collection changed): keep the course and a pending question when they
        still exist."""
        self.courses = courses
        self.progress = progress
        if not any(c.name == self.selected for c in courses):
            self.selected = courses[0].name if courses else ""
        model = self.model()
        if self.confirm is not None and (
            model is None or not any(r.section.did == self.confirm for r in model.rows)
        ):
            self.confirm = None

    def row(self, did: int) -> RowModel | None:
        model = self.model()
        return next((r for r in model.rows if r.section.did == did), None) if model else None

    # -- commands -------------------------------------------------------------------------------

    def command(self, cmd: Command) -> str:
        if cmd.kind == "select" and cmd.a == SELECT_PREFIX:
            if any(c.name == cmd.b for c in self.courses):
                self.selected = cmd.b
                self.confirm = None
            return EFFECT_NONE
        if cmd.kind != "act":
            return EFFECT_NONE
        if cmd.a == "close":
            return EFFECT_CLOSE
        if cmd.a == "import":
            return EFFECT_IMPORT
        if cmd.a == "refresh":
            return EFFECT_REFRESH
        if cmd.a == "cancel":
            self.confirm = None
            return EFFECT_NONE
        if cmd.a == "learn_next":
            model = self.model()
            row = model.next_row if model is not None else None
            return self._learn(row)
        if cmd.a == "learn" and cmd.b.isdigit():
            return self._learn(self.row(int(cmd.b)))
        if cmd.a == "learn_anyway" and cmd.b.isdigit():
            row = self.row(int(cmd.b))
            self.confirm = None
            if row is not None and row.can_learn:
                self.learn_did = row.section.did
                return EFFECT_LEARN
        return EFFECT_NONE

    def _learn(self, row: RowModel | None) -> str:
        """Learn on a row: with Recall cards still undrilled, ask first (a soft warning, never a
        lock); otherwise go."""
        if row is None or not row.can_learn:
            return EFFECT_NONE
        if row.recall_warning:
            self.confirm = row.section.did
            return EFFECT_NONE
        self.confirm = None
        self.learn_did = row.section.did
        return EFFECT_LEARN
