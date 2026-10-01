"""Answer normalization, word-level diffing and grading. Port of ``src/utils/grading.ts``.

The TS module is the reference; this is a copy, not an improvement. Parity is
checked against recorded TS outputs in ``tests/golden/grading.json``.

========================  ==========================
TS name                   Python name
========================  ==========================
``DECIMAL_MARKER``        ``DECIMAL_MARKER``
``NEGATIVE_MARKER``       ``NEGATIVE_MARKER``
``norm``                  ``norm``
``exactMatch``            ``exact_match``
``normStrict``            ``_norm_strict``
``wordNorm``              ``_word_norm``
``alignWords``            ``_align_words``
``computeWordDiff``       ``compute_word_diff``
``STOPWORDS``             ``STOPWORDS``
``lightStem``             ``_light_stem``
``grade``                 ``grade``
========================  ==========================

TS-private functions keep a leading underscore. All JS semantics (whitespace,
trimming, splitting) come from :mod:`.jscompat`; engine patterns spell out
``[0-9]`` because Python's ``\\d`` is Unicode-wide where the TS one is ASCII.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Literal, NamedTuple

from .jscompat import JS_WS, WS_RE, is_js_ws, js_split_ws, js_trim
from .types import GradeResult, WordDiffResult

# Private-use placeholders that shield a decimal point and a leading minus sign
# from the generic punctuation strip. Same code points as the TS constants.
DECIMAL_MARKER = "\ue000"
NEGATIVE_MARKER = "\ue001"

_COMBINING_MARKS_RE = re.compile("[\u0300-\u036f]")
_DASHES_RE = re.compile("[\u2212\u2013\u2014]")  # minus, en dash, em dash
_DECIMAL_RE = re.compile("([0-9])[.,](?=[0-9])")
_NORM_STRIP_RE = re.compile("[^a-z0-9 " + DECIMAL_MARKER + NEGATIVE_MARKER + "+%<>=]")
_CURLY_QUOTES_RE = re.compile("[\u2018\u2019\u201c\u201d]")
_STRICT_IGNORED_RE = re.compile("[()\\[\\]{}\"',:;]")
_SENTENCE_END_RE = re.compile("[.!?]+(?=" + JS_WS + "|\\Z)")

_ASCII_LOWER_ALNUM = frozenset("abcdefghijklmnopqrstuvwxyz0123456789")
_ASCII_DIGITS = frozenset("0123456789")


def _mark_negatives(s: str) -> str:
    """Replaces TS ``.replace(/(?<![a-z0-9]\\s*)-\\s*(?=\\d)/g, NEGATIVE_MARKER)``.

    Python's ``re`` rejects that variable-width lookbehind, so this scans
    instead. A ``-``, plus any JS whitespace after it, becomes the marker when a
    digit follows the whitespace, unless the nearest preceding non-whitespace
    character is ``[a-z0-9]`` (that makes it a range like ``10-20``). The
    lookbehind reads the string as it was before this step, like the regex.
    """
    out: list[str] = []
    n = len(s)
    i = 0
    while i < n:
        if s[i] == "-":
            j = i + 1
            while j < n and is_js_ws(s[j]):
                j += 1
            if j < n and s[j] in _ASCII_DIGITS:
                k = i - 1
                while k >= 0 and is_js_ws(s[k]):
                    k -= 1
                if not (k >= 0 and s[k] in _ASCII_LOWER_ALNUM):
                    out.append(NEGATIVE_MARKER)
                    i = j
                    continue
        out.append(s[i])
        i += 1
    return "".join(out)


def norm(s: str) -> str:
    """Lenient normalization: accents, case and meaning-free punctuation ignored."""
    s = unicodedata.normalize("NFKD", s)
    s = _COMBINING_MARKS_RE.sub("", s)  # e-acute -> e
    s = s.lower()
    s = _DASHES_RE.sub("-", s)  # minus/en/em dash -> -
    s = _DECIMAL_RE.sub(lambda m: m.group(1) + DECIMAL_MARKER, s)  # protect decimals: 7.4
    s = _mark_negatives(s)  # protect negatives: -5 (not ranges 10-20)
    s = _NORM_STRIP_RE.sub("", s)
    s = s.replace(DECIMAL_MARKER, ".")  # TS: .split(DECIMAL_MARKER).join('.')
    s = s.replace(NEGATIVE_MARKER, "-")  # TS: .split(NEGATIVE_MARKER).join('-')
    s = WS_RE.sub(" ", s)
    return js_trim(s)


def exact_match(a: str, b: str, strict: bool = False) -> bool:
    """The exact check: spacing-insensitive on top of the deck's normalizer."""
    n = _norm_strict if strict else norm
    return n(a).replace(" ", "") == n(b).replace(" ", "")


def _norm_strict(s: str) -> str:
    """Strict normalization: only accents, case, brackets/quotes/commas/colons/
    semicolons and sentence-ending ``. ! ?`` are ignored."""
    s = unicodedata.normalize("NFKD", s)
    s = _COMBINING_MARKS_RE.sub("", s)  # accents ignored: e-acute -> e
    s = s.lower()
    s = _CURLY_QUOTES_RE.sub("'", s)  # curly quotes -> '
    s = _DASHES_RE.sub("-", s)  # minus/en/em dash -> -
    s = _STRICT_IGNORED_RE.sub("", s)  # brackets, quotes, apostrophes, commas, colons, semicolons
    s = _SENTENCE_END_RE.sub("", s)  # sentence-ending . ! ? ignored; 7.35 kept
    s = WS_RE.sub(" ", s)
    return js_trim(s)


