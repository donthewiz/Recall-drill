"""Drill cards left waiting too long, and sending them to Anki undrilled (pure).

docs/DECISIONS.md, "Waiting cards and release". The anki-cards skill suspends
the cards it tags ``rd::drill`` ("suspend until drilled"). When a deck is never
drilled they wait forever. This module decides which are **stale**, when the
once-a-day notice shows, and what a release writes to the history; reading
the collection is ``anki_io/waiting.py``, the write ``anki_io/release.py``.

- **Waiting**: a new, suspended card whose note has a ``rd::drill`` or (v0.3)
  ``rd::held`` tag (the search is exactly :data:`WAITING_SEARCH`, never
  ``tag:rd::*``, which would also match ``rd::drilled`` and ``rd::undrilled``),
  and that isn't waiting for Anki after a handoff or release. **Added**: the note
  id's date (its Anki day).
- **Stale**: added more than ``stale_drill_days`` days ago, or in a deck whose
  pacing target has passed or that pacing says has no drill days left (the
  card's home deck's pacing, else the nearest parent deck's with a target).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, cast

from .engine.jscompat import js_iso_string
from .history_store import RELEASE_GROUPS
from .holdback import TAG_HELD
from .pacing import PacingSettings, drill_days, short_date
from .storage import Storage

WAITING_TAG = "rd::drill"
"""The anki-cards skill's tag family (``rd::drill``, ``rd::drill::A``, …)."""
HELD_TAG = TAG_HELD
"""v0.3: the tag a hold-back adds; held cards wait like skill drill cards."""
WAITING_STATES = "is:new is:suspended"
WAITING_SEARCH = f"(tag:{WAITING_TAG} OR tag:{HELD_TAG}) {WAITING_STATES}"
"""``tag:rd::drill`` matches the tag and its children, not ``rd::drilled``; the same
for ``tag:rd::held`` (v0.3: held cards wait like skill drill cards)."""
TAG_UNDRILLED = "rd::undrilled"
"""The note tag a release adds."""
NOTICE_FILE = "waiting_notice.json"
"""``user_files/profiles/<profile>/waiting_notice.json``: the last Anki day shown."""
UNDO_LABEL = "Recall Drill: send undrilled"


@dataclass(frozen=True)
class WaitingCard:
    cid: int
    nid: int
    did: int
    """The card's home deck."""
    added: date
    """The note id's Anki day."""


@dataclass(frozen=True)
class WaitingRow:
    """One deck's waiting cards (subdeck level: the cards' home deck)."""

    did: int
    deck: str
    cids: tuple[int, ...]
    stale_cids: tuple[int, ...]
    """The waiting cards that are stale (a subset of ``cids``)."""
    oldest: date
    target: date | None
    """The pacing target that applies to this deck, if any."""

    @property
    def waiting(self) -> int:
        return len(self.cids)

    @property
    def stale(self) -> int:
        return len(self.stale_cids)


def pacing_stale(settings: PacingSettings | None, today: date) -> bool:
    """The deck's pacing target has passed, or it has no drill days left."""
    if settings is None or settings.target_date is None:
        return False
    if today > settings.target_date:
        return True
    return not drill_days(today, settings, done_today=False)


def is_stale(added: date, today: date, stale_days: int, pacing: PacingSettings | None) -> bool:
    return (today - added).days > stale_days or pacing_stale(pacing, today)


def waiting_rows(
    cards: Iterable[WaitingCard],
    today: date,
    stale_days: int,
    pacing_for: Callable[[int], PacingSettings | None],
    deck_name: Callable[[int], str],
) -> list[WaitingRow]:
    """One row per home deck, by deck name. ``pacing_for(did)``: the pacing that
    applies to a deck (its own target, else its nearest parent's), or None."""
    by_deck: dict[int, list[WaitingCard]] = {}
    for c in cards:
        by_deck.setdefault(c.did, []).append(c)
    rows: list[WaitingRow] = []
    for did, group in by_deck.items():
        pacing = pacing_for(did)
        rows.append(
            WaitingRow(
                did=did,
                deck=deck_name(did),
                cids=tuple(sorted(c.cid for c in group)),
                stale_cids=tuple(
                    sorted(c.cid for c in group if is_stale(c.added, today, stale_days, pacing))
                ),
                oldest=min(c.added for c in group),
                target=pacing.target_date if pacing is not None else None,
            )
        )
    rows.sort(key=lambda r: r.deck)
    return rows


