"""Engine extension (add-on only): ``SessionConfig["minWordsToChunk"]``.

docs/DECISIONS.md, "Engine extensions beyond the TS engine". Absent, the engine
uses the module constant exactly as the TS engine does (the golden and simulate
parity suites run with it absent, unchanged). Set, a mid-session edit rechunks
with the session's threshold.
"""

from __future__ import annotations

from typing import Any, cast

from recalldrill.engine.estimate import compute_cold_start_estimate
from recalldrill.engine.items import MIN_WORDS_TO_CHUNK, build_items, chunk_text
from recalldrill.engine.session import edit_current_item, empty_stats, init_session
from recalldrill.engine.types import DeckItem, SessionConfig, SessionState

FIVE = "alpha beta gamma delta epsilon"
DECK: list[DeckItem] = [
    {"front": "five words", "back": FIVE},
    {"front": "two words", "back": "one two"},
]


def state(min_words: int | None) -> SessionState:
    config: SessionConfig = {
        "encodeReps": 2,
        "chunkDifficulty": 35,
        "stemTolerance": True,
        "ladderMode": "cumulative",
        "strictPunctuation": False,
        "batchSize": 0,
        "cycleOrder": "inOrder",
    }
    if min_words is not None:
        config["minWordsToChunk"] = min_words
    items = build_items(
        DECK,
        35,
        "cumulative",
        0,
        MIN_WORDS_TO_CHUNK if min_words is None else min_words,
        shuffle_within_batch=False,
    )
    return init_session(
        {
            "items": items,
            "phase": "encode",
            "queue": [],
            "stats": {**empty_stats(), "startTime": 0},
            "currentId": -1,
            "batchIndex": 0,
            "batchStartStats": empty_stats(),
            "config": config,
        }
    )


def current(s: SessionState) -> dict[str, Any]:
    return cast(dict[str, Any], next(i for i in s["items"] if i["id"] == s["currentId"]))


def without_key(s: SessionState) -> dict[str, Any]:
    out = cast(dict[str, Any], {**s, "config": dict(s["config"])})
    out["config"].pop("minWordsToChunk", None)
    return out


def test_absent_is_the_constant() -> None:
    """Absent, every edit gives what an explicit constant gives (the TS behavior)."""
    absent, explicit = state(None), state(MIN_WORDS_TO_CHUNK)
    assert without_key(absent) == without_key(explicit)
    for back in (FIVE, FIVE.upper(), "alpha beta", " ".join(["w"] * 12)):
        edit = {"front": "five words", "back": back}
        a = edit_current_item(absent, edit)  # type: ignore[arg-type]
        b = edit_current_item(explicit, edit)  # type: ignore[arg-type]
        assert a["restarted"] == b["restarted"]
        assert without_key(a["state"]) == without_key(b["state"])
        assert "minWordsToChunk" not in a["state"]["config"]


def test_edit_restart_rechunks_with_the_session_threshold() -> None:
    """A changed answer restarts the card, chunked by the session's T."""
    s = state(3)
    assert current(s)["back"] == FIVE and current(s)["chunks"] is not None  # 5 > 3
    edit = {"front": "five words", "back": "one two three four"}
    r = edit_current_item(s, edit)  # type: ignore[arg-type]
    assert r["restarted"] is True
    item = current(r["state"])
    assert item["chunks"] == chunk_text("one two three four", 35, 3) is not None
    assert item["stage"] == "chunks" and item["status"] == "encoding"
    assert r["state"]["config"].get("minWordsToChunk") == 3
    # With the TS constant, the same edit gives an unchunked card (4 <= 8).
    plain = edit_current_item(state(None), edit)  # type: ignore[arg-type]
    assert current(plain["state"])["chunks"] is None


def test_an_unchanged_answer_keeps_progress_under_the_session_threshold() -> None:
    """A case-only edit (exactMatch-equal) keeps progress when the chunk count,
    under the session's T, is unchanged; under the constant it would differ."""
    s = state(3)
    edit = {"front": "five words", "back": FIVE.upper()}
    r = edit_current_item(s, edit)  # type: ignore[arg-type]
    assert r["restarted"] is False
    item = current(r["state"])
    assert item["back"] == FIVE.upper() and item["chunks"] == chunk_text(FIVE.upper(), 35, 3)
    # The same items without the key fall back to the constant: no chunks now,
    # two before, so the card restarts.
    fallback = edit_current_item(cast(SessionState, without_key(s)), edit)  # type: ignore[arg-type]
    assert fallback["restarted"] is True and current(fallback["state"])["chunks"] is None


def test_estimate_takes_the_threshold() -> None:
    plain = compute_cold_start_estimate(DECK, 2, 35, "cumulative", "fresh")
    same = compute_cold_start_estimate(DECK, 2, 35, "cumulative", "fresh", MIN_WORDS_TO_CHUNK)
    low = compute_cold_start_estimate(DECK, 2, 35, "cumulative", "fresh", 3)
    assert plain == same
    assert low["floorTrials"] > plain["floorTrials"]  # the 5-word card is chunked at T=3
