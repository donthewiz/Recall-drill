"""What an import will do, as plain data (pure): the plan, the learner's deck picks, the summary.

``anki_io/importer.py`` reads files and the collection to build these and writes the notes;
nothing here touches Anki.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from .recipe import Recipe

Action = Literal["add", "update", "unchanged", "skip"]


@dataclass(frozen=True)
class RecipeFile:
    """One ``*.json`` file, read and smoke-tested (``recipe`` is None when it was refused)."""

    name: str
    recipe: Recipe | None
    error: str = ""


@dataclass(frozen=True)
class DeckChoice:
    did: int
    name: str


@dataclass(frozen=True)
class ImportItem:
    file: str
    recipe: Recipe | None
    action: Action
    reason: str = ""
    did: int | None = None
    """The section deck a new note goes to (None: it needs a pick, or isn't added)."""
    candidates: tuple[DeckChoice, ...] = ()
    """The decks that match the section when there is none or several (the pick list)."""
    existing_nid: int | None = None

    @property
    def needs_deck(self) -> bool:
        return self.action == "add" and self.did is None


@dataclass(frozen=True)
class ImportPlan:
    items: tuple[ImportItem, ...]
    all_decks: tuple[DeckChoice, ...]
    """Every normal deck, for the pick list when no deck matched."""

    @property
    def needing_deck(self) -> tuple[ImportItem, ...]:
        return tuple(i for i in self.items if i.needs_deck)

    def count(self, action: Action) -> int:
        return sum(1 for i in self.items if i.action == action)


def section_decks(decks: Sequence[DeckChoice], recipe: Recipe) -> list[DeckChoice]:
    """The decks whose last path component starts with ``<section.number> ``; when several do and
    some also have the recipe's course in their path, only those."""
    number = recipe.section_number
    pattern = re.compile(re.escape(number) + r"\s")
    found = [d for d in decks if pattern.match(d.name.split("::")[-1])]
    if len(found) > 1 and recipe.course:
        course = recipe.course.casefold()
        same_course = [
            d for d in found if any(course in p.casefold() for p in d.name.split("::")[:-1])
        ]
        if len(same_course) == 1:
            return same_course
    return found


@dataclass(frozen=True)
class ImportSummary:
    added: tuple[str, ...]
    updated: tuple[str, ...]
    unchanged: tuple[str, ...]
    skipped: tuple[tuple[str, str], ...]
    """``(file or recipe id, reason)``."""
    nids: tuple[int, ...] = field(default=())
    changes: Any = None
    """The ``OpChanges`` of the writes (what ``CollectionOp`` needs); None before they ran."""

    @property
    def lines(self) -> list[str]:
        out = [
            f"Added {len(self.added)}, updated {len(self.updated)}, "
            f"unchanged {len(self.unchanged)}, skipped {len(self.skipped)}."
        ]
        out += [f"Skipped {name}: {why}" for name, why in self.skipped]
        return out


def resolve_choices(plan: ImportPlan, picks: Mapping[str, int | None]) -> list[ImportItem]:
    """The items with the learner's deck picks applied (``picks``: recipe id → deck id, or None to
    skip). An item that needed a deck and got none becomes a skip."""
    out: list[ImportItem] = []
    for item in plan.items:
        if item.needs_deck and item.recipe is not None:
            did = picks.get(item.recipe.id)
            if did is None:
                out.append(
                    ImportItem(
                        item.file,
                        item.recipe,
                        "skip",
                        f"{item.reason}; no deck picked",
                        candidates=item.candidates,
                    )
                )
            else:
                out.append(
                    ImportItem(
                        item.file,
                        item.recipe,
                        "add",
                        item.reason,
                        did=did,
                        candidates=item.candidates,
                    )
                )
        else:
            out.append(item)
    return out
