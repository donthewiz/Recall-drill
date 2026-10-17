"""The screens of one problem being worked, shared by the learn session and the reviews (pure).

Everything math is MathJax: the prompt, each worked result, the typed answer, the key, hints and
mistake messages (``display.kb_html`` and ``math_span``). The page only draws what these return.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .. import grading
from ..display import kb_html, math_span
from ..pages import math_field, pad_html
from ..run import (
    ANSWER,
    ANSWER_FIELD,
    FADED,
    HINT,
    OTHER_FIELD,
    PLAN,
    SHOW,
    SOLO,
    STUDY,
    VERTEX_FIELD,
    WHY,
    ProblemRun,
    plan_field,
    step_field,
)
from .common import button, card, chip, esc, note

NOTHING_TO_WRITE = '<span class="mp-muted">Do this on paper; there is nothing to write down.</span>'


@dataclass
class Screen:
    """What a window sends the page for one screen."""

    html: str
    fields: dict[str, str] = field(default_factory=dict[str, str])
    texts: dict[str, str] = field(default_factory=dict[str, str])
    readonly: tuple[str, ...] = ()
    focus: str = ""


def worked_html(run: ProblemRun, index: int) -> str:
    """A step's worked result as MathJax (or the paper reminder when it has none)."""
    shown = run.problem.steps[index].shown_html
    return shown or NOTHING_TO_WRITE


def problem_card(run: ProblemRun) -> str:
    return card(f'<div class="mp-problem">{run.problem.prompt_html}</div>', "Problem")


def _pairs(run: ProblemRun, index: int) -> str:
    """The hint and why the learner has asked for on a step, and its worked result."""
    st = run.steps[index]
    hint = run.recipe.hint_for(run.recipe.steps[index])
    parts: list[str] = []
    if st.hint_shown and hint is not None:
        parts.append(f'<div><span class="mp-chip accent">Hint</span>{kb_html(hint.hint)}</div>')
    if st.why_shown and hint is not None:
        parts.append(f'<div><span class="mp-chip accent">Why</span>{kb_html(hint.why)}</div>')
    if st.shown:
        parts.append(f'<div><span class="mp-chip warn">Step</span>{worked_html(run, index)}</div>')
    return "".join(parts)


def _study_hints(run: ProblemRun, index: int) -> str:
    """Study: the hint and why under each step, folded."""
    hint = run.recipe.hint_for(run.recipe.steps[index])
    if hint is None or not (hint.hint.strip() or hint.why.strip()):
        return ""
    rows = ""
    if hint.hint.strip():
        rows += f'<div><span class="mp-chip accent">Hint</span>{kb_html(hint.hint)}</div>'
    if hint.why.strip():
        rows += f'<div><span class="mp-chip accent">Why</span>{kb_html(hint.why)}</div>'
    return (
        f'<details class="mp-help"><summary class="mp-muted">Hint and why</summary>{rows}</details>'
    )


def steps_card(run: ProblemRun) -> str:
    """The steps: worked (Study), partly blank (Faded), or boxes for the plan (Plan)."""
    rows: list[str] = []
    for i, step in enumerate(run.problem.steps):
        st = run.steps[i]
        state = ""
        body = ""
        if run.mode == STUDY:
            body = f'<div class="mp-stepbody">{worked_html(run, i)}</div>' + _study_hints(run, i)
        elif st.blank:
            state = (
                " ok"
                if st.ok
                else (" bad" if st.ok is False else (" now" if run.active_step == i else ""))
            )
            body = _blank_row(run, i)
        elif run.instruction_only(i):
            body = ""
        else:
            body = f'<div class="mp-stepbody">{worked_html(run, i)}</div>'
        extra = ""
        if run.mode == FADED and st.blank:
            inline = _pairs(run, i)
            if st.shown and st.ok is not True:
                inline += '<div class="mp-muted">Type it in the field to go on.</div>'
            extra = f'<div class="mp-help">{inline}</div>' if inline else ""
        rows.append(
            f'<div class="mp-step{state}"><div class="mp-stepno">{i + 1}</div>'
            f'<div class="mp-stepname">{esc(step.name)}</div>{body}{extra}</div>'
        )
    label = "Worked example" if run.mode == STUDY else "Steps"
    return card(f'<div class="mp-steps">{"".join(rows)}</div>', label)


