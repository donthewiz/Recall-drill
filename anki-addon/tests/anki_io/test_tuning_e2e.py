"""The tuning report end to end on a scratch collection: real session and
handoff lines (with a holdout), revlog rows written at chosen times, the
revlog join (``anki_io/revlog.py``) and ``tuning.build_report``."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# anki.collection must load before anki.cards (circular import).
import anki.collection  # noqa: F401
from anki.cards import Card
from anki.collection import Collection
from anki.decks import DeckId
from anki_fixtures import add_note, deck

from recalldrill import deck_settings, history_store, sessions
from recalldrill.anki_io.handoff import HandoffSettings, apply_handoff, handoff_line, plan_handoff
from recalldrill.anki_io.revlog import (
    BATCH,
    card_decks,
    encode_reps_overrides,
    read_report_inputs,
    read_revlog,
)
from recalldrill.engine.types import DeckItem
from recalldrill.measure import RevlogRow
from recalldrill.sources import SourceRef, source_to_json
from recalldrill.storage import Storage
from recalldrill.tuning import CardInfo, ReportSettings, build_report

DAY = 86_400_000


def basic(col: Collection, did: DeckId, front: str) -> Card:
    return add_note(col, "Basic", did, {"Front": front, "Back": f"ans {front}"}).cards()[0]


def add_revlog(col: Collection, cid: int, at_ms: int, ease: int, type_: int = 0) -> None:
    assert col.db is not None
    col.db.execute(
        "insert into revlog (id, cid, usn, ease, ivl, lastIvl, factor, time, type) "
        "values (?, ?, -1, ?, 1, 0, 0, 5000, ?)",
        at_ms,
        cid,
        ease,
        type_,
    )


def source(c: Card) -> SourceRef:
    return SourceRef(
        cid=c.id, nid=c.nid, ord=c.ord, did=c.did, ntid=0, card_class="suspended_new", flags=0,
        front_html="", extra_html="", answer_hash="", has_audio=False, answer_html="", css="",
        image_front=False,
    )  # fmt: skip


def finished_session(
    col: Collection, drilled: list[Card], holdout: list[Card], started: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    """(session line, save) for a finished session over ``drilled``."""
    items: list[DeckItem] = [{"front": f"f{i}", "back": "ans"} for i in range(len(drilled))]
    state = sessions.new_session_state(
        items,
        {
            "encodeReps": 2,
            "chunkDifficulty": 35,
            "stemTolerance": False,
            "ladderMode": "cumulative",
            "strictPunctuation": True,
            "batchSize": 0,
            "minWordsToChunk": 8,
        },
        started,
    )
    for it in state["items"]:
        it.update({"finalDone": True, "status": "mastered", "attempts": 4})  # type: ignore[typeddict-item]
    srcs = [source(c) for c in drilled]
    refs = [
        {"cid": c.id, "nid": c.nid, "ord": c.ord, "did": c.did, "card_class": "suspended_new"}
        for c in holdout
    ]
    line = history_store.build_session_line(
        session_id="s1",
        state=state,
        sources=srcs,
        finished_at=started + 600_000,
        scope={"deckId": drilled[0].did, "search": None},
        collisions=0,
        hints=True,
        holdout=refs,
    )
    saved = {
        "items": state["items"],
        "addon": {
            "sessionId": "s1",
            "sources": [source_to_json(s) for s in srcs],
            "scope": {"deckId": drilled[0].did, "search": None},
            "handoffPending": True,
            "holdout": refs,
        },
    }
    return line, saved


def test_report_from_a_real_handoff(col: Collection, tmp_path: Path) -> None:
    ch1 = deck(col, "Med Term::Ch 1")
    ch0 = deck(col, "Med Term::Ch 0")
    other = deck(col, "Other")
    cards = [basic(col, ch1, f"t{i}") for i in range(6)]
    col.sched.suspend_cards([c.id for c in cards])
    drilled, holdout = cards[:4], cards[4:]
    old = [basic(col, ch0, f"old{i}") for i in range(2)]
    elsewhere = basic(col, other, "x")

    noon = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
    t0 = int((noon - timedelta(days=10)).timestamp() * 1000)
    line, saved = finished_session(col, drilled, holdout, t0 - 3_600_000)
    plan = plan_handoff(col, saved, HandoffSettings(mode="B"))
    assert plan.holdout == tuple(c.id for c in holdout)
    apply_handoff(col, plan)
    st = Storage(tmp_path / "user_files", "User 1")
    history_store.append_session(st, str(ch1), line)
    history_store.append_handoff(st, str(ch1), handoff_line(plan, None, t0))

    # Next day: two drilled cards Again, one Good; one never studied (pending).
    for i, (c, ease) in enumerate(zip(drilled[:3], (1, 1, 3), strict=True)):
        add_revlog(col, c.id, t0 + DAY + 60_000 + i, ease)
    # Holdout: introduced the next day, rated the day after.
    for i, c in enumerate(holdout):
        add_revlog(col, c.id, t0 + DAY + 120_000 + i, 3)
        add_revlog(col, c.id, t0 + 2 * DAY + i, 1 if i == 0 else 3, 1)
    # Baseline: learned 40 days before the first session; elsewhere: another deck.
    for i, c in enumerate([*old, elsewhere]):
        add_revlog(col, c.id, t0 - 40 * DAY + i, 3)
        add_revlog(col, c.id, t0 - 39 * DAY + i, 1, 1)

    inputs = read_report_inputs(col, st)
    assert inputs.rollover == col.get_preferences().scheduling.rollover
    assert {c.id for c in cards + old} <= set(inputs.cards)
    assert elsewhere.id not in inputs.cards
    assert inputs.cards[drilled[0].id] == CardInfo("Med Term::Ch 1", "Med Term")
    assert inputs.cards[old[0].id] == CardInfo("Med Term::Ch 0", "Med Term")

    r = build_report(
        inputs.lines,
        inputs.revlog,
        None,
        cards=inputs.cards,
        rollover=inputs.rollover,
        settings=ReportSettings(min_n=1),
    )
    assert r.sessions == 1 and r.decks == ["Med Term"]
    assert r.counts("drilled") == (4, 3, 0, 1)
    drilled_stat, holdout_stat, baseline_stat = r.comparison
    assert (drilled_stat.n, drilled_stat.again, drilled_stat.trials) == (3, 2, 4.0)
    assert (holdout_stat.n, holdout_stat.again) == (2, 1)
    assert (baseline_stat.n, baseline_stat.again) == (2, 2)
    assert {row.cid for row in r.group("baseline")} == {c.id for c in old}
    assert {row.encode_reps for row in r.group("drilled")} == {2}
    assert {row.mode for row in r.group("drilled")} == {"B"}


def test_read_revlog_batches_the_in_list(col: Collection) -> None:
    n = 2 * BATCH + 7
    for cid in range(1, n + 1):
        add_revlog(col, cid, 1_700_000_000_000 + (n - cid), 3)
    rows = read_revlog(col, range(1, n + 1))
    assert len(rows) == n and [r.id for r in rows] == sorted(r.id for r in rows)
    assert rows[0] == RevlogRow(1_700_000_000_000, n, 3, 0, 1, 5000)
    assert read_revlog(col, []) == []
    assert len(read_revlog(col, [5, 5, 6])) == 2


def test_card_decks_uses_the_home_deck(col: Collection) -> None:
    did = deck(col, "Path::Ch 1")
    c = basic(col, did, "a")
    c.odid, c.did = did, deck(col, "Filtered")
    col.update_card(c)
    assert card_decks(col, [c.id, 424242]) == {c.id: CardInfo("Path::Ch 1", "Path")}


def test_encode_reps_overrides(col: Collection, tmp_path: Path) -> None:
    st = Storage(tmp_path / "user_files", "User 1")
    a, b = deck(col, "Med Term"), deck(col, "Path")
    deck_settings.save(st, a, {"encodeReps": 3})
    deck_settings.save(st, b, {"encodeReps": 2})
    assert encode_reps_overrides(col, st, 2) == ["Med Term (3)"]
    assert encode_reps_overrides(col, st, 4) == ["Med Term (3)", "Path (2)"]
