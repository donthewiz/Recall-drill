"""holdout.py: deterministic assignment and the salt (pure)."""

from __future__ import annotations

import hashlib
from pathlib import Path

from recalldrill.holdout import ensure_salt, is_holdout, read_salt, salt_for
from recalldrill.storage import HOLDOUT, Storage


def test_assignment_is_the_documented_hash() -> None:
    salt = "abc123"
    for cid in (1, 1790966545010, 42):
        h = int(hashlib.sha1(f"{salt}:{cid}".encode()).hexdigest()[:8], 16) % 100
        assert is_holdout(salt, cid, 15) is (h < 15)


def test_assignment_is_stable_and_monotonic() -> None:
    salt = "5eed"
    cids = range(1_700_000_000_000, 1_700_000_000_000 + 2000)
    first = [is_holdout(salt, c, 15) for c in cids]
    assert first == [is_holdout(salt, c, 15) for c in cids]  # same answer every run
    # A card held out at 15% is held out at any higher percentage.
    assert all(is_holdout(salt, c, 30) for c, h in zip(cids, first, strict=True) if h)
    assert not any(is_holdout(salt, c, 0) for c in cids)
    assert not any(is_holdout("", c, 15) for c in cids)  # no salt: off
    assert first != [is_holdout("other", c, 15) for c in cids]  # the salt matters


def test_percentage_is_roughly_right() -> None:
    cids = range(1_600_000_000_000, 1_600_000_000_000 + 10_000)
    share = sum(is_holdout("f00d", c, 15) for c in cids) / 10_000
    assert 0.135 <= share <= 0.165


def test_salt_is_made_once_and_kept(tmp_path: Path) -> None:
    st = Storage(tmp_path, "User 1")
    assert read_salt(st) == "" and salt_for(st, 0) == ""
    assert not st.exists(HOLDOUT)  # off: nothing is written
    salt = salt_for(st, 15)
    assert len(salt) == 16 and int(salt, 16) >= 0
    assert ensure_salt(st) == salt == read_salt(Storage(tmp_path, "User 1"))
    assert salt_for(st, 0) == ""  # off again: unused, but kept
    assert read_salt(st) == salt
    assert read_salt(Storage(tmp_path, "User 2")) == ""  # per profile
