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


def test_tuning_lines_and_every_log(st: Storage) -> None:
    history_store.append_session(st, "42", {"type": "session", "sessionId": "a"})
    history_store.append_handoff(st, "search-abc", {"type": "handoff", "sessionId": "a"})
    line = {"type": "tuning", "parameter": "encode_reps", "old": 3, "new": 2}
    history_store.append_tuning(st, line)
    assert history_store.read_all(st, history_store.TUNING_KEY) == [line]
    every = history_store.read_every_log(st)
    assert sorted(x["type"] for x in every) == ["handoff", "session", "tuning"]
    with pytest.raises(ValueError):
        history_store.append_tuning(st, {"type": "session"})
    # The rd::hard reader ignores tuning lines.
    assert history_store.hard_cards(st).hard == frozenset()


def test_handed_off_at(st: Storage) -> None:
    """The never-studied groups of every handoff in every log, with the latest
    handoff's time per card; declined handoffs, already-scheduled drilled cards,
    skipped and missing cards don't count."""
    groups = {
        "drilled_new": [1, 2],
        "drilled_scheduled": [3],
        "siblings": [4],
        "holdout": [5],
        "holdout_siblings": [6],
        "holdout_skipped": [7],
        "missing": [8],
    }
    first = "2026-10-01T15:00:00.000Z"
    later = "2026-10-03T15:00:00.000Z"
    history_store.append_handoff(
        st, "10", {"type": "handoff", "sessionId": "a", "timestamp": first, "groups": groups}
    )
    history_store.append_handoff(
        st,
        "20",
        {
            "type": "handoff",
            "sessionId": "b",
            "timestamp": later,
            "groups": {"drilled_new": [9, 1]},
        },
    )
    history_store.append_handoff(
        st, "20", {"type": "handoff", "sessionId": "e", "groups": {"siblings": [10, True]}}
    )
    history_store.append_handoff(st, "20", history_store.declined_line("c", 0))
    history_store.append_handoff(
        st, "20", {"type": "handoff", "sessionId": "d", "declined": True, "groups": groups}
    )
    t1, t3 = 1_790_866_800_000, 1_791_039_600_000
    assert history_store.handed_off_at(st) == {
        1: t3,  # handed off twice: the later time
        2: t1,
        4: t1,
        5: t1,
        6: t1,
        9: t3,
        10: 0,  # no timestamp: any later rating releases it
    }
