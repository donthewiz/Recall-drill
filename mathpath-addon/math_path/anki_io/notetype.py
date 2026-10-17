"""The "Math Path recipe" note type, and reading recipe notes back (may import anki, never Qt)."""

from __future__ import annotations

# anki.collection must load before anki.cards (circular import).
import anki.collection  # noqa: F401  # pyright: ignore[reportUnusedImport]
from anki.collection import Collection
from anki.models import NotetypeDict, NotetypeId
from anki.notes import Note, NoteId

from .. import recipe_note
from ..notes import RecipeNote
from ..recipe import Recipe, RecipeError, parse_recipe

PYCMD_OPEN = "mathpath:open"
"""The card face's link sends this through the reviewer's ``pycmd``."""

FRONT = """<div class="mp-card">
<div class="mp-title">{{Title}}</div>
<div class="mp-section">{{Section}}</div>
<div class="mp-solving">Solving in Math Path…</div>
<div class="mp-link"><a href="#"
 onclick="if (typeof pycmd === 'function') { pycmd('mathpath:open'); } return false;"
>Solve in Math Path</a></div>
</div>"""

BACK = """{{FrontSide}}
<hr id=answer>
<div class="mp-card mp-prompt">{{Prompt}}</div>
{{#Notes}}<div class="mp-card mp-notes">{{Notes}}</div>{{/Notes}}"""

CSS = """.card { font-family: -apple-system, "Segoe UI", Roboto, sans-serif; font-size: 20px;
  text-align: center; color: #2b3036; background: #ffffff; }
.nightMode.card, .night-mode .card { color: #abb2bf; background: #282c34; }
.mp-title { font-size: 24px; font-weight: 700; margin-bottom: 4px; }
.mp-section { font-size: 15px; opacity: .7; margin-bottom: 14px; }
.mp-solving { font-size: 16px; margin-top: 8px; }
.mp-link a { font-size: 15px; }
.mp-prompt { margin-top: 10px; }
.mp-notes { font-size: 15px; opacity: .8; margin-top: 10px; }
"""


def is_math_path_model(model: NotetypeDict) -> bool:
    """Both a RecipeId and a Recipe field: a Math Path note type, whatever its name."""
    names = {str(f["name"]) for f in model["flds"]}
    return all(f in names for f in recipe_note.REQUIRED_FIELDS)


def math_path_models(col: Collection) -> list[NotetypeDict]:
    out: list[NotetypeDict] = []
    for entry in col.models.all_names_and_ids():
        model = col.models.get(NotetypeId(entry.id))
        if model is not None and is_math_path_model(model):
            out.append(model)
    return out


def is_math_path_note(note: Note) -> bool:
    names = set(note.keys())
    return all(f in names for f in recipe_note.REQUIRED_FIELDS)


def ensure_notetype(col: Collection) -> NotetypeDict:
    """The "Math Path recipe" note type, created when it is missing."""
    existing = col.models.by_name(recipe_note.NOTETYPE_NAME)
    if existing is not None and is_math_path_model(existing):
        return existing
    mm = col.models
    name = recipe_note.NOTETYPE_NAME
    if existing is not None:  # a note type of that name that isn't ours: don't touch it
        name = f"{name} (Math Path)"
    model = mm.new(name)
    for field in recipe_note.FIELDS:
        mm.add_field(model, mm.new_field(field))
    template = mm.new_template("Problem")
    template["qfmt"] = FRONT
    template["afmt"] = BACK
    mm.add_template(model, template)
    model["css"] = CSS
    mm.add(model)
    made = mm.by_name(name)
    assert made is not None
    return made


def read_note(note: Note) -> RecipeNote:
    rid = recipe_note.decode_text(note[recipe_note.F_ID]).strip()
    try:
        version = int(recipe_note.decode_text(note[recipe_note.F_VERSION]).strip() or "0")
    except ValueError:
        version = 0
    recipe: Recipe | None = None
    error = ""
    try:
        recipe = parse_recipe(recipe_note.decode_recipe(note[recipe_note.F_RECIPE]))
    except (RecipeError, ValueError) as exc:
        error = str(exc)
    cards = sorted(note.cards(), key=lambda c: c.ord)
    return RecipeNote(
        nid=int(note.id),
        recipe_id=rid,
        version=version,
        title=recipe_note.decode_text(note[recipe_note.F_TITLE])
        if recipe_note.F_TITLE in note
        else "",
        section=recipe_note.decode_text(note[recipe_note.F_SECTION])
        if recipe_note.F_SECTION in note
        else "",
        recipe=recipe,
        error=error,
        tags=tuple(note.tags),
        ntid=int(note.mid),
        did=int(cards[0].odid or cards[0].did) if cards else 0,
        cids=tuple(int(c.id) for c in cards),
    )


def read_notes(col: Collection) -> list[RecipeNote]:
    """Every Math Path note in the collection, in note-id order."""
    out: list[RecipeNote] = []
    for model in math_path_models(col):
        for nid in col.models.nids(NotetypeId(int(model["id"]))):
            out.append(read_note(col.get_note(NoteId(nid))))
    return sorted(out, key=lambda n: n.nid)
