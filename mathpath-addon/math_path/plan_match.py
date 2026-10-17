"""Matching a typed step name against the recipe's (the Plan stage; pure).

The plan is typed from memory in the same words as the Recall Drill process card. Both texts are
normalised (lower case, punctuation dropped, the words "a", "an" and "the" dropped, spaces
collapsed) and a typed name is right when it equals the step's name or is within the
Damerau-Levenshtein distance ``max(1, len // 8)`` of it (``len`` is the normalised name's length).
Order matters: box ``k`` is graded against step ``k``.
"""

from __future__ import annotations

import re
import unicodedata

_DROPPED_WORDS = frozenset({"a", "an", "the"})
_APOSTROPHES = "'’‘`"


def normalize(text: str) -> str:
    """Lower case, punctuation dropped (apostrophes vanish, other marks separate words), the words
    "a", "an" and "the" dropped, spaces collapsed."""
    t = unicodedata.normalize("NFKC", text).casefold()
    for ch in _APOSTROPHES:
        t = t.replace(ch, "")
    t = "".join(c if (c.isalnum() or c.isspace()) else " " for c in t)
    words = [w for w in re.split(r"\s+", t) if w and w not in _DROPPED_WORDS]
    return " ".join(words)


def damerau_levenshtein(a: str, b: str) -> int:
    """The edit distance counting an insertion, a deletion, a substitution and the swap of two
    neighbouring characters as one edit each (the unrestricted Damerau-Levenshtein distance)."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    last_seen: dict[str, int] = {}
    inf = len(a) + len(b)
    # d has an extra first row and column of "infinity" so a transposition can look back.
    d = [[0] * (len(b) + 2) for _ in range(len(a) + 2)]
    d[0][0] = inf
    for i in range(len(a) + 1):
        d[i + 1][0] = inf
        d[i + 1][1] = i
    for j in range(len(b) + 1):
        d[0][j + 1] = inf
        d[1][j + 1] = j
    for i in range(1, len(a) + 1):
        last_match_col = 0
        for j in range(1, len(b) + 1):
            i1 = last_seen.get(b[j - 1], 0)
            j1 = last_match_col
            cost = 1
            if a[i - 1] == b[j - 1]:
                cost = 0
                last_match_col = j
            d[i + 1][j + 1] = min(
                d[i][j] + cost,  # substitution
                d[i + 1][j] + 1,  # insertion
                d[i][j + 1] + 1,  # deletion
                d[i1][j1] + (i - i1 - 1) + 1 + (j - j1 - 1),  # transposition
            )
        last_seen[a[i - 1]] = i
    return d[len(a) + 1][len(b) + 1]


def tolerance(name: str) -> int:
    """How many edits a typed step name may be away from the (normalised) step name."""
    return max(1, len(normalize(name)) // 8)


def matches(typed: str, name: str) -> bool:
    """Is ``typed`` right for the step called ``name``? An empty box never is."""
    a, b = normalize(typed), normalize(name)
    if not a or not b:
        return False
    return a == b or damerau_levenshtein(a, b) <= max(1, len(b) // 8)
