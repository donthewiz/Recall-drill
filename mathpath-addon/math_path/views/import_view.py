"""The import dialog's screens (pure)."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..import_plan import DeckChoice, ImportItem, ImportPlan, ImportSummary
from .common import bar, button, card, chip, esc, note, plural

PICK_PREFIX = "pick:"
"""A deck list's id is ``pick:<recipe id>``."""

ACTION_CHIPS = {
    "add": ("Add", "ok"),
    "update": ("Update", "accent"),
    "unchanged": ("Unchanged", "muted"),
    "skip": ("Skip", "warn"),
}


@dataclass
class ImportState:
    stage: str = "start"
    """start, scanning, review, importing, done or error."""
    folder: str = ""
    plan: ImportPlan | None = None
    picks: dict[str, int | None] = field(default_factory=dict[str, int | None])
    summary: ImportSummary | None = None
    message: str = ""


def _deck_cell(item: ImportItem, plan: ImportPlan, picks: dict[str, int | None]) -> str:
    if item.action != "add" or item.recipe is None:
        return ""
    if item.did is not None:
        name = next((d.name for d in item.candidates if d.did == item.did), "")
        return f'<span class="mp-muted">{esc(name)}</span>'
    options: tuple[DeckChoice, ...] = item.candidates or plan.all_decks
    chosen = picks.get(item.recipe.id)
    opts = ['<option value="">Skip (no deck)</option>']
    for d in options:
        sel = " selected" if d.did == chosen else ""
        opts.append(f'<option value="{d.did}"{sel}>{esc(d.name)}</option>')
    why = "several decks match" if item.candidates else "no deck matches"
    return (
        f'<div class="mp-sub">{esc(why)} {esc(item.recipe.section_number)}: pick one</div>'
        f'<select class="mp-input" data-id="{PICK_PREFIX}{esc(item.recipe.id)}">'
        f"{''.join(opts)}</select>"
    )


def _row(item: ImportItem, plan: ImportPlan, picks: dict[str, int | None]) -> str:
    label, kind = ACTION_CHIPS[item.action]
    if item.recipe is None:
        title = f'<span class="mp-strong">{esc(item.file)}</span>'
        meta = ""
    else:
        title = f'<span class="mp-strong">{esc(item.recipe.title)}</span>'
        meta = (
            f'<div class="mp-sub">{esc(item.recipe.id)} · {esc(item.recipe.section_number)} · '
            f"version {item.recipe.version}</div>"
        )
    reason = (
        f'<div class="mp-sub">{esc(item.reason)}</div>'
        if item.reason and item.action != "add"
        else ""
    )
    return (
        f'<div class="item"><div>{title}{meta}{reason}{_deck_cell(item, plan, picks)}</div>'
        f"<div>{chip(label, kind)}</div></div>"
    )


def render(state: ImportState) -> str:
    head = bar(
        '<div class="mp-names"><span class="mp-title">Import recipes</span>'
        '<span class="mp-sub">Each recipe becomes a suspended Math Path note in its section deck'
        "</span></div>"
    )
    body: list[str] = []
    if state.stage == "start":
        body.append(
            card(
                "<p>Pick a folder with recipe files (<code>*.json</code>, format "
                "<code>mathpath-recipe/1</code> or <code>/2</code>). Nothing is written until "
                "you press Import.</p>"
                + (note(esc(state.message), "bad") if state.message else "")
                + button("Choose folder…", "choose", role="primary")
            )
        )
    elif state.stage == "scanning":
        body.append(
            card(
                '<p class="mp-strong">Checking recipes…</p>'
                f'<p class="mp-muted">{esc(state.folder)}</p>'
                '<p class="mp-muted">Each recipe makes three practice problems first, so a broken '
                "recipe is caught here.</p>"
            )
        )
    elif state.stage == "review" and state.plan is not None:
        plan = state.plan
        counts = (
            f"{plural(plan.count('add'), 'to add', 'to add')}, {plan.count('update')} to update, "
            f"{plan.count('unchanged')} unchanged, {plan.count('skip')} skipped"
        )
        waiting = len(plan.needing_deck)
        top = f'<p class="mp-muted">{esc(state.folder)}</p><p class="mp-strong">{esc(counts)}</p>'
        if waiting:
            top += note(
                f"{plural(waiting, 'recipe')} can't find exactly one section deck. Pick a deck "
                "for each, or leave it on Skip.",
                "warn",
            )
        rows = "".join(_row(i, plan, state.picks) for i in plan.items)
        body.append(card(top + f'<div class="mp-list">{rows}</div>'))
    elif state.stage == "importing":
        body.append(card('<p class="mp-strong">Importing…</p>'))
    elif state.stage == "done" and state.summary is not None:
        s = state.summary
        lines = "".join(f"<li>{esc(line)}</li>" for line in s.lines)
        body.append(
            card(
                f'<p class="mp-strong">Done.</p><ul>{lines}</ul>'
                '<p class="mp-muted">Undo with Edit → Undo “Math Path: import recipes”. The new '
                "notes are suspended until a learn session hands them to Anki.</p>"
            )
        )
    elif state.stage == "error":
        body.append(card(note(esc(state.message), "bad")))
    foot: list[str] = []
    if state.stage == "review" and state.plan is not None:
        todo = state.plan.count("add") + state.plan.count("update")
        foot.append(button("Import", "import", role="primary", disabled=todo == 0))
        foot.append(button("Choose another folder…", "choose", role="ghost"))
    elif state.stage in ("start", "error"):
        pass
    foot.append('<span class="mp-spacer"></span>')
    foot.append(
        button(
            "Close" if state.stage in ("done", "error", "start") else "Cancel",
            "close",
            role="ghost",
        )
    )
    return head + f'<div class="mp-main">{"".join(body)}</div>' + bar("".join(foot), foot=True)
