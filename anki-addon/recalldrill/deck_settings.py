"""Per-deck drill settings (pure, plus storage in ``deck_settings.json``).

Keyed by deck id. Keys: ``strictPunctuation``, ``stemTolerance``,
``batchSize``, ``encodeReps``, ``hints``, ``cycleOrder``, ``card_ords``,
``holdoutPct`` (Phase 5: the deck's holdout percentage, 0-50; the config's
``holdout_pct`` is the default). A
deck without saved settings uses :data:`DEFAULTS` (or the add-on config's, via
``resolve``'s ``base``); for a terminology-looking deck,
:func:`propose_terminology_settings` suggests better ones, which the setup
panel offers as one click and only saves on Start or Save.

``hints`` has no fixed default: unless saved, it is on when strict punctuation
is on and most of the selected cards are standard (non-cloze) note types
(docs/DECISIONS.md, "Disambiguation hints").
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from typing import Any, Literal, NotRequired, TypedDict, cast

from .engine.jscompat import js_split_ws, js_trim
from .engine.types import CycleOrder
from .storage import DECK_SETTINGS, Storage


class DeckSettings(TypedDict):
    strictPunctuation: NotRequired[bool]
    stemTolerance: NotRequired[bool]
    batchSize: NotRequired[int]
    encodeReps: NotRequired[int]
    hints: NotRequired[bool]
    cycleOrder: NotRequired[CycleOrder]
    card_ords: NotRequired[dict[str, list[int]]]
    """Template filter: note type id (as a string, for JSON) -> template ords."""
    holdoutPct: NotRequired[int]
    """Holdout percentage for this deck's sessions (0 = off)."""


class ResolvedSettings(TypedDict):
    strictPunctuation: bool
    stemTolerance: bool
    batchSize: int
    encodeReps: int
    cycleOrder: CycleOrder
    card_ords: dict[str, list[int]]
    holdoutPct: int


HOLDOUT_MAX_PCT = 50
"""A higher holdout would leave most new cards undrilled."""

# The web app's defaults (config.json); strict punctuation is off there too.
DEFAULTS: ResolvedSettings = {
    "strictPunctuation": False,
    "stemTolerance": True,
    "batchSize": 5,
    "encodeReps": 3,
    "cycleOrder": "shuffled",
    "card_ords": {},
    "holdoutPct": 0,
}

TERMINOLOGY_MAX_WORDS = 3
TERMINOLOGY_SHARE = 0.8
MOSTLY_STANDARD_SHARE = 0.5

SettingsSource = Literal["saved", "proposed", "defaults"]


def sanitize(raw: object) -> DeckSettings:
    """Keeps the known keys with the right types; drops everything else."""
    out: DeckSettings = {}
    if not isinstance(raw, dict):
        return out
    d = {str(k): v for k, v in cast(dict[object, Any], raw).items()}
    for key in ("strictPunctuation", "stemTolerance", "hints"):
        if isinstance(d.get(key), bool):
            out[key] = d[key]
    batch = d.get("batchSize")
    if isinstance(batch, int) and not isinstance(batch, bool) and batch >= 0:
        out["batchSize"] = batch
    reps = d.get("encodeReps")
    if isinstance(reps, int) and not isinstance(reps, bool) and 1 <= reps <= 10:
        out["encodeReps"] = reps
    if d.get("cycleOrder") in ("shuffled", "inOrder"):
        out["cycleOrder"] = d["cycleOrder"]
    pct = d.get("holdoutPct")
    if isinstance(pct, int) and not isinstance(pct, bool) and 0 <= pct <= HOLDOUT_MAX_PCT:
        out["holdoutPct"] = pct
    ords = d.get("card_ords")
    if isinstance(ords, dict):
        clean: dict[str, list[int]] = {}
        for ntid, values in cast(dict[object, object], ords).items():
            if not (isinstance(ntid, str) and ntid.isdigit() and isinstance(values, list)):
                continue
            clean[ntid] = sorted(
                {
                    v
                    for v in cast(list[object], values)
                    if isinstance(v, int) and not isinstance(v, bool) and v >= 0
                }
            )
        out["card_ords"] = clean
    return out


