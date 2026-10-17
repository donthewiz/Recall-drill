"""The progress map's screen (pure): one row per section, a chip per recipe, NEXT, Learn."""

from __future__ import annotations

from ..course_model import ChipModel, RowModel
from ..progress_controller import SELECT_PREFIX, ProgressController
from .common import bar, button, card, chip, esc, note, plural

TITLE_CHARS = 34


def short_title(title: str) -> str:
    """A recipe's title for a chip: the part before a parenthesis, cut at a word near 34 letters."""
    t = title.split(" (")[0].strip()
    if len(t) <= TITLE_CHARS:
        return t
    cut = t[:TITLE_CHARS].rsplit(" ", 1)[0]
    return (cut or t[:TITLE_CHARS]) + "…"


def _chip_html(c: ChipModel) -> str:
    cls = "mp-recipe " + c.kind
    detail = f'<span class="s">{esc(c.stage)}{" · " + esc(c.detail) if c.detail else ""}</span>'
    return (
        f'<span class="{cls}" title="{esc(c.title)}">'
        f'<span class="t">{esc(short_title(c.title))}</span>{detail}</span>'
    )


def _row_html(row: RowModel, ctl: ProgressController) -> str:
    cls = "next" if row.is_next else ""
    label = f'<div class="mp-strong">{esc(row.section.label)}</div>'
    if row.is_next:
        label += chip("NEXT", "accent")
    chips = "".join(_chip_html(c) for c in row.chips)
    chips_html = (
        f'<div class="mp-chips">{chips}</div>'
        if chips
        else '<span class="mp-muted">no recipes yet</span>'
    )
    ask = ""
    if ctl.confirm == row.section.did:
        ask = note(
            f'<div class="mp-strong">{esc(row.recall_warning)}</div>'
            '<div class="mp-row" style="margin-top:8px">'
            + button(
                "Learn anyway", "learn_anyway", str(row.section.did), role="primary", small=True
            )
            + button("Cancel", "cancel", role="ghost", small=True)
            + "</div>",
            "warn",
        )
    learn = button(
        "Learn",
        "learn",
        str(row.section.did),
        role="primary" if row.is_next else "secondary",
        disabled=not row.can_learn,
        small=True,
    )
    return (
        f'<tr class="{cls}"><td>{label}</td><td>{esc(row.recall_cell)}</td>'
        f"<td>{chips_html}{ask}</td><td>{learn}</td></tr>"
    )


def render(ctl: ProgressController, *, notice: str = "") -> str:
    model = ctl.model()
    picker = ""
    if len(ctl.courses) > 1:
        opts = "".join(
            f'<option value="{esc(c.name)}"{" selected" if c.name == ctl.selected else ""}>'
            f"{esc(c.name)}</option>"
            for c in ctl.courses
        )
        picker = (
            f'<select class="mp-input" data-id="{SELECT_PREFIX}" aria-label="Course">'
            f"{opts}</select>"
        )
    title = ctl.selected or "Progress"
    names = (
        f'<div class="mp-names"><span class="mp-title">{esc(title)}</span>'
        '<span class="mp-sub">Progress: recipes by section, in textbook order</span></div>'
    )
    next_row = model.next_row if model is not None else None
    head = bar(
        names
        + picker
        + button(
            "Learn next",
            "learn_next",
            role="primary",
            disabled=next_row is None,
            tip=f"Next: {next_row.section.label}" if next_row is not None else "Nothing to learn",
        )
        + button("Refresh", "refresh", role="ghost", small=True)
    )
    if model is None:
        body = card(
            '<p class="mp-strong">No Math Path notes yet.</p>'
            '<p class="mp-muted">Import recipe files to get started.</p>'
            + button("Import recipes…", "import", role="primary")
        )
    else:
        rows = "".join(_row_html(r, ctl) for r in model.rows)
        learned = sum(1 for r in model.rows for c in r.chips if c.kind == "learned")
        total = sum(len(r.chips) for r in model.rows)
        summary = f'<div class="mp-sub">{plural(learned, "recipe")} learned of {total}</div>'
        table = (
            '<table class="mp-table"><tr><th>Section</th><th>Recall cards</th>'
            "<th>Recipes</th><th></th></tr>"
            f"{rows}</table>"
        )
        body = (note(esc(notice), "warn") if notice else "") + card(summary + table)
    foot = bar(
        '<span class="mp-spacer"></span>' + button("Close", "close", role="ghost"), foot=True
    )
    return head + f'<div class="mp-main">{body}</div>' + foot
