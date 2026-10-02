"""recalldrill/prompts.py: the medterm skill's disambiguation hints, ported.

Examples are the skill's own: pain -> -algia/-dynia, tendon -> ten/o/tendin,
acute vs acute condition, birth -> nat vs natal (suppressed).
"""

from __future__ import annotations

import random

import pytest

from recalldrill.prompts import (
    HintEntry,
    auto_hint,
    compute_hints,
    find_conflicts,
    hint_extras,
    hint_suffix,
    meanings_conflict,
    parse_hint_overrides,
    words,
)


def e(key: str, term: str, meaning: str) -> HintEntry:
    return HintEntry(key, term, meaning)


def fronts(entries: list[HintEntry], overrides: dict[str, str] | None = None) -> dict[str, str]:
    """term -> front, the way the skill prints a day."""
    result = compute_hints(entries, entries, overrides or {})
    return {t.term: t.meaning + result.suffixes[t.key] for t in entries}


# ---------------------------------------------------------------------------
# The script's helpers, unchanged
# ---------------------------------------------------------------------------


def test_words_drops_stop_words_and_non_letters() -> None:
    assert words("Pertaining to the Heart, or 2 lungs") == {"pertaining", "heart", "lungs"}
    assert words("of the") == set()


@pytest.mark.parametrize(
    ("term", "others", "hint"),
    [
        ("-algia", ["-dynia"], "-a___"),
        ("-dynia", ["-algia"], "-d___"),
        ("ten/o", ["tendin/o"], "ten/___"),
        ("tendin/o", ["ten/o"], "tend___"),
        ("hyper-", ["hypo-"], "hype___-"),
        ("intra-", ["end/o"], "i___-"),
        ("nat/i", ["natal"], "nat/___"),
        ("natal", ["nat/i"], "nata___"),
        # Others are compared on their first form.
        ("cardi/o", ["cor/o, coron/o"], "ca___"),
        # The term's own first form is what gets hinted.
        ("-algia, -algesia", ["-dynia"], "-a___"),
        # No prefix tells them apart.
        ("nat", ["natal"], None),
        ("-algia", ["-algia"], None),
    ],
)
def test_auto_hint(term: str, others: list[str], hint: str | None) -> None:
    assert auto_hint(term, others) == hint


@pytest.mark.parametrize(
    ("a", "b", "conflict"),
    [
        ("pain", "pain", True),
        ("acute", "acute condition", True),
        ("acute condition", "acute", True),
        ("birth", "pertaining to birth", True),
        ("tendon", "Tendon", True),
        ("liver", "inflammation of the liver", True),
        ("heart", "pertaining to the heart muscle", False),
        ("heart", "lung", False),
        ("heart muscle", "heart valve", False),
        ("of the", "of the", False),
        ("", "pain", False),
    ],
)
def test_meanings_conflict(a: str, b: str, conflict: bool) -> None:
    assert meanings_conflict(words(a), words(b)) is conflict


# ---------------------------------------------------------------------------
# The skill's examples
# ---------------------------------------------------------------------------


def test_pain_algia_dynia() -> None:
    entries = [e("1:1", "-algia", "pain"), e("2:1", "-dynia", "pain")]
    assert fronts(entries) == {"-algia": "pain (-a___)", "-dynia": "pain (-d___)"}


def test_tendon_ten_o_tendin_o() -> None:
    entries = [e("1:1", "ten/o", "tendon"), e("2:1", "tendin/o", "tendon")]
    assert fronts(entries) == {"ten/o": "tendon (ten/___)", "tendin/o": "tendon (tend___)"}


def test_acute_vs_acute_condition() -> None:
    entries = [e("1:1", "acu/o", "acute"), e("2:1", "acut/o", "acute condition")]
    assert fronts(entries) == {"acu/o": "acute (acu/___)", "acut/o": "acute condition (acut___)"}


def test_birth_nat_vs_natal_suppressed() -> None:
    nat, natal = e("1:1", "nat/i", "birth"), e("2:1", "natal", "pertaining to birth")
    # Without overrides the one-word meaning sits inside the two-word one.
    assert fronts([nat, natal]) == {
        "nat/i": "birth (nat/___)",
        "natal": "pertaining to birth (nata___)",
    }
    # "" suppresses the auto hint, per card.
    assert fronts([nat, natal], {"1:1": "", "2:1": ""}) == {
        "nat/i": "birth",
        "natal": "pertaining to birth",
    }
    assert fronts([nat, natal], {"2:1": ""}) == {
        "nat/i": "birth (nat/___)",
        "natal": "pertaining to birth",
    }


