"""Starting a learn session: from a section, or "Learn next" (v0.1)."""

from __future__ import annotations

from aqt import mw
from aqt.utils import tooltip

from ..anki_io import courses
from ..course_model import CourseData, SectionData, next_section, session_notes, unhanded
from ..notes import RecipeNote
from ..progress import ProgressStore
from ..storage import UI_STATE
from .context import AddonContext

COURSE_KEY = "course"
"""Key in ``ui_state.json``: the course (top deck name) the learn and progress windows last used."""


def remembered_course(ctx: AddonContext, available: list[CourseData]) -> CourseData | None:
    """The course last used, else the first one (None when there are none)."""
    if not available:
        return None
    ui = ctx.storage().read_json(UI_STATE, {})
    name = ui.get(COURSE_KEY) if isinstance(ui, dict) else None
    return next((c for c in available if c.name == name), available[0])


def remember_course(ctx: AddonContext, name: str) -> None:
    store = ctx.storage()
    ui = store.read_json(UI_STATE, {})
    ui = ui if isinstance(ui, dict) else {}
    ui[COURSE_KEY] = name
    store.write_json(UI_STATE, ui)


def open_session(
    ctx: AddonContext, course: CourseData, section: SectionData, store: ProgressStore | None = None
) -> bool:
    """Open a learn session on ``section`` (False, with a word to the learner, when nothing can be
    learned there now)."""

    store = store or ProgressStore(ctx.storage())
    progress = store.all()
    notes = session_notes(section, course, progress, ctx.config())
    pending = [n.nid for n in unhanded(course.notes, progress)]
    if not notes and not pending:
        tooltip(f"Nothing to learn in {section.label}: every recipe is learned or locked.")
        return False
    remember_course(ctx, course.name)
    _show(ctx, notes, section.label, pending)
    return True


def _show(ctx: AddonContext, notes: list[RecipeNote], label: str, pending: list[int]) -> None:
    from .learn_window import LearnWindow

    if mw.col is None:
        return
    window = LearnWindow(ctx, notes, label, pending=pending)
    window.show()
    window.raise_()
    window.activateWindow()


def learn_next(ctx: AddonContext) -> bool:
    """Tools → Math Path → Learn next: a session on the NEXT section of the course."""
    if mw.col is None:
        return False
    for w in ctx.windows:
        if type(w).__name__ == "LearnWindow":
            w.showNormal()
            w.raise_()
            w.activateWindow()
            return True
    available = courses.read_courses(mw.col)
    course = remembered_course(ctx, available)
    if course is None:
        tooltip("No Math Path notes yet. Tools → Math Path → Import recipes… adds them.")
        return False
    store = ProgressStore(ctx.storage())
    section = next_section(course, store.all(), ctx.config())
    if section is None:
        tooltip(f"Nothing to learn in {course.name}: every recipe is learned or locked.")
        return False
    return open_session(ctx, course, section, store)