def _blank_row(run: ProblemRun, i: int) -> str:
    st = run.steps[i]
    cls = "small" + (" ok" if st.ok else (" bad" if st.ok is False else ""))
    status = ""
    if st.ok:
        status = chip("Right", "ok")
    elif st.note:
        status = f'<span class="{"mp-bad" if st.ok is False else "mp-muted"}">{esc(st.note)}</span>'
    check = "" if st.ok else button("Check", "check_step", str(i), small=True)
    field = math_field(step_field(i), label=f"Step {i + 1}", cls=cls)
    return f'<div class="mp-steprow">{field}{check}{status}</div>'


def plan_card(run: ProblemRun) -> str:
    rows: list[str] = []
    for i, step in enumerate(run.problem.steps):
        ok = run.plan_ok.get(i)
        missed = i in run.plan_missed
        cls = "mp-input" + (" ok" if ok else (" bad" if missed else ""))
        ro = " readonly" if ok else ""
        box = (
            f'<input type="text" class="{cls}" data-id="{plan_field(i)}"{ro} autocomplete="off" '
            f'placeholder="Step {i + 1}" aria-label="Step {i + 1}">'
        )
        hint = ""
        if ok:
            hint = f'<div class="mp-ok">{chip("Right", "ok")}</div>'
        elif missed:
            hint = (
                f'<div class="mp-bad">The step is: <span class="mp-strong">{esc(step.name)}</span>'
                " . Type it to go on.</div>"
            )
        rows.append(
            f'<div class="mp-step"><div class="mp-stepno">{i + 1}</div>'
            f'<div class="mp-stepbody small">{box}{hint}</div></div>'
        )
    intro = (
        '<p class="mp-muted">Type the steps in order, from memory, in the words of the process '
        "card. Spelling slips and a missing “a”, “an” or “the” are fine.</p>"
    )
    return card(intro + f'<div class="mp-steps">{"".join(rows)}</div>', "Say the plan")


# -- the answer ------------------------------------------------------------------------------------


def verdict_html(run: ProblemRun) -> str:
    """The note under the answer: right, right value in the wrong form, not right (with the named
    mistake), or why it couldn't be read."""
    parts: list[str] = []
    v = run.verdict
    if run.message:
        parts.append(note(esc(run.message)))
    if v is None:
        return "".join(parts)
    if v.unreadable:
        parts.append(note(esc(v.unreadable)))
    elif v.ok:
        parts.append(note('<span class="mp-strong">Right.</span>', "ok"))
    elif v.value_ok and v.forms:
        parts.append(
            note(
                f'<span class="mp-strong">Right value, but {esc("; ".join(v.forms))}.</span>'
                " Write it the way the problem asks and check again.",
                "warn",
            )
        )
    else:
        extra = f" {esc(' '.join(v.graph_problems))}" if v.graph_problems else ""
        parts.append(note(f'<span class="mp-strong">Not right yet.</span>{extra}', "bad"))
    if v.mistake is not None and not v.ok:
        name = esc(v.mistake.name or v.mistake.id)
        parts.append(
            note(f'<span class="mp-chip warn">{name}</span> {kb_html(v.mistake.message)}', "warn")
        )
    return "".join(parts)