def load_all(storage: Storage) -> dict[str, DeckSettings]:
    data = storage.read_json(DECK_SETTINGS, {})
    if not isinstance(data, dict):
        return {}
    return {str(k): sanitize(v) for k, v in cast(dict[object, object], data).items()}


def get_saved(storage: Storage, did: int) -> DeckSettings | None:
    return load_all(storage).get(str(did))


def save(storage: Storage, did: int, settings: DeckSettings) -> None:
    all_settings = load_all(storage)
    all_settings[str(did)] = sanitize(settings)
    storage.write_json(DECK_SETTINGS, all_settings)


def resolve(settings: DeckSettings | None, base: ResolvedSettings = DEFAULTS) -> ResolvedSettings:
    """``settings`` over ``base`` (the defaults, or the add-on config's)."""
    s = settings or {}
    return {
        "strictPunctuation": s.get("strictPunctuation", base["strictPunctuation"]),
        "stemTolerance": s.get("stemTolerance", base["stemTolerance"]),
        "batchSize": s.get("batchSize", base["batchSize"]),
        "encodeReps": s.get("encodeReps", base["encodeReps"]),
        "cycleOrder": s.get("cycleOrder", base["cycleOrder"]),
        "card_ords": dict(s.get("card_ords", base["card_ords"])),
        "holdoutPct": s.get("holdoutPct", base["holdoutPct"]),
    }


def card_ords_option(settings: DeckSettings | None) -> dict[int, frozenset[int]]:
    """``SelectOptions.card_ords`` from the saved template filter."""
    ords = (settings or {}).get("card_ords", {})
    return {int(ntid): frozenset(values) for ntid, values in ords.items()}


def hints_enabled(settings: DeckSettings | None, standard_share: float) -> bool:
    """The saved ``hints``, else on when strict punctuation is on and more than
    half of the selected cards are standard note types."""
    s = settings or {}
    if "hints" in s:
        return s["hints"]
    strict = s.get("strictPunctuation", DEFAULTS["strictPunctuation"])
    return strict and standard_share > MOSTLY_STANDARD_SHARE


def word_count(text: str) -> int:
    t = js_trim(text)
    return len(js_split_ws(t)) if t else 0


def looks_like_terminology(answers: Sequence[str]) -> bool:
    """At least 80% of the answers are three words or fewer."""
    if not answers:
        return False
    short = sum(1 for a in answers if word_count(a) <= TERMINOLOGY_MAX_WORDS)
    return short >= TERMINOLOGY_SHARE * len(answers)


def propose_terminology_settings(answers: Sequence[str]) -> DeckSettings | None:
    """A proposal for a deck with no saved settings, or None. Never saved here."""
    if not looks_like_terminology(answers):
        return None
    return {"stemTolerance": False, "strictPunctuation": True, "hints": True}


def effective(
    saved: DeckSettings | None, answers: Sequence[str]
) -> tuple[DeckSettings, SettingsSource]:
    """What a session would use: saved settings, else the terminology proposal,
    else nothing (defaults)."""
    if saved is not None:
        return saved, "saved"
    proposal = propose_terminology_settings(answers)
    if proposal is not None:
        return proposal, "proposed"
    return {}, "defaults"


def settings_deck(home_dids: Iterable[int]) -> int | None:
    """For a search scope: the deck holding the most selected cards (ties: the
    one met first)."""
    counts = Counter(home_dids)
    if not counts:
        return None
    return counts.most_common(1)[0][0]


def standard_share(kinds: Iterable[str]) -> float:
    ks = list(kinds)
    return sum(1 for k in ks if k == "standard") / len(ks) if ks else 0.0
