"""Read the courses, their sections and the notes' card states (may import anki, never Qt)."""

from __future__ import annotations

import re
from datetime import date, timedelta

# anki.collection must load before anki.cards (circular import).
import anki.collection  # noqa: F401  # pyright: ignore[reportUnusedImport]
from anki.cards import Card, CardId
from anki.collection import Collection, SearchNode
from anki.consts import (
    CARD_TYPE_LRN,
    CARD_TYPE_NEW,
    CARD_TYPE_RELEARNING,
    CARD_TYPE_REV,
    QUEUE_TYPE_MANUALLY_BURIED,
    QUEUE_TYPE_SIBLING_BURIED,
    QUEUE_TYPE_SUSPENDED,
)
from anki.decks import DeckId

from ..course_model import CardState, CourseData, SectionData, natural_key
from ..notes import RecipeNote
from . import notetype

SECTION_NUMBER = re.compile(r"^(\d+(?:\.\d+)*)\s")
"""A section deck's name starts with its number and a space (``3.2 Quadratic …``)."""

TAG_DRILL = "rd::drill"
TAG_DRILLED = "rd::drilled"
TAG_UNDRILLED = "rd::undrilled"
"""Recall Drill's tags, read only: exact tags, never ``tag:rd::*``."""

_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def section_number(label: str) -> str:
    m = SECTION_NUMBER.match(label)
    return m.group(1) if m else ""


def card_state(col: Collection, card: Card) -> CardState:
    """Anki's state of a card in words (``review, due Mon Oct 19``)."""
    if card.queue == QUEUE_TYPE_SUSPENDED:
        return CardState("suspended", "suspended")
    if card.queue in (QUEUE_TYPE_MANUALLY_BURIED, QUEUE_TYPE_SIBLING_BURIED):
        return CardState(
            "buried", "buried until tomorrow" if card.type == CARD_TYPE_NEW else "buried"
        )
    if card.type == CARD_TYPE_NEW:
        return CardState("new", "new")
    if card.type in (CARD_TYPE_LRN, CARD_TYPE_RELEARNING):
        return CardState("learning", "learning")
    if card.type == CARD_TYPE_REV:
        days = card.due - col.sched.today
        when = date.today() + timedelta(days=days)
        text = f"{_DAYS[when.weekday()]} {_MONTHS[when.month - 1]} {when.day}"
        return CardState("review", "review, due today" if days <= 0 else f"review, due {text}")
    return CardState("new", "new")


def _recall_counts(col: Collection, deck_name: str) -> tuple[int, int]:
    """(Recall Drill cards, of them drilled or released) in the deck and its subdecks."""

    def find(tag: str) -> set[int]:
        search = col.build_search_string(SearchNode(deck=deck_name), SearchNode(tag=tag))
        return {int(c) for c in col.find_cards(search)}

    drill, drilled, undrilled = find(TAG_DRILL), find(TAG_DRILLED), find(TAG_UNDRILLED)
    done = drilled | undrilled
    return len(drill | done), len(done)


def read_courses(col: Collection) -> list[CourseData]:
    """Every top deck that contains Math Path notes, with its sections, in deck-name order."""
    notes = notetype.read_notes(col)
    if not notes:
        return []
    by_top: dict[str, list[RecipeNote]] = {}
    for n in notes:
        if n.did == 0:
            continue
        top = col.decks.name(DeckId(n.did)).split("::")[0]
        by_top.setdefault(top, []).append(n)
    courses: list[CourseData] = []
    for top in sorted(by_top, key=natural_key):
        course_notes = by_top[top]
        top_id = col.decks.id(top, create=False)
        decks = {
            int(d["id"]): str(d["name"])
            for d in col.decks.all()
            if not d.get("dyn") and (str(d["name"]) == top or str(d["name"]).startswith(top + "::"))
        }
        holding = {n.did for n in course_notes}
        section_ids = [
            did
            for did, name in decks.items()
            if did in holding or section_number(name.split("::")[-1])
        ]
        sections: list[SectionData] = []
        for did in sorted(section_ids, key=lambda i: natural_key(decks[i])):
            name = decks[did]
            label = name.split("::")[-1]
            total, drilled = _recall_counts(col, name)
            sections.append(
                SectionData(
                    did=did,
                    name=name,
                    label=label,
                    notes=tuple(n for n in course_notes if n.did == did),
                    recall_total=total,
                    recall_drilled=drilled,
                    number=section_number(label),
                )
            )
        states: dict[int, CardState] = {}
        for n in course_notes:
            if n.cids:
                states[n.nid] = card_state(col, col.get_card(CardId(n.cids[0])))
        courses.append(
            CourseData(
                did=int(top_id or 0),
                name=top,
                sections=tuple(sections),
                states=states,
                notes=tuple(sorted(course_notes, key=lambda n: n.nid)),
            )
        )
    return courses
