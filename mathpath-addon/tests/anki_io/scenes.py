"""Scratch decks shaped like the real College Algebra course (Chapter 3), for the Anki I/O tests."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from anki.collection import Collection
from recipe_files import CH03

COURSE = "College Algebra"
CHAPTER = "College Algebra::Ch 03 Quadratic Functions and Equations"
SECTIONS: dict[str, str] = {
    "3.1": "3.1 The Complex Numbers",
    "3.2": "3.2 Quadratic Equations, Functions, Zeros, and Models",
    "3.3": "3.3 Analyzing Graphs of Quadratic Functions",
    "3.4": "3.4 Solving Rational Equations and Radical Equations",
    "3.5": "3.5 Solving Equations and Inequalities with Absolute Value",
}


@dataclass
class Course:
    decks: dict[str, int] = field(default_factory=dict[str, int])
    """Section number -> deck id."""
    top: int = 0
    chapter: int = 0


def make_course(col: Collection, sections: Sequence[str] = tuple(SECTIONS)) -> Course:
    course = Course()
    course.top = int(col.decks.id(COURSE) or 0)
    course.chapter = int(col.decks.id(CHAPTER) or 0)
    for number in sections:
        name = f"{CHAPTER}::{SECTIONS[number]}"
        course.decks[number] = int(col.decks.id(name) or 0)
    return course


def recipe_dir(tmp_path: Path, *, limit: int | None = None) -> Path:
    """A folder holding copies of the Chapter 3 recipe files (the first ``limit``)."""
    out = tmp_path / "recipes"
    out.mkdir(exist_ok=True)
    files = sorted(CH03.glob("*.json"))
    for p in files[:limit]:
        (out / p.name).write_bytes(p.read_bytes())
    return out
