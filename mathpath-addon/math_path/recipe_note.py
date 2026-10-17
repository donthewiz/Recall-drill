"""A recipe as the fields of a Math Path note (pure).

The note contract (``README.md``): the fields are ``Title``, ``Section``, ``RecipeId``, ``Version``,
``Prompt`` (one example problem, MathJax), ``Recipe`` (the full recipe JSON) and ``Notes``. A
note type is a Math Path type when it has both a ``RecipeId`` and a ``Recipe`` field, whatever
its name.

``Recipe`` is stored HTML-escaped (``<``, ``>`` and ``&`` appear in inequalities) as compact,
ASCII-only JSON, so it round-trips exactly; reading it back drops any tags Anki's editor adds.
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Mapping
from typing import Any

from .recipe import Recipe

NOTETYPE_NAME = "Math Path recipe"
F_TITLE = "Title"
F_SECTION = "Section"
F_ID = "RecipeId"
F_VERSION = "Version"
F_PROMPT = "Prompt"
F_RECIPE = "Recipe"
F_NOTES = "Notes"
FIELDS: tuple[str, ...] = (F_TITLE, F_SECTION, F_ID, F_VERSION, F_PROMPT, F_RECIPE, F_NOTES)
REQUIRED_FIELDS: tuple[str, str] = (F_ID, F_RECIPE)
"""A note type with both is a Math Path note type."""

TAG_RECIPE = "mp::recipe"
TAG_LEARNED = "mp::learned"
TAG_RECIPE_PREFIX = "Recipe::"

_TAG = re.compile(r"<[^>]*>")


def encode_text(text: str) -> str:
    """``text`` as an Anki field: ``& < >`` escaped, nothing else changed."""
    return html.escape(text, quote=False)


def decode_text(field: str) -> str:
    """The inverse of :func:`encode_text`, ignoring any tags the editor added."""
    return html.unescape(_TAG.sub("", field))


def encode_recipe(data: Mapping[str, Any]) -> str:
    """The ``Recipe`` field for a decoded recipe: compact ASCII JSON, escaped."""
    return encode_text(json.dumps(data, ensure_ascii=True, separators=(",", ":")))


def decode_recipe(field: str) -> Any:
    """The decoded recipe in a ``Recipe`` field (``json.JSONDecodeError`` if it isn't JSON).
    The JSON is ASCII, so a non-breaking space can only have come from the editor."""
    return json.loads(decode_text(field).replace("\xa0", " "))


def section_text(recipe: Recipe) -> str:
    return f"{recipe.section_number} {recipe.section_title}".strip()


def tags_for(recipe: Recipe) -> list[str]:
    """The tags a new note gets. Never a ``rd::`` tag: those belong to Recall Drill."""
    return [TAG_RECIPE, TAG_RECIPE_PREFIX + recipe.id]


def fields_for(recipe: Recipe, prompt_html: str) -> dict[str, str]:
    """Every field but ``Notes`` (which the learner owns)."""
    return {
        F_TITLE: encode_text(recipe.title),
        F_SECTION: encode_text(section_text(recipe)),
        F_ID: encode_text(recipe.id),
        F_VERSION: str(recipe.version),
        F_PROMPT: prompt_html,
        F_RECIPE: encode_recipe(recipe.raw),
    }
