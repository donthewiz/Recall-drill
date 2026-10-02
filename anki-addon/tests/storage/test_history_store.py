"""history_store.py: cold-start estimates (the web app's cold-start history)."""

from __future__ import annotations

from pathlib import Path

import pytest

from recalldrill import history_store
from recalldrill.storage import ESTIMATES, Storage


@pytest.fixture
def st(tmp_path: Path) -> Storage:
    return Storage(tmp_path / "user_files", "User 1")


def test_cold_start_history_round_trip(st: Storage) -> None:
    assert history_store.get_cold_start_history(st, "deck-1") is None
    entry: history_store.ColdStartHistory = {
        "multiplier": 1.8,
        "deckShape": "chunked",
        "measuredAt": "2026-10-02T04:00:00.000Z",
    }
    assert history_store.save_cold_start_history(st, "deck-1", entry)
    assert history_store.save_cold_start_history(st, "deck-2", {**entry, "multiplier": 2})
    assert history_store.get_cold_start_history(st, "deck-1") == entry
    assert history_store.get_cold_start_history(st, "deck-2")["multiplier"] == 2.0  # type: ignore[index]
    # An empty key (TS: empty slug) neither reads nor writes.
    assert history_store.get_cold_start_history(st, "") is None
    assert not history_store.save_cold_start_history(st, "", entry)


@pytest.mark.parametrize(
    "bad",
    [
        "x",
        {"multiplier": "2", "deckShape": "full", "measuredAt": "t"},
        {"multiplier": True, "deckShape": "full", "measuredAt": "t"},
        {"multiplier": 2, "deckShape": "huge", "measuredAt": "t"},
        {"multiplier": 2, "deckShape": "full"},
    ],
)
def test_bad_estimates_read_as_none(st: Storage, bad: object) -> None:
    st.write_json(ESTIMATES, {"deck-1": bad})
    assert history_store.get_cold_start_history(st, "deck-1") is None


def test_estimates_file_that_isnt_a_dict(st: Storage) -> None:
    st.write_json(ESTIMATES, [1])
    assert history_store.get_cold_start_history(st, "deck-1") is None
    history_store.save_cold_start_history(
        st, "deck-1", {"multiplier": 1, "deckShape": "full", "measuredAt": "t"}
    )
    assert st.read_json(ESTIMATES, None) == {
        "deck-1": {"multiplier": 1, "deckShape": "full", "measuredAt": "t"}
    }
