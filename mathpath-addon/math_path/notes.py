"""A Math Path note as the learn session and the progress map see it (pure)."""

from __future__ import annotations

from dataclasses import dataclass

from .recipe import Recipe
from .recipe_note import TAG_LEARNED


@dataclass(frozen=True)
class RecipeNote:
    """A Math Path note as read from the collection."""

    nid: int
    recipe_id: str
    version: int
    title: str
    section: str
    recipe: Recipe | None
    """None when the ``Recipe`` field can't be read (the note is shown but can't be solved)."""
    error: str
    tags: tuple[str, ...]
    ntid: int
    did: int = 0
    """The home deck of the note's first card (its section deck)."""
    cids: tuple[int, ...] = ()

    @property
    def learned_tag(self) -> bool:
        """The note carries ``mp::learned`` (the handoff put it there; it syncs, progress.json
        doesn't)."""
        return TAG_LEARNED in self.tags
