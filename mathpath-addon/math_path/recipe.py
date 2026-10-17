"""A problem recipe as typed data (pure).

The file format is ``docs/recipe-format.md`` (``mathpath-recipe/1`` and ``/2``). Only the keys
Math Path shows or compares are typed here; the whole decoded JSON stays in ``Recipe.raw`` for
the copied checker, which reads it as it always has.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

FORMATS: tuple[str, ...] = ("mathpath-recipe/1", "mathpath-recipe/2")
KINDS: tuple[str, ...] = (
    "list",
    "expr",
    "equation",
    "interval",
    "point",
    "none",
    "all_reals",
    "graph",
)
PRIORITIES: tuple[str, ...] = ("high", "medium", "low")
UNBLANKABLE_CHECKS: frozenset[str] = frozenset({"text", "substitution"})
"""Steps with these checks have nothing to type: they are shown as instructions."""

REQUIRED_KEYS: tuple[str, ...] = (
    "format",
    "id",
    "version",
    "title",
    "section",
    "params",
    "problem",
    "steps",
    "answer",
    "hints",
)


class RecipeError(ValueError):
    """The recipe can't be used; ``str(exc)`` is the reason, in plain words."""


@dataclass(frozen=True)
class Step:
    name: str
    result: str
    """The worked result as a template (keyboard form); empty for a step with nothing to compute."""
    check: str
    show: str
    """How the step is displayed when it differs from ``result``; else ``""``."""
    raw: Mapping[str, Any]

    @property
    def blankable(self) -> bool:
        """Faded can ask for this step: it has a result to type and a check that grades it."""
        return bool(self.result.strip()) and self.check not in UNBLANKABLE_CHECKS


@dataclass(frozen=True)
class Hint:
    step: str
    hint: str
    why: str


@dataclass(frozen=True)
class Mistake:
    id: str
    name: str
    message: str
    rule: Mapping[str, Any]
    applies_if: str


@dataclass(frozen=True, eq=False)
class Recipe:
    """Compared and hashed by identity (it holds the decoded JSON)."""

    raw: Mapping[str, Any]
    id: str
    version: int
    format: str
    title: str
    course: str
    section_number: str
    section_title: str
    priority: str
    prerequisites: tuple[str, ...]
    steps: tuple[Step, ...]
    hints: Mapping[str, Hint]
    mistakes: tuple[Mistake, ...]
    task: str
    kind: str
    forms: tuple[str, ...]
    units: str

    def hint_for(self, step: Step) -> Hint | None:
        return self.hints.get(step.name)

    @property
    def blank_steps(self) -> tuple[int, ...]:
        """Indexes of the steps Faded can blank."""
        return tuple(i for i, s in enumerate(self.steps) if s.blankable)

    @property
    def priority_rank(self) -> int:
        """0 for high, 1 medium, 2 low (anything else counts as medium)."""
        return PRIORITIES.index(self.priority) if self.priority in PRIORITIES else 1


def _str(d: Mapping[str, Any], key: str, default: str = "") -> str:
    v = d.get(key, default)
    return v if isinstance(v, str) else default


def _mapping(v: Any) -> Mapping[str, Any] | None:
    return cast(Mapping[str, Any], v) if isinstance(v, dict) else None


def parse_recipe(data: Any) -> Recipe:
    """Type a decoded recipe, or raise :class:`RecipeError` saying what is wrong."""
    d = _mapping(data)
    if d is None:
        raise RecipeError("not a recipe (the file is not a JSON object)")
    fmt = d.get("format")
    if fmt not in FORMATS:
        raise RecipeError(f"format {fmt!r} is not one Math Path reads ({', '.join(FORMATS)})")
    missing = [k for k in REQUIRED_KEYS if k not in d]
    if missing:
        raise RecipeError("missing " + ", ".join(missing))
    rid = d["id"]
    if not isinstance(rid, str) or not rid.strip():
        raise RecipeError("id must be a non-empty string")
    version = d["version"]
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise RecipeError("version must be a whole number, 1 or more")
    section = _mapping(d["section"])
    if section is None or not _str(section, "number"):
        raise RecipeError("section needs a number (for example 3.2)")
    problem = _mapping(d["problem"])
    answer = _mapping(d["answer"])
    if problem is None or not _str(problem, "prompt"):
        raise RecipeError("problem needs a prompt")
    if answer is None or not isinstance(answer.get("value"), str):
        raise RecipeError("answer needs a value")
    kind = _str(answer, "kind", "list")
    if kind not in KINDS:
        raise RecipeError(f"answer kind {kind!r} is not one Math Path reads")
    steps_raw = d["steps"]
    if not isinstance(steps_raw, list) or not steps_raw:
        raise RecipeError("steps must be a list with at least one step")
    steps: list[Step] = []
    for s in cast(list[Any], steps_raw):
        sm = _mapping(s)
        if sm is None or not _str(sm, "name") or not _str(sm, "check"):
            raise RecipeError("every step needs a name and a check")
        steps.append(
            Step(_str(sm, "name"), _str(sm, "result"), _str(sm, "check"), _str(sm, "show"), sm)
        )
    hints: dict[str, Hint] = {}
    for h in cast(list[Any], d["hints"] if isinstance(d["hints"], list) else []):
        hm = _mapping(h)
        if hm is not None and _str(hm, "step"):
            hints[_str(hm, "step")] = Hint(_str(hm, "step"), _str(hm, "hint"), _str(hm, "why"))
    mistakes: list[Mistake] = []
    for m in cast(list[Any], d.get("mistakes") if isinstance(d.get("mistakes"), list) else []):
        mm = _mapping(m)
        rule = _mapping(mm.get("rule")) if mm is not None else None
        if mm is not None and rule is not None and _str(mm, "id"):
            mistakes.append(
                Mistake(
                    _str(mm, "id"),
                    _str(mm, "name"),
                    _str(mm, "message"),
                    rule,
                    _str(mm, "applies_if"),
                )
            )
    prereq = d.get("prerequisites")
    prerequisites = tuple(
        p for p in cast(list[Any], prereq if isinstance(prereq, list) else []) if isinstance(p, str)
    )
    forms_raw = answer.get("form")
    forms = tuple(
        f
        for f in cast(list[Any], forms_raw if isinstance(forms_raw, list) else [])
        if isinstance(f, str)
    )
    units = answer.get("units")
    if isinstance(units, list):
        units_text = ", ".join(str(u) for u in cast(list[Any], units))
    else:
        units_text = units if isinstance(units, str) else ""
    return Recipe(
        raw=d,
        id=rid.strip(),
        version=version,
        format=cast(str, fmt),
        title=_str(d, "title"),
        course=_str(d, "course"),
        section_number=_str(section, "number").strip(),
        section_title=_str(section, "title"),
        priority=_str(d, "priority", "medium"),
        prerequisites=prerequisites,
        steps=tuple(steps),
        hints=hints,
        mistakes=tuple(mistakes),
        task=_str(problem, "task", "solve"),
        kind=kind,
        forms=forms,
        units=units_text,
    )


def loads_recipe(text: str) -> Recipe:
    """Decode JSON text and type it (:class:`RecipeError` for either failure)."""
    try:
        data: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RecipeError(f"not valid JSON ({exc.msg} at line {exc.lineno})") from exc
    return parse_recipe(data)