def answer_card(run: ProblemRun) -> str:
    """The answer area: the field (or the graph's shape and points), the two choice buttons on a
    solve task, the units, and what was said about the last try."""
    locked = run.done
    ok_cls = (
        " ok"
        if run.answer_ok
        else (
            " bad"
            if run.verdict is not None and not run.verdict.ok and not run.verdict.unreadable
            else ""
        )
    )
    units = f'<span class="mp-units">{esc(run.recipe.units)}</span>' if run.recipe.units else ""
    if run.is_graph:
        pills = "".join(
            f'<button type="button" class="mp-pill{" on" if run.shape == s else ""}" '
            f'data-act="shape" data-arg="{esc(s)}">{esc(s.capitalize())}</button>'
            for s in grading.SHAPES
        )
        body = (
            '<div class="mp-choices">' + pills + "</div>"
            '<div class="mp-graph"><span class="mp-muted">Vertex</span>'
            + math_field(VERTEX_FIELD, label="Vertex", cls="small" + ok_cls)
            + '<span class="mp-muted">Another point</span>'
            + math_field(OTHER_FIELD, label="Another point", cls="small" + ok_cls)
            + "</div>"
            '<p class="mp-prompt-sub">Type each point as (x, y) with the palette.</p>'
        )
    else:
        choices = ""
        if run.offers_choices:
            choices = (
                '<div class="mp-choices">'
                + button("No solution", "choose", grading.NONE_ANSWER, disabled=locked)
                + button("All real numbers", "choose", grading.ALL_REALS_ANSWER, disabled=locked)
                + "</div>"
            )
        body = (
            '<div class="mp-answer-row">'
            f"{math_field(ANSWER_FIELD, cls=ok_cls.strip())}{units}</div>" + choices
        )
    return card(f'<div class="mp-answer">{body}{verdict_html(run)}</div>', "Your answer")


# -- help ------------------------------------------------------------------------------------------


def help_row(run: ProblemRun) -> str:
    """Hint / Why / Show step / Show answer as ghost buttons: each enabled only when it is the
    next rung of the ladder (Show answer is always there until it is used)."""
    if not run.can_help():
        return ""
    nxt = run.next_rung()
    target = run.ladder_target()
    where = ""
    if target is not None and nxt is not None:
        where = f'<span class="mp-muted">for step {target + 1}</span>'
    return (
        '<div class="mp-row">'
        + button("Hint", "help", HINT, role="ghost", disabled=nxt != HINT)
        + button("Why", "help", WHY, role="ghost", disabled=nxt != WHY)
        + button("Show step", "help", SHOW, role="ghost", disabled=nxt != SHOW)
        + button("Show answer", "help", ANSWER, role="ghost")
        + where
        + "</div>"
    )


def help_panel(run: ProblemRun) -> str:
    """Solo and reviews: what the ladder has shown so far, step by step (Esc closes it). In Faded
    the help sits under each step instead."""
    if run.mode != SOLO or not run.help_open:
        return ""
    items: list[str] = []
    for i, step in enumerate(run.problem.steps):
        pairs = _pairs(run, i)
        if pairs:
            items.append(
                f'<div class="mp-step"><div class="mp-stepno">{i + 1}</div>'
                f'<div class="mp-stepname">{esc(step.name)}</div>'
                f'<div class="mp-help">{pairs}</div></div>'
            )
    if run.answer_shown:
        items.append(
            '<div class="mp-step"><div class="mp-stepno">✓</div>'
            '<div class="mp-stepname">The answer</div>'
            f'<div class="mp-stepbody">{run.problem.answer_html}</div></div>'
        )
    if not items:
        return ""
    close = button("Close help", "close_help", role="ghost", small=True, tip="Esc")
    return card(
        f'<div class="mp-steps">{"".join(items)}</div><div class="mp-row">{close}</div>', "Help"
    )


def pad_block(run: ProblemRun) -> str:
    """The palette, whenever there is a math field to type in."""
    if run.mode in (FADED, SOLO) and not run.done:
        return pad_html()
    return ""


# -- finished -----------------------------------------------------------------------------------