def _word_norm(w: str, strict: bool) -> str:
    return _norm_strict(w) if strict else norm(w)


class _WordAlignment(NamedTuple):
    matched_typed_idx: list[bool]
    matched_target_idx: list[bool]
    lcs_length: int


def _align_words(
    typed_words: list[str], target_words: list[str], strict: bool = False
) -> _WordAlignment:
    """Order-preserving LCS alignment between two word lists."""
    t_n = [_word_norm(w, strict) for w in typed_words]
    g_n = [_word_norm(w, strict) for w in target_words]
    n = len(t_n)
    m = len(g_n)

    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if t_n[i - 1] == g_n[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])

    matched_typed = [False] * n
    matched_target = [False] * m
    i = n
    jj = m
    while i > 0 and jj > 0:
        if t_n[i - 1] == g_n[jj - 1]:
            matched_typed[i - 1] = True
            matched_target[jj - 1] = True
            i -= 1
            jj -= 1
        elif dp[i - 1][jj] >= dp[i][jj - 1]:
            i -= 1
        else:
            jj -= 1

    return _WordAlignment(matched_typed, matched_target, dp[n][m])


def compute_word_diff(
    typed_str: str, target_str: str, strict: bool = False
) -> list[WordDiffResult]:
    """Per target word: whether the LCS alignment matched it."""
    typed_trimmed = js_trim(typed_str)
    typed_words = js_split_ws(typed_trimmed) if typed_trimmed else []
    target_words = js_split_ws(js_trim(target_str))
    matched_target_idx = _align_words(typed_words, target_words, strict).matched_target_idx

    return [
        {"word": word, "matched": matched_target_idx[idx]} for idx, word in enumerate(target_words)
    ]


# Stopwords whose omission/insertion alone shouldn't fail a trial.
STOPWORDS = frozenset(
    {
        "a", "an", "the", "of", "to", "in", "on", "for", "and", "or", "is", "are",
        "was", "were", "that", "this", "it", "its", "as", "at", "by", "with", "from",
    }
)  # fmt: skip


def _light_stem(word: str) -> str:
    """Strips a light inflectional suffix. Deliberately shallow, not a real stemmer."""
    if word.endswith("ing") and len(word) > 4:
        return word[:-3]
    if word.endswith("ed") and len(word) > 3:
        return word[:-2]
    if word.endswith("es") and len(word) > 3:
        return word[:-2]
    if word.endswith("s") and len(word) > 2:
        return word[:-1]
    return word


def grade(
    typed: str,
    target: str,
    *,
    lenient: bool | None = None,
    stem_tolerance: bool | None = None,
    strict_punctuation: bool | None = None,
) -> GradeResult:
    """Grades ``typed`` against ``target``: exact, near or wrong.

    The options mirror TS ``opts?.x ?? default``: ``None`` means the default
    (lenient on, stem tolerance on, strict punctuation off).
    """
    lenient = True if lenient is None else lenient
    stem_tolerance = True if stem_tolerance is None else stem_tolerance
    strict = False if strict_punctuation is None else strict_punctuation

    diff = compute_word_diff(typed, target, strict)

    if exact_match(typed, target, strict):
        return {
            "verdict": "exact",
            "diff": diff,
            "missingWords": [],
            "extraWords": [],
            "similarity": 1,
        }

    typed_trimmed = js_trim(typed)
    typed_words = js_split_ws(typed_trimmed) if typed_trimmed else []
    target_words = js_split_ws(js_trim(target))
    alignment = _align_words(typed_words, target_words, strict)

    missing_words = [
        w for idx, w in enumerate(target_words) if not alignment.matched_target_idx[idx]
    ]
    extra_words = [w for idx, w in enumerate(typed_words) if not alignment.matched_typed_idx[idx]]
    total_len = len(typed_words) + len(target_words)
    similarity = (2 * alignment.lcs_length) / total_len if total_len > 0 else 0

    def result(verdict: Literal["near", "wrong"]) -> GradeResult:
        return {
            "verdict": verdict,
            "diff": diff,
            "missingWords": missing_words,
            "extraWords": extra_words,
            "similarity": similarity,
        }

    # A strict deck has no near-miss tier at all.
    if not lenient or strict:
        return result("wrong")

    def is_stopword(w: str) -> bool:
        return norm(w) in STOPWORDS

    stopword_only_difference = all(is_stopword(w) for w in missing_words) and all(
        is_stopword(w) for w in extra_words
    )
    if stopword_only_difference:
        return result("near")

    if similarity >= 0.9:

        def is_stopword_or_stem_match(w: str) -> bool:
            if is_stopword(w):
                return True
            if not stem_tolerance:
                return False
            stemmed = _light_stem(norm(w))
            return any(_light_stem(norm(e)) == stemmed for e in extra_words)

        if all(is_stopword_or_stem_match(w) for w in missing_words):
            return result("near")

    return result("wrong")
