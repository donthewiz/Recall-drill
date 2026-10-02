"""The holdout: a deterministic, opt-in control group for the tuning report (pure).

docs/DECISIONS.md, "Measurement and holdout (Phase 5)". With ``holdout_pct``
above 0, a deck session sets aside the eligible new cards whose hash falls
under the percentage: they skip the drill and go to Anki at the handoff as
plain new cards, tagged ``rd::holdout``, so their next-day Again rate can be
compared with the drilled cards' on a fair footing.

Assignment is ``int(sha1(f"{salt}:{cid}").hexdigest()[:8], 16) % 100 < pct``.
The salt is a random hex made once, the first time the holdout is on, and kept
in ``holdout.json`` (per profile, like every other add-on file). So a card's
status never changes between sessions, and nobody can predict it from the id.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Any, cast

from .storage import HOLDOUT, Storage

TAG_HOLDOUT = "rd::holdout"
"""The note tag a handed-off holdout card gets. Searched as an exact tag only."""

HOLDOUT_CLASSES = frozenset({"new", "suspended_new"})
"""Only cards Anki hasn't introduced yet can be a control: their introduction
(first rating) is the holdout's start time."""


def is_holdout(salt: str, cid: int, pct: int) -> bool:
    """Whether ``cid`` is in the holdout at ``pct`` percent. Stable for a salt."""
    if pct <= 0 or not salt:
        return False
    return int(hashlib.sha1(f"{salt}:{cid}".encode()).hexdigest()[:8], 16) % 100 < pct


def read_salt(storage: Storage) -> str:
    """The stored salt, or ``""`` when the holdout was never on."""
    data = storage.read_json(HOLDOUT, {})
    salt = cast(dict[str, Any], data).get("salt") if isinstance(data, dict) else None
    return salt if isinstance(salt, str) else ""


def ensure_salt(storage: Storage) -> str:
    """The salt, made (and saved) on first use."""
    salt = read_salt(storage)
    if not salt:
        salt = secrets.token_hex(8)
        storage.write_json(HOLDOUT, {"salt": salt})
    return salt


def salt_for(storage: Storage, pct: int) -> str:
    """The salt a selection uses: made on first enable, ``""`` while off."""
    return ensure_salt(storage) if pct > 0 else ""