def worked_solution(run: ProblemRun) -> str:
    rows = "".join(
        f'<div class="mp-step"><div class="mp-stepno">{i + 1}</div>'
        f'<div class="mp-stepname">{esc(step.name)}</div>'
        f'<div class="mp-stepbody">{worked_html(run, i)}</div></div>'
        for i, step in enumerate(run.problem.steps)
    )
    return card(f'<div class="mp-steps">{rows}</div>', "Worked solution")


def typed_answer_html(run: ProblemRun) -> str:
    """What was typed as the final answer, typeset (the last try)."""
    if run.is_graph:
        shape = run.shape.capitalize() if run.shape else "—"
        vertex = run.fields.get(VERTEX_FIELD, "")
        other = run.fields.get(OTHER_FIELD, "")
        pts = " · ".join(
            f"{label} {math_span(latex)}"
            for label, latex in (("vertex", vertex), ("another point", other))
            if latex
        )
        return esc(shape) + (f" · {pts}" if pts else "")
    latex = run.fields.get(ANSWER_FIELD, "").strip()
    return math_span(latex) if latex else '<span class="mp-muted">(a button)</span>'


def answers_card(run: ProblemRun, *, mine: bool = True) -> str:
    """Your answer (unless the answer was shown) and the key, typeset."""
    units = f' <span class="mp-muted">{esc(run.recipe.units)}</span>' if run.recipe.units else ""
    yours = ""
    if mine and not run.answer_shown:
        yours = (
            '<div class="mp-label">Your answer</div>'
            f'<div class="mp-stepbody">{typed_answer_html(run)}</div>'
        )
    key = (
        '<div class="mp-label">The answer</div>'
        f'<div class="mp-stepbody">{run.problem.answer_html}{units}</div>'
    )
    return card(yours + key)


def worked_note(run: ProblemRun) -> str:
    """One line on how it went (tries, help)."""
    bits: list[str] = []
    if run.wrong_tries:
        bits.append(f"{run.wrong_tries} wrong {'try' if run.wrong_tries == 1 else 'tries'}")
    if run.rungs:
        bits.append(f"help: {', '.join(_rung_words(run))}")
    return " · ".join(bits) if bits else "no wrong tries and no help"


def _rung_words(run: ProblemRun) -> list[str]:
    words: list[str] = []
    for r in run.rungs:
        kind, _, idx = r.partition(":")
        label = {"hint": "hint", "why": "why", "show": "show step", "answer": "show answer"}[kind]
        words.append(f"{label} {int(idx) + 1}" if idx else label)
    return words


def seconds_text(ms: int) -> str:
    s = round(ms / 1000)
    return f"{s // 60}:{s % 60:02d}" if s >= 60 else f"{s} s"


def run_fields(run: ProblemRun) -> dict[str, str]:
    """The math fields' contents to send the page (it keeps nothing across a redraw)."""
    return dict(run.fields)


def run_readonly(run: ProblemRun) -> tuple[str, ...]:
    """Fields the learner can't type in: right steps and answer, and every field once done."""
    ro: list[str] = []
    for st in run.steps:
        if st.blank and (st.ok or run.done):
            ro.append(step_field(st.index))
    if run.answer_ok or run.done:
        ro += [ANSWER_FIELD, VERTEX_FIELD, OTHER_FIELD]
    return tuple(ro)


def run_texts(run: ProblemRun) -> dict[str, str]:
    return {plan_field(i): t for i, t in run.plan_typed.items()}


def mode_body(run: ProblemRun) -> str:
    """The cards of a problem on screen, by mode (without the header and footer)."""
    parts = [problem_card(run)]
    if run.mode == STUDY:
        parts.append(steps_card(run))
        parts.append(answers_card(run, mine=False))
    elif run.mode == PLAN:
        parts.append(plan_card(run))
    elif run.mode == FADED:
        parts.append(steps_card(run))
        parts.append(answer_card(run))
        parts.append(help_row(run))
    else:
        parts.append(answer_card(run))
        parts.append(help_row(run))
        parts.append(help_panel(run))
    return "".join(parts)