def test_manual_hint_replaces_the_auto_hint_and_needs_no_conflict() -> None:
    entries = [e("1:1", "-algia", "pain"), e("2:1", "-dynia", "pain"), e("3:1", "my/o", "muscle")]
    got = fronts(entries, {"1:1": "1 word", "3:1": "m_/o"})
    assert got == {"-algia": "pain (1 word)", "-dynia": "pain (-d___)", "my/o": "muscle (m_/o)"}


def test_n_forms() -> None:
    entries = [e("1:0", "crooked, bent, stiff", "ankyl/o")]
    assert fronts(entries) == {"crooked, bent, stiff": "ankyl/o (3 forms)"}


def test_n_forms_comes_first_and_blocks_auto_hints_only() -> None:
    entries = [e("1:1", "-algia, -algesia", "pain"), e("2:1", "-dynia", "pain")]
    result = compute_hints(entries, entries, {})
    # A multi-form term in a conflict gets no auto hint and isn't flagged...
    assert result.suffixes["1:1"] == " (2 forms)"
    assert result.flagged == []
    # ...but a manual hint still joins it, after "N forms", as the skill writes it.
    result = compute_hints(entries, entries, {"1:1": "-alg___"})
    assert result.suffixes["1:1"] == " (2 forms; -alg___)"


def test_unresolvable_conflict_is_flagged_and_suppression_clears_it() -> None:
    nat, natal = e("1:1", "nat", "birth"), e("2:1", "natal", "birth")
    result = compute_hints([nat, natal], [nat, natal], {})
    assert result.suffixes == {"1:1": "", "2:1": " (nata___)"}
    assert result.flagged == [nat]
    assert result.conflicts["1:1"] == ["natal"]
    result = compute_hints([nat, natal], [nat, natal], {"1:1": ""})
    assert result.flagged == []


# ---------------------------------------------------------------------------
# Pool vs targets (add-on adaptations)
# ---------------------------------------------------------------------------


def test_earlier_chapters_in_the_pool_count() -> None:
    earlier = e("1:1", "-algia", "pain")
    today = e("2:1", "-dynia", "pain")
    result = compute_hints([today], [earlier, today], {})
    assert result.suffixes == {"2:1": " (-d___)"}  # only targets get hints


def test_same_term_never_conflicts() -> None:
    # The same word part in two chapters: typing it is right for both.
    a, b = e("1:1", "-algia", "pain"), e("2:1", "-algia", "pain")
    result = compute_hints([a, b], [a, b], {})
    assert result.suffixes == {"1:1": "", "2:1": ""}
    assert result.flagged == []


def test_a_card_never_conflicts_with_itself() -> None:
    a = e("1:1", "-algia", "pain")
    assert find_conflicts([a], [a]) == {"1:1": []}


def _pairwise(targets: list[HintEntry], pool: list[HintEntry]) -> dict[str, list[str]]:
    """The script's O(n^2) loop, per card."""
    out: dict[str, list[str]] = {}
    for t in targets:
        out[t.key] = sorted(
            p.term
            for p in pool
            if p.key != t.key
            and p.term != t.term
            and meanings_conflict(words(t.meaning), words(p.meaning))
        )
    return out


def test_find_conflicts_matches_the_pairwise_rule() -> None:
    rng = random.Random(7)
    vocab = ["pain", "of", "the", "heart", "birth", "acute", "muscle", "condition", "to", "x"]
    for _ in range(40):
        pool = [
            e(
                f"{i}:1",
                rng.choice(["-algia", "-dynia", "card/o", "nat/i", "my/o", "acu/o"]),
                " ".join(rng.choice(vocab) for _ in range(rng.randint(0, 4))),
            )
            for i in range(30)
        ]
        targets = rng.sample(pool, 10)
        fast = {k: sorted(v) for k, v in find_conflicts(targets, pool).items()}
        assert fast == _pairwise(targets, pool)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def test_hint_extras_and_suffix() -> None:
    assert hint_extras("ten/o", ["tendin/o"], None) == (["ten/___"], False)
    assert hint_extras("nat", ["natal"], None) == ([], True)
    assert hint_extras("ten/o", [], None) == ([], False)
    assert hint_suffix([]) == ""
    assert hint_suffix(["2 forms", "a___"]) == " (2 forms; a___)"


def test_parse_hint_overrides() -> None:
    assert parse_hint_overrides({"1:0": "a___", "2:0": "", "3:0": 5, "4:0": None}) == {
        "1:0": "a___",
        "2:0": "",
    }
    assert parse_hint_overrides(["x"]) == {}
    assert parse_hint_overrides(None) == {}