def stale_total(rows: Sequence[WaitingRow]) -> tuple[int, date | None]:
    """(stale cards, the oldest added date among the decks with any)."""
    stale = [r for r in rows if r.stale]
    return sum(r.stale for r in stale), min((r.oldest for r in stale), default=None)


# ---------------------------------------------------------------------------
# The once-a-day notice
# ---------------------------------------------------------------------------


def notice_due(enabled: bool, last_shown: date | None, today: date) -> bool:
    """Once per Anki day, when the notice is on."""
    return enabled and (last_shown is None or last_shown < today)


def notice_text(stale: int, oldest: date) -> str:
    card = "drill card is" if stale == 1 else "drill cards are"
    return (
        f"Recall Drill: {stale} {card} still suspended and waiting "
        f"(oldest added {short_date(oldest)}). Tools → Recall Drill: waiting cards."
    )


def panel_line(stale: int) -> str:
    """The setup panel's amber line for a deck scope with stale waiting cards."""
    card = "card has" if stale == 1 else "cards have"
    return (
        f"{stale} drill {card} waited too long, still suspended. "
        "Drill them, or send them to Anki undrilled (Tools → Recall Drill: waiting cards)."
    )


def load_last_shown(storage: Storage) -> date | None:
    raw: object = storage.read_json(NOTICE_FILE, {})
    day = cast(dict[str, object], raw).get("lastShown") if isinstance(raw, dict) else None
    if not isinstance(day, str):
        return None
    try:
        return date.fromisoformat(day)
    except ValueError:
        return None


def save_last_shown(storage: Storage, day: date) -> None:
    storage.write_json(NOTICE_FILE, {"lastShown": day.isoformat()})


# ---------------------------------------------------------------------------
# What "Send to Anki undrilled" offers (2026-10-13)
# ---------------------------------------------------------------------------

ReleaseScope = Literal["stale", "all"]
RELEASE_SCOPES: tuple[ReleaseScope, ...] = ("stale", "all")


@dataclass(frozen=True)
class ReleaseChoice:
    """One thing the confirmation can send: a row's stale cards, or all of its
    waiting cards."""

    scope: ReleaseScope
    cids: tuple[int, ...]

    @property
    def label(self) -> str:
        """The confirmation's button: "Stale only (N)" or "All waiting (M)"."""
        return f"{'Stale only' if self.scope == 'stale' else 'All waiting'} ({len(self.cids)})"


def release_choices(row: WaitingRow) -> list[ReleaseChoice]:
    """The row's choices, the default first: "Stale only" while any card is
    stale (the default, so a deck whose exam is ahead keeps its fresh cards),
    then "All waiting". With nothing stale, only "All waiting"."""
    choices: list[ReleaseChoice] = []
    if row.stale_cids:
        choices.append(ReleaseChoice("stale", row.stale_cids))
    choices.append(ReleaseChoice("all", row.cids))
    return choices


# ---------------------------------------------------------------------------
# The release's history line
# ---------------------------------------------------------------------------


def release_line(
    did: int,
    released: Sequence[int],
    siblings: Sequence[int],
    tagged_notes: Sequence[int],
    at_ms: float,
    scope: ReleaseScope,
    untagged_held: Sequence[int] = (),
) -> dict[str, Any]:
    """``{"type": "release", …}`` in ``history/<did>.jsonl``. ``scope`` says which
    choice was sent: ``"stale"`` (the deck's stale cards) or ``"all"``."""
    line: dict[str, Any] = {
        "type": "release",
        "timestamp": js_iso_string(at_ms),
        "deckId": did,
        "scope": scope,
        "groups": {"released": list(released), "released_siblings": list(siblings)},
        "tags": {"added": len(tagged_notes), "byTag": {TAG_UNDRILLED: len(tagged_notes)}},
    }
    if untagged_held:  # v0.3: absent when the release removed no rd::held
        line["tags"]["removed"] = len(untagged_held)
        line["tags"]["removedByTag"] = {HELD_TAG: len(untagged_held)}
    return line


def released_cids(lines: Iterable[Mapping[str, Any]]) -> set[int]:
    """Every card a release line sent to Anki (both groups)."""
    out: set[int] = set()
    for line in lines:
        if line.get("type") != "release":
            continue
        groups = line.get("groups")
        if not isinstance(groups, dict):
            continue
        for key in RELEASE_GROUPS:
            ids = cast(list[object], cast(dict[str, Any], groups).get(key) or [])
            out.update(i for i in ids if isinstance(i, int) and not isinstance(i, bool))
    return out
