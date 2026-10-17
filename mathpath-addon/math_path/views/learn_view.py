"""The learn window's screens (pure): header, the problem in progress, the result, the summary."""

from __future__ import annotations

from ..progress import FADED, MAX_FADED_TRIES, STAGE_LABELS
from ..run import FADED as RUN_FADED
from ..run import PLAN, STUDY
from ..session import PREPARING, RESULT, RUN, SUMMARY, LearnSession
from . import run_view
from .common import bar, button, card, chip, esc, note, plural
from .run_view import Screen


def _dots(session: LearnSession) -> str:
    cells: list[str] = []
    for i, item in enumerate(session.items):
        cls = "mp-dot" + (
            " done"
            if item.progress.is_learned
            else (" now" if i == session.current and session.screen != SUMMARY else "")
        )
        cells.append(f'<span class="{cls}" title="{esc(item.title)}"></span>')
    return f'<span class="mp-dots" aria-label="Recipes in this session">{"".join(cells)}</span>'


def header(session: LearnSession, show_progress: bool = True) -> str:
    item = session.item
    if item is None or session.screen == SUMMARY:
        names = (
            '<div class="mp-names"><span class="mp-title">Learn session</span>'
            f'<span class="mp-sub">{esc(session.section)}</span></div>'
        )
        chips = ""
    else:
        recipe = item.recipe
        where = f"{recipe.section_number} {recipe.section_title}".strip()
        names = (
            f'<div class="mp-names"><span class="mp-title">{esc(item.title)}</span>'
            f'<span class="mp-sub">{esc(where)}</span></div>'
        )
        chips = chip(session.stage_label, "accent")
        if item.progress.stage == FADED and item.progress.faded_tries:
            chips += chip(f"try {item.progress.faded_tries + 1} of {MAX_FADED_TRIES}", "warn")
    progress = button("Progress", "progress", role="ghost", small=True) if show_progress else ""
    return bar(names + chips + _dots(session) + progress)


def footer(session: LearnSession) -> str:
    run = session.run
    left: list[str] = []
    if session.screen == RESULT:
        left.append(button("Next", "next", role="primary", tip="Enter"))
    elif session.screen == RUN and run is not None:
        if run.mode == STUDY:
            left.append(button("Next", "next", role="primary", tip="Enter"))
        elif run.mode == PLAN:
            left.append(button("Check", "check", role="primary", tip="Enter"))
        else:
            left.append(button("Check", "check", role="primary", tip="Enter"))
    elif session.screen == SUMMARY:
        left.append(button("Close", "close", role="primary"))
    right = ""
    if session.screen in (RUN, RESULT, PREPARING):
        right = button("End session", "end", role="ghost")
    return bar("".join(left) + '<span class="mp-spacer"></span>' + right, foot=True)


def _result_body(session: LearnSession) -> str:
    run = session.run
    result = session.result
    assert run is not None and result is not None
    kind = "ok" if result.ok else "warn"
    lines = "".join(f"<div>{esc(x)}</div>" for x in result.lines)
    stage = ""
    if result.stage_before != result.stage_after:
        stage = f'<div class="mp-sub">{esc(result.stage_before)} → {esc(result.stage_after)}</div>'
    parts = [
        note(f'<span class="mp-strong">{esc(result.headline)}</span>{lines}{stage}', kind),
        run_view.problem_card(run),
    ]
    if run.mode in (RUN_FADED, "solo"):
        parts.append(run_view.answers_card(run))
        parts.append(run_view.worked_solution(run))
    elif run.mode == PLAN:
        parts.append(run_view.worked_solution(run))
    summary = f"{run_view.worked_note(run)} · {run_view.seconds_text(run.active_ms)}"
    parts.append(f'<div class="mp-sub">{esc(summary)}</div>')
    return "".join(parts)


def summary_body(session: LearnSession) -> str:
    s = session.summary()
    rows = "".join(
        f'<tr><td><span class="mp-strong">{esc(r.title)}</span></td>'
        f"<td>{esc(r.stage)}{' ' + chip('needed help', 'warn') if r.needed_help else ''}</td>"
        f"<td>{'help used' if r.helped else 'no help'}</td>"
        f"<td>{esc(run_view.seconds_text(r.time_ms))}</td></tr>"
        for r in s.rows
    )
    table = (
        '<table class="mp-table"><tr><th>Recipe</th><th>Stage reached</th><th>Help</th>'
        f"<th>Time</th></tr>{rows}</table>"
    )
    parts: list[str] = []
    learned = sum(1 for r in s.rows if r.learned)
    head = (
        f"{plural(learned, 'recipe')} learned" if learned else "No recipe reached Learned this time"
    )
    parts.append(
        f'<div class="mp-strong">{esc(head)} · '
        f"{esc(run_view.seconds_text(s.total_ms))} in all</div>"
    )
    parts.append(table)
    if s.handed_off:
        parts.append(
            note(
                f'<span class="mp-strong">{plural(len(s.handed_off), "problem")} '
                "handed to Anki.</span> "
                "Each is buried until tomorrow, then comes up in your reviews as a fresh problem. "
                "Edit → Undo “Math Path: hand off” takes it back.",
                "ok",
            )
        )
    elif s.handoff_error and s.learned:
        parts.append(
            note(
                f'<span class="mp-strong">The handoff failed.</span> {esc(s.handoff_error)}', "bad"
            )
            + button("Hand off again", "handoff", role="primary")
        )
    elif s.learned:
        parts.append(note(f"Handing {plural(len(s.learned), 'problem')} to Anki…"))
    unfinished = [r for r in s.rows if not r.learned]
    if unfinished:
        parts.append(
            note(
                f"{plural(len(unfinished), 'recipe')} not learned yet: "
                "each stays suspended and picks up at the stage shown, with a fresh problem."
            )
        )
    return card("".join(f'<div style="margin-bottom:10px">{p}</div>' for p in parts), "Summary")


def render(session: LearnSession, show_progress: bool = True) -> Screen:
    """The whole screen for the session's state."""
    run = session.run
    if session.screen == SUMMARY:
        body = summary_body(session)
        fields: dict[str, str] = {}
        ro: tuple[str, ...] = ()
        texts: dict[str, str] = {}
    elif session.screen == PREPARING or run is None:
        item = session.item
        title = esc(item.title) if item is not None else ""
        body = card(
            '<p class="mp-strong">Preparing…</p>'
            f'<p class="mp-muted">Making a fresh {title} problem.</p>'
        )
        fields, ro, texts = {}, (), {}
    elif session.screen == RESULT:
        body = _result_body(session)
        fields, ro, texts = {}, (), run_view.run_texts(run)
    else:
        body = run_view.mode_body(run)
        fields, ro, texts = (
            run_view.run_fields(run),
            run_view.run_readonly(run),
            run_view.run_texts(run),
        )
    pad = run_view.pad_block(run) if run is not None and session.screen == RUN else ""
    html = (
        header(session, show_progress)
        + f'<div class="mp-main">{body}</div>'
        + pad
        + footer(session)
    )
    return Screen(html, fields, texts, ro, session.focus_id if session.screen == RUN else "")


__all__ = ["render", "header", "footer", "summary_body", "STAGE_LABELS"]
