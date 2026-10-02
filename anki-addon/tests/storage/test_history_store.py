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


# ---------------------------------------------------------------------------
# Handoff lines
# ---------------------------------------------------------------------------


def _handoff(at: str, cards: list[tuple[int, bool]], **extra: object) -> dict[str, object]:
    return {
        "type": "handoff",
        "sessionId": at,
        "timestamp": at,
        "cards": [{"cid": c, "hard": h} for c, h in cards],
        **extra,
    }


def test_append_handoff_and_declined_line(st: Storage) -> None:
    history_store.append_handoff(st, "42", _handoff("2026-10-02T10:00:00.000Z", [(1, True)]))
    declined = history_store.declined_line("s2", 1_790_000_000_000)
    assert declined == {
        "type": "handoff",
        "sessionId": "s2",
        "declined": True,
        "timestamp": "2026-09-21T14:13:20.000Z",
    }
    history_store.append_handoff(st, "42", declined)
    assert [x.get("declined", False) for x in history_store.read_all(st, "42")] == [False, True]
    with pytest.raises(ValueError, match="handoff"):
        history_store.append_handoff(st, "42", {"type": "session", "sessionId": "x"})


def test_hard_cards_latest_handoff_wins_across_logs(st: Storage) -> None:
    assert history_store.hard_cards(st) == history_store.HardCards(frozenset(), frozenset())
    history_store.append_handoff(
        st, "42", _handoff("2026-10-01T10:00:00.000Z", [(1, True), (2, True), (3, False)])
    )
    # A later handoff (another deck's log) of card 2: no longer hard.
    history_store.append_handoff(
        st, "search-abc", _handoff("2026-10-02T10:00:00.000Z", [(2, False), (4, True)])
    )
    # Declined lines and junk are ignored.
    history_store.append_handoff(
        st, "42", _handoff("2026-10-03T10:00:00.000Z", [(1, False)], declined=True)
    )
    st.append_jsonl(history_store.history_name("42"), {"type": "handoff", "cards": [{"cid": "x"}]})
    hard = history_store.hard_cards(st)
    assert hard.hard == frozenset({1, 4})
    assert hard.not_hard == frozenset({2, 3})
