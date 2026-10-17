"""The review window's screens (pure): the problem, then how it went and the rating."""

from __future__ import annotations

from ..review import DONE, PREPARING, RATING_NAMES, RATINGS, ReviewSession, outcome_text
from . import run_view
from .common import bar, button, card, chip, esc, note
from .run_view import Screen


def header(session: ReviewSession) -> str:
    recipe = session.recipe
    where = f"{recipe.section_number} {recipe.section_title}".strip()
    title = esc(session.note.title or recipe.title)
    names = (
        f'<div class="mp-names"><span class="mp-title">{title}</span>'
        f'<span class="mp-sub">{esc(where)}</span></div>'
    )
    return bar(names + chip("Review", "accent"))


def rating_chips(session: ReviewSession) -> str:
    cells: list[str] = []
    for r in RATINGS:
        on = " on" if r == session.rating else ""
        cells.append(
            f'<button type="button" class="mp-pill{on}" data-act="rate" data-arg="{r}">'
            f"{RATING_NAMES[r]}</button>"
        )
    return f'<div class="mp-rating">{"".join(cells)}</div>'


def _done_body(session: ReviewSession) -> str:
    run = session.run
    assert run is not None
    kind = "warn" if run.answer_shown else "ok"
    parts = [
        note(f'<span class="mp-strong">{esc(outcome_text(run))}</span>', kind),
        run_view.problem_card(run),
        run_view.answers_card(run),
        card(
            f'<p>Math Path picked <span class="mp-strong">{RATING_NAMES[session.suggested]}</span> '
            "for Anki. Change it if it was wrong, then press Next.</p>" + rating_chips(session),
            "Anki rating",
        ),
        run_view.worked_solution(run),
    ]
    summary = f"{run_view.worked_note(run)} · {run_view.seconds_text(run.active_ms)}"
    parts.append(f'<div class="mp-sub">{esc(summary)}</div>')
    return "".join(parts)


def footer(session: ReviewSession) -> str:
    if session.screen == DONE:
        label = f"Next ({RATING_NAMES[session.rating]})"
        left = button(label, "next", role="primary", tip="Enter")
    elif session.screen == PREPARING:
        left = ""
    else:
        left = button("Check", "check", role="primary", tip="Enter")
    return bar(
        left + '<span class="mp-spacer"></span>' + button("Close", "close", role="ghost"), foot=True
    )


def render(session: ReviewSession, *, notice: str = "") -> Screen:
    run = session.run
    extra = note(esc(notice), "warn") if notice else ""
    if session.screen == PREPARING or run is None:
        body = card(
            '<p class="mp-strong">Preparing…</p>'
            f'<p class="mp-muted">Making a fresh {esc(session.recipe.title)} problem.</p>'
        )
        html = header(session) + f'<div class="mp-main">{extra}{body}</div>' + footer(session)
        return Screen(html)
    if session.screen == DONE:
        html = (
            header(session)
            + f'<div class="mp-main">{extra}{_done_body(session)}</div>'
            + footer(session)
        )
        return Screen(html, {}, {}, (), "")
    body = run_view.mode_body(run)
    pad = run_view.pad_block(run)
    html = header(session) + f'<div class="mp-main">{extra}{body}</div>' + pad + footer(session)
    return Screen(
        html,
        run_view.run_fields(run),
        run_view.run_texts(run),
        run_view.run_readonly(run),
        session.focus_id,
    )
