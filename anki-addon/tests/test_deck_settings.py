"""recalldrill/deck_settings.py: per-deck settings, the hints default and the
terminology proposal."""

from __future__ import annotations

from pathlib import Path

import pytest

from recalldrill import deck_settings as ds
from recalldrill.storage import DECK_SETTINGS, Storage


@pytest.fixture
def st(tmp_path: Path) -> Storage:
    return Storage(tmp_path, "User 1")


def test_sanitize_keeps_known_valid_keys_only() -> None:
    raw = {
        "strictPunctuation": True,
        "stemTolerance": "no",
        "batchSize": 8,
        "hints": False,
        "cycleOrder": "inOrder",
        "card_ords": {"123": [1, 1, 0, -1, True, "2"], "abc": [0], "456": "x"},
        "unknown": 1,
    }
    assert ds.sanitize(raw) == {
        "strictPunctuation": True,
        "batchSize": 8,
        "hints": False,
        "cycleOrder": "inOrder",
        "card_ords": {"123": [0, 1]},
    }
    assert ds.sanitize({"batchSize": True, "cycleOrder": "random"}) == {}
    assert ds.sanitize(None) == {}


def test_save_and_read_back_by_deck_id(st: Storage) -> None:
    assert ds.get_saved(st, 42) is None
    ds.save(st, 42, {"strictPunctuation": True, "card_ords": {"1700000000000": [1]}})
    ds.save(st, 7, {"batchSize": 0})
    assert ds.get_saved(st, 42) == {"strictPunctuation": True, "card_ords": {"1700000000000": [1]}}
    assert ds.get_saved(st, 7) == {"batchSize": 0}
    assert set(st.read_json(DECK_SETTINGS, {})) == {"42", "7"}


def test_resolve_fills_defaults() -> None:
    assert ds.resolve(None) == {
        "strictPunctuation": False,
        "stemTolerance": True,
        "batchSize": 5,
        "cycleOrder": "shuffled",
        "card_ords": {},
    }
    assert ds.resolve({"stemTolerance": False})["stemTolerance"] is False


def test_card_ords_option() -> None:
    assert ds.card_ords_option(None) == {}
    assert ds.card_ords_option({"card_ords": {"17": [1], "18": [0, 2]}}) == {
        17: frozenset({1}),
        18: frozenset({0, 2}),
    }


@pytest.mark.parametrize(
    ("settings", "share", "on"),
    [
        ({"hints": True}, 0.0, True),
        ({"hints": False, "strictPunctuation": True}, 1.0, False),
        ({"strictPunctuation": True}, 1.0, True),
        ({"strictPunctuation": True}, 0.6, True),
        ({"strictPunctuation": True}, 0.5, False),  # half isn't "mostly"
        ({"strictPunctuation": True}, 0.0, False),  # cloze decks
        ({"strictPunctuation": False}, 1.0, False),
        (None, 1.0, False),  # strict punctuation is off by default
    ],
)
def test_hints_default(settings: ds.DeckSettings | None, share: float, on: bool) -> None:
    assert ds.hints_enabled(settings, share) is on


def test_standard_share() -> None:
    assert ds.standard_share(["standard", "cloze", "standard", "standard"]) == 0.75
    assert ds.standard_share([]) == 0.0


@pytest.mark.parametrize(
    ("answers", "proposed"),
    [
        (["-algia", "ten/o", "crooked, bent, stiff", "a b c", "one two three four"], True),
        (["-algia", "ten/o", "a b c d", "one two three four", "x"], False),
        (["Bone tissue is formally called osseous tissue."] * 10, False),
        ([], False),
    ],
)
def test_terminology_proposal(answers: list[str], proposed: bool) -> None:
    got = ds.propose_terminology_settings(answers)
    if proposed:
        assert got == {"stemTolerance": False, "strictPunctuation": True, "hints": True}
    else:
        assert got is None


def test_effective_settings_never_save(st: Storage) -> None:
    terms = ["-algia", "ten/o", "nat/i"]
    assert ds.effective({"batchSize": 3}, terms) == ({"batchSize": 3}, "saved")
    settings, source = ds.effective(None, terms)
    assert source == "proposed" and settings.get("strictPunctuation") is True
    assert ds.effective(None, ["a long answer with many words"]) == ({}, "defaults")
    assert not st.path(DECK_SETTINGS).exists()


def test_settings_deck_for_a_search_scope() -> None:
    assert ds.settings_deck([5, 7, 7, 5, 7]) == 7
    assert ds.settings_deck([5, 7, 7, 5]) == 5  # tie: the first one met
    assert ds.settings_deck([]) is None
