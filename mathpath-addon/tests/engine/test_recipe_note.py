"""The Recipe field round-trips exactly."""

from __future__ import annotations

import json
from typing import Any

import pytest
from recipe_files import CH03, V2

from math_path import recipe_note
from math_path.recipe import loads_recipe

FILES = sorted(CH03.glob("*.json")) + sorted(V2.glob("*.json"))
TRICKY = "a<b >= c & d \\ \"q\" 's' é ≤ 日本 &amp; &lt;b&gt; <i>not a tag</i>\n\ttab"


def test_there_are_thirty_chapter_3_fixtures() -> None:
    assert len(sorted(CH03.glob("*.json"))) == 30


@pytest.mark.parametrize("path", FILES, ids=[p.stem for p in FILES])
def test_every_fixture_round_trips(path: Any) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    field = recipe_note.encode_recipe(data)
    assert recipe_note.decode_recipe(field) == data
    assert "<" not in field and ">" not in field  # inequalities can't be mistaken for tags
    assert field.isascii()
    assert loads_recipe(recipe_note.decode_text(field)).id == data["id"]


def test_a_tricky_string_round_trips_exactly() -> None:
    assert recipe_note.decode_text(recipe_note.encode_text(TRICKY)) == TRICKY
    data = {"x": TRICKY, "n": [1, 2.5, None, True], "nested": {"k": "a<b"}}
    assert recipe_note.decode_recipe(recipe_note.encode_recipe(data)) == data


def test_tags_the_editor_adds_are_ignored() -> None:
    data = {"title": "x < 3 & y >= 2", "n": 1}
    field = recipe_note.encode_recipe(data)
    mangled = "<div>" + field[:20] + "<br>" + field[20:] + "</div>"
    assert recipe_note.decode_recipe(mangled) == data
    nbsp = recipe_note.encode_recipe({"a": "b  c"}).replace(",", ",&nbsp;")
    assert recipe_note.decode_recipe(nbsp) == {"a": "b  c"}


def test_the_fields_and_tags_follow_the_note_contract() -> None:
    recipe = loads_recipe((CH03 / "ca.quad.solve_factoring.json").read_text(encoding="utf-8"))
    fields = recipe_note.fields_for(recipe, "Solve: \\(x\\)")
    assert set(fields) == {"Title", "Section", "RecipeId", "Version", "Prompt", "Recipe"}
    assert fields["RecipeId"] == "ca.quad.solve_factoring" and fields["Version"] == "1"
    assert fields["Section"] == "3.2 Quadratic Equations, Functions, Zeros, and Models"
    tags = recipe_note.tags_for(recipe)
    assert tags == ["mp::recipe", "Recipe::ca.quad.solve_factoring"]
    assert not any(t.startswith("rd::") for t in tags)
