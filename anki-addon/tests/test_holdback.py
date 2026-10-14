"""Hold back (v0.3), pure: the setting's inheritance, the order default, the
planning rules on synthetic card snapshots, and the deck setting's storage."""

from __future__ import annotations

from pathlib import Path

from anki.consts import (
    CARD_TYPE_NEW,
    CARD_TYPE_REV,
    QUEUE_TYPE_MANUALLY_BURIED,
    QUEUE_TYPE_NEW,
    QUEUE_TYPE_REV,
    QUEUE_TYPE_SUSPENDED,
)

from recalldrill import deck_settings
from recalldrill.anki_io.cards import CardSnapshot
from recalldrill.anki_io.holdback import build_hold_back_plan, describe
from recalldrill.holdback import (
    TAG_HELD,
    UNDO_LABEL,
    HoldBack,
    button_label,
    default_order,
    effective,
    release_question,
)
from recalldrill.storage import Storage


def snap(
    cid: int,
    *,
    nid: int | None = None,
    type: int = CARD_TYPE_NEW,
    queue: int = QUEUE_TYPE_NEW,
    odid: int = 0,
    tags: tuple[str, ...] = (),
) -> CardSnapshot:
    return CardSnapshot(
        cid=cid,
        nid=nid if nid is not None else cid * 10,
        did=1,
        odid=odid,
        ord=0,
        ntid=1,
        type=type,
        queue=queue,
        ivl=0,
        due=cid,
        lapses=0,
        reps=0,
        factor=0,
        flags=0,
        tags=tags,
        fsrs_d=None,
        fsrs_s=None,
    )


def test_the_nearest_explicit_value_decides() -> None:
    saved: dict[int, bool | None] = {1: True, 2: None, 3: None}
    chain = [3, 2, 1]  # deck 3, its parent 2, the root 1
    assert effective(chain, saved.get) == HoldBack(True, 1)
    saved[2] = False  # a subdeck opts out explicitly
    assert effective(chain, saved.get) == HoldBack(False, 2)
    saved[3] = True
    assert effective(chain, saved.get) == HoldBack(True, 3)
    assert effective([3, 2, 1], lambda _d: None) == HoldBack(False, None)  # default off


def test_the_order_default_and_labels() -> None:
    assert default_order(True) == "deck_order"
    assert default_order(False) == "priority_first"
    assert button_label(12) == "Hold back 12"
    assert release_question(1) == "Release 1 held card to Anki now?"
    assert release_question(7) == "Release 7 held cards to Anki now?"
    assert UNDO_LABEL == "Recall Drill: hold back" and TAG_HELD == "rd::held"


def test_planning_rules() -> None:
    snaps = [
        snap(1),  # new, unsuspended: held back
        snap(2, nid=20, tags=("rd::drill::A",)),  # tagged ones too
        snap(3, nid=20),  # a sibling of 2: same note, tagged once
        snap(4, type=CARD_TYPE_REV, queue=QUEUE_TYPE_REV),  # already introduced
        snap(5, queue=QUEUE_TYPE_MANUALLY_BURIED),  # buried
        snap(6, queue=QUEUE_TYPE_SUSPENDED),  # already suspended
        snap(7, odid=99),  # in a filtered deck
        snap(8),  # handed off, waiting for Anki
        snap(9, nid=90, tags=(TAG_HELD,)),  # already tagged: no tag step
    ]
    plan = build_hold_back_plan(5, "Course", snaps, waiting_for_anki=[8])
    assert plan.suspend == (1, 2, 3, 9)
    assert plan.tag_notes == (10, 20)
    assert (plan.handed_off, plan.in_filtered, plan.cards) == (1, 1, 4)
    assert plan.has_changes
    text = describe(plan)
    assert text.startswith("Keep 4 new cards in Course out of Anki until drilled?")
    assert "1 card handed off and waiting for Anki, 1 card in a filtered deck" in text
    assert f'Edit → Undo "{UNDO_LABEL}" reverts it.' in text
    nothing = build_hold_back_plan(5, "Course", [snap(4, type=CARD_TYPE_REV, queue=QUEUE_TYPE_REV)])
    assert not nothing.has_changes and nothing.cards == 0


def test_hold_back_is_a_deck_setting_saved_on_its_own(tmp_path: Path) -> None:
    st = Storage(tmp_path / "user_files", "User 1")
    assert deck_settings.explicit_hold_back(st, 5) is None
    deck_settings.save(st, 5, {"batchSize": 7})
    assert deck_settings.explicit_hold_back(st, 5) is None  # saved settings without it
    deck_settings.set_hold_back(st, 5, True)
    saved = deck_settings.get_saved(st, 5)
    assert saved == {"batchSize": 7, "holdBack": True}  # nothing else was touched
    assert deck_settings.explicit_hold_back(st, 5) is True
    deck_settings.set_hold_back(st, 5, False)
    assert deck_settings.explicit_hold_back(st, 5) is False
    deck_settings.set_hold_back(st, 6, True)  # a deck with nothing saved
    assert deck_settings.get_saved(st, 6) == {"holdBack": True}
    # A bad value is dropped, the rest kept.
    assert deck_settings.sanitize({"holdBack": "yes", "batchSize": 3}) == {"batchSize": 3}
    assert deck_settings.resolve({"holdBack": True}) == deck_settings.resolve(
        {}
    )  # not a session setting
