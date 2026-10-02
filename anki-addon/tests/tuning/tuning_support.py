"""History lines and revlog rows in the shapes the add-on writes, for the
tuning report's tests (``history_store.build_session_line`` and
``anki_io/handoff.handoff_line`` make the real ones; the end-to-end test in
``tests/anki_io/test_tuning_e2e.py`` checks they agree)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from recalldrill.engine.jscompat import js_iso_string
from recalldrill.measure import RevlogRow

ROLLOVER = 4


def ms(y: int, mo: int, d: int, h: int = 12, mi: int = 0) -> int:
    return int(datetime(y, mo, d, h, mi, tzinfo=UTC).timestamp() * 1000)


@dataclass(frozen=True)
class Drilled:
    cid: int
    words: int = 2
    chunks: int = 0
    attempts: int = 6
    misses: int = 0
    reveals: int = 0
    card_class: str = "suspended_new"
    final_misses: int = 0

    @property
    def nid(self) -> int:
        return self.cid + 1_000_000


def session_line(
    sid: str,
    started: int,
    cards: Sequence[Drilled],
    *,
    encode_reps: int = 3,
    t: int = 8,
    holdout: Sequence[int] = (),
    did: int = 1,
    minutes: int = 20,
) -> dict[str, Any]:
    return {
        "type": "session",
        "sessionId": sid,
        "startedAt": js_iso_string(started),
        "finishedAt": js_iso_string(started + minutes * 60_000),
        "stats": {"attempts": sum(c.attempts for c in cards), "misses": 0, "nearMisses": 0},
        "config": {"encodeReps": encode_reps, "chunkDifficulty": 35, "ladderMode": "cumulative"},
        "cards": [
            {
                "front": f"front {c.cid}",
                "words": c.words,
                "chunks": c.chunks,
                "attempts": c.attempts,
                "misses": c.misses,
                "reveals": c.reveals,
                "nearMisses": 0,
                "finalMisses": c.final_misses,
                "hardSpans": [],
            }
            for c in cards
        ],
        "anki": [
            {"cid": c.cid, "nid": c.nid, "ord": 0, "did": did, "card_class": c.card_class}
            for c in cards
        ],
        "encode": {
            "encodeReps": encode_reps,
            "chunkDifficulty": 35,
            "MIN_WORDS_TO_CHUNK": t,
            "ladderMode": "cumulative",
            "strictPunctuation": True,
            "stemTolerance": False,
            "hints": True,
        },
        "scope": {"deckId": did, "search": None},
        "collisions": 0,
        "holdout": [
            {"cid": h, "nid": h + 1_000_000, "ord": 0, "did": did, "card_class": "suspended_new"}
            for h in holdout
        ],
    }


def handoff_line(
    sid: str,
    at: int,
    cards: Sequence[Drilled],
    *,
    holdout: Sequence[int] = (),
    mode: str = "B",
) -> dict[str, Any]:
    return {
        "type": "handoff",
        "sessionId": sid,
        "mode": mode,
        "timestamp": js_iso_string(at),
        "groups": {
            "drilled_new": [c.cid for c in cards],
            "drilled_scheduled": [],
            "siblings": [],
            "holdout": list(holdout),
            "holdout_siblings": [],
            "holdout_skipped": [],
            "missing": [],
        },
        "cards": [
            {
                "cid": c.cid,
                "nid": c.nid,
                "ord": 0,
                "struggle": c.misses + c.reveals + c.final_misses,
                "finalMisses": c.final_misses,
                "chunked": c.chunks > 0,
                "hard": c.misses + c.reveals + c.final_misses >= 3,
            }
            for c in cards
        ],
    }


def rating(cid: int, at: int, ease: int = 3, type_: int = 0) -> RevlogRow:
    return RevlogRow(id=at, cid=cid, ease=ease, type=type_)
