"""Import recipe files as suspended Math Path notes (may import anki, never Qt).

Tools → Math Path → Import recipes…: pick a folder; every ``*.json`` with ``format``
``mathpath-recipe/1`` or ``/2`` becomes a note (others are refused with a reason). Each recipe is
smoke-tested (3 instances) first; that and the reading run off the main thread. A note goes in the
section deck: the deck whose last path component starts with ``<section.number> ``; none or several
match → the dialog lets the learner pick (default: skip). A ``RecipeId`` that already exists is
updated only when the file's ``version`` is higher (fields only: scheduling and Math Path
progress are untouched). New notes are added suspended, in file-name order, and all writes of one
import are one undo step.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

# anki.collection must load before anki.cards (circular import).
import anki.collection  # noqa: F401  # pyright: ignore[reportUnusedImport]
from anki.collection import AddNoteRequest, Collection, OpChanges
from anki.decks import DeckId
from anki.notes import Note, NoteId

from .. import recipe_note
from ..import_plan import (
    DeckChoice,
    ImportItem,
    ImportPlan,
    ImportSummary,
    RecipeFile,
    resolve_choices,
    section_decks,
)
from ..problem import example_prompt_html, smoke_test
from ..recipe import FORMATS, RecipeError, parse_recipe
from . import notetype
from .undo import run_as_one_step

UNDO_LABEL = "Math Path: import recipes"


def scan_folder(folder: Path, *, smoke: bool = True) -> list[RecipeFile]:
    """Read every ``*.json`` in ``folder`` (file-name order) and smoke-test the readable ones.

    Meant for a worker thread: it loads SymPy and generates three instances of each recipe."""
    out: list[RecipeFile] = []
    for path in sorted(folder.glob("*.json"), key=lambda p: p.name.casefold()):
        try:
            data: Any = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as exc:
            out.append(RecipeFile(path.name, None, f"can't read the file ({exc})"))
            continue
        except json.JSONDecodeError as exc:
            out.append(
                RecipeFile(path.name, None, f"not valid JSON ({exc.msg}, line {exc.lineno})")
            )
            continue
        fmt: Any = cast(dict[str, Any], data).get("format") if isinstance(data, dict) else None
        if fmt not in FORMATS:
            shown = fmt if isinstance(fmt, str) else "none"
            out.append(
                RecipeFile(
                    path.name,
                    None,
                    f"format {shown!r} is not one Math Path reads ({', '.join(FORMATS)})",
                )
            )
            continue
        try:
            recipe = parse_recipe(data)
        except RecipeError as exc:
            out.append(RecipeFile(path.name, None, str(exc)))
            continue
        if smoke:
            try:
                smoke_test(recipe)
            except Exception as exc:  # noqa: BLE001 (any failure to generate refuses the recipe)
                out.append(RecipeFile(path.name, None, f"can't generate a problem ({exc})"))
                continue
        out.append(RecipeFile(path.name, recipe))
    return out


def normal_decks(col: Collection) -> list[DeckChoice]:
    """Every deck that is not a filtered deck, in name order."""
    out: list[DeckChoice] = []
    for d in col.decks.all():
        if d.get("dyn"):
            continue
        out.append(DeckChoice(int(d["id"]), str(d["name"])))
    return sorted(out, key=lambda c: c.name.casefold())


def plan_import(col: Collection, files: Sequence[RecipeFile]) -> ImportPlan:
    """What importing these files would do, read fresh. Writes nothing."""
    existing: dict[str, notetype.RecipeNote] = {}
    for n in notetype.read_notes(col):
        existing.setdefault(n.recipe_id, n)
    decks = normal_decks(col)
    chosen: dict[str, tuple[str, int]] = {}
    for f in files:
        if f.recipe is not None:
            prior = chosen.get(f.recipe.id)
            if prior is None or f.recipe.version > prior[1]:
                chosen[f.recipe.id] = (f.name, f.recipe.version)
    items: list[ImportItem] = []
    for f in files:
        recipe = f.recipe
        if recipe is None:
            items.append(ImportItem(f.name, None, "skip", f.error))
            continue
        if chosen[recipe.id][0] != f.name:
            items.append(
                ImportItem(
                    f.name,
                    recipe,
                    "skip",
                    f"same id as {chosen[recipe.id][0]}, which has the higher version "
                    "or comes first",
                )
            )
            continue
        have = existing.get(recipe.id)
        if have is not None:
            if recipe.version > have.version:
                items.append(
                    ImportItem(
                        f.name,
                        recipe,
                        "update",
                        f"version {have.version} → {recipe.version}",
                        existing_nid=have.nid,
                    )
                )
            else:
                items.append(
                    ImportItem(
                        f.name,
                        recipe,
                        "unchanged",
                        f"already imported (version {have.version})",
                        existing_nid=have.nid,
                    )
                )
            continue
        matches = section_decks(decks, recipe)
        if len(matches) == 1:
            items.append(
                ImportItem(f.name, recipe, "add", did=matches[0].did, candidates=tuple(matches))
            )
        else:
            reason = "no deck starts with " if not matches else "several decks start with "
            items.append(
                ImportItem(
                    f.name,
                    recipe,
                    "add",
                    f"{reason}{recipe.section_number!r}",
                    candidates=tuple(matches),
                )
            )
    return ImportPlan(tuple(items), tuple(decks))


def apply_import(
    col: Collection, plan: ImportPlan, picks: Mapping[str, int | None] | None = None
) -> ImportSummary:
    """Write the plan. The note type is made first (idempotent); every note write after it is one
    undo step. Raises :class:`~.undo.StepFailed` after undoing what it had done."""
    items = resolve_choices(plan, picks or {})
    work = [i for i in items if i.action in ("add", "update")]
    added: list[str] = []
    updated: list[str] = []
    nids: list[int] = []
    changes = OpChanges()
    if work:
        model = notetype.ensure_notetype(col)

        def write() -> None:
            # Bulk calls only: Anki's undo list keeps 30 steps, so one call per note could push the
            # start of this step out of it.
            to_add: list[AddNoteRequest] = []
            to_update: list[Note] = []
            for item in work:
                assert item.recipe is not None
                recipe = item.recipe
                fields = recipe_note.fields_for(recipe, example_prompt_html(recipe))
                if item.action == "update":
                    assert item.existing_nid is not None
                    old = col.get_note(NoteId(item.existing_nid))
                    for name, value in fields.items():
                        old[name] = value
                    to_update.append(old)
                    updated.append(recipe.id)
                    continue
                assert item.did is not None
                new = col.new_note(model)
                for name, value in fields.items():
                    new[name] = value
                for tag in recipe_note.tags_for(recipe):
                    new.add_tag(tag)
                to_add.append(AddNoteRequest(new, DeckId(item.did)))
                added.append(recipe.id)
            if to_update:
                col.update_notes(to_update)
                nids.extend(int(n.id) for n in to_update)
            if to_add:
                col.add_notes(to_add)
                cids = [c for r in to_add for c in col.card_ids_of_note(r.note.id)]
                col.sched.suspend_cards(cids)
                nids.extend(int(r.note.id) for r in to_add)

        changes = run_as_one_step(col, UNDO_LABEL, write)
    return ImportSummary(
        added=tuple(added),
        updated=tuple(updated),
        unchanged=tuple(
            i.recipe.id for i in items if i.action == "unchanged" and i.recipe is not None
        ),
        skipped=tuple(
            (i.recipe.id if i.recipe is not None else i.file, i.reason)
            for i in items
            if i.action == "skip"
        ),
        nids=tuple(nids),
        changes=changes,
    )
