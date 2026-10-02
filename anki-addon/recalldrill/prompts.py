"""Disambiguation hints for prompts (pure).

A port of the ``medterm-daily-drill`` skill's build script: ``words``,
``auto_hint``, the meaning-conflict rule, the ``"N forms"`` rule and the
suppression semantics are copied as they are. "term" is the typed answer,
"meaning" is the prompt.

What differs from the script, because the add-on reads Anki cards instead of
one day's term list:

- Cards, not terms, are the keys. Conflicts are found per card, and manual
  overrides (``hints.json``) are keyed by ``"<note id>:<ord>"``.
- Conflicts are looked for across a *pool* (every eligible card of the same
  note type and template under the deck's top level, so earlier chapters
  count), but hints are only made for the session's cards (the *targets*).
- Two cards with the same term never conflict: typing that term is right for
  both prompts, so there is nothing to disambiguate. (The script never met
  this: it deduplicated within one day.)
- No card is dropped. The script skipped a repeated (front, term) pair.

Front format, as the script writes it: ``meaning (N forms; hint)``.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import cast

STOP = {"or", "and", "the", "of", "to", "a", "an", "in"}


def words(m: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", m.lower()) if w not in STOP}


def auto_hint(term: str, others: Sequence[str]) -> str | None:
    t = term.split(",")[0].strip()
    for k in range(1, len(t) + 1):
        if all(not o.split(",")[0].strip().startswith(t[:k]) for o in others):
            return (
                t[:k].rstrip("-")
                + "___"
                + ("-" if t.endswith("-") and not t.startswith("-") else "")
            )
    return None


def meanings_conflict(wa: set[str] | frozenset[str], wb: set[str] | frozenset[str]) -> bool:
    """The script's pair rule: identical word sets, or a one-word meaning inside
    a two-word one (stop words left out)."""
    small, big = sorted((wa, wb), key=len)
    return bool(wa and wb and (wa == wb or (small <= big and len(big) <= 2)))


@dataclass(frozen=True)
class HintEntry:
    key: str
    """``"<note id>:<ord>"``."""
    term: str
    """The typed answer (grading text)."""
    meaning: str
    """The prompt (grading text of the rendered front)."""


@dataclass
class HintResult:
    suffixes: dict[str, str] = field(default_factory=dict[str, str])
    """Target key -> ``" (...)"`` to append to the front, or ``""``."""
    flagged: list[HintEntry] = field(default_factory=list[HintEntry])
    """Targets in a conflict that no auto hint can resolve: they need a manual hint."""
    conflicts: dict[str, list[str]] = field(default_factory=dict[str, list[str]])
    """Target key -> the conflicting pool terms."""


def find_conflicts(targets: Sequence[HintEntry], pool: Sequence[HintEntry]) -> dict[str, list[str]]:
    """For each target, the terms of pool entries whose meaning conflicts with it.

    Same result as checking every (target, pool entry) pair with
    :func:`meanings_conflict`, in linear time: a conflict is either the same
    word set, or a one-word set inside a two-word set. Pool entries with the
    target's own key or term are skipped.
    """
    by_set: dict[frozenset[str], list[HintEntry]] = defaultdict(list)
    for e in pool:
        ws = frozenset(words(e.meaning))
        if ws:
            by_set[ws].append(e)
    pairs_with_word: dict[str, list[frozenset[str]]] = defaultdict(list)
    for ws in by_set:
        if len(ws) == 2:
            for w in ws:
                pairs_with_word[w].append(ws)

    out: dict[str, list[str]] = {}
    for t in targets:
        ws = frozenset(words(t.meaning))
        found: list[HintEntry] = []
        if ws:
            found.extend(by_set.get(ws, ()))
            if len(ws) == 1:
                (w,) = ws
                for pair in pairs_with_word.get(w, ()):
                    found.extend(by_set[pair])
            elif len(ws) == 2:
                for w in sorted(ws):
                    found.extend(by_set.get(frozenset((w,)), ()))
        out[t.key] = [e.term for e in found if e.key != t.key and e.term != t.term]
    return out


def hint_extras(
    term: str, conflicts: Sequence[str], override: str | None
) -> tuple[list[str], bool]:
    """(extras, needs a manual hint). ``override``: None = no manual hint stored;
    ``""`` = suppress the auto hint; any other string replaces it."""
    extras: list[str] = []
    parts = [p.strip() for p in term.split(",")]
    if len(parts) > 1:
        extras.append(f"{len(parts)} forms")
    if override is not None:
        if override:
            extras.append(override)
    elif conflicts and len(parts) == 1:
        h = auto_hint(term, conflicts)
        if h:
            extras.append(h)
        else:
            return extras, True
    return extras, False


def hint_suffix(extras: Sequence[str]) -> str:
    return f" ({'; '.join(extras)})" if extras else ""


def compute_hints(
    targets: Sequence[HintEntry],
    pool: Sequence[HintEntry],
    overrides: Mapping[str, str],
) -> HintResult:
    """Hints for ``targets``, with conflicts looked up in ``pool`` (which should
    include the targets). ``overrides``: hints.json, ``"<nid>:<ord>"`` -> hint."""
    conflicts = find_conflicts(targets, pool)
    result = HintResult(conflicts=conflicts)
    for t in targets:
        extras, flagged = hint_extras(t.term, conflicts[t.key], overrides.get(t.key))
        result.suffixes[t.key] = hint_suffix(extras)
        if flagged:
            result.flagged.append(t)
    return result


def parse_hint_overrides(data: object) -> dict[str, str]:
    """hints.json ``data`` -> overrides; anything that isn't ``str: str`` is dropped."""
    if not isinstance(data, dict):
        return {}
    return {
        k: v
        for k, v in cast(dict[object, object], data).items()
        if isinstance(k, str) and isinstance(v, str)
    }
