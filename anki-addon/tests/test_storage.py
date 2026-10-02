"""recalldrill/storage.py: per-profile JSON files, atomic writes, corrupt-file recovery."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import pytest

from recalldrill import storage
from recalldrill.storage import (
    DECK_SETTINGS,
    HINTS,
    MAPPINGS,
    Storage,
    sanitize_profile_name,
)


@pytest.fixture
def st(tmp_path: Path) -> Storage:
    return Storage(tmp_path / "user_files", "User 1")


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["User 1", "Don", "Usuário", "a.b-c_d"])
def test_plain_profile_names_are_kept(name: str) -> None:
    assert sanitize_profile_name(name) == name


@pytest.mark.parametrize(
    "name", ["a/b", "a\\b", "a:b", "CON", "nul.txt", "", "..", "trailing. ", 'q"uote', "x" * 80]
)
def test_unsafe_profile_names_get_a_safe_unique_folder(name: str) -> None:
    safe = sanitize_profile_name(name)
    assert safe and safe != name
    assert not any(ch in safe for ch in '/\\:*?"<>|')
    assert not safe.endswith((".", " "))
    assert safe.split(".")[0].split("-")[0].upper() not in {"CON", "NUL"}
    assert len(safe) <= 64 + 9


def test_sanitized_names_do_not_collide() -> None:
    assert sanitize_profile_name("a/b") != sanitize_profile_name("a_b")
    assert sanitize_profile_name("a/b") != sanitize_profile_name("a:b")


def test_files_live_under_profiles_folder(tmp_path: Path) -> None:
    root = tmp_path / "user_files"
    one, two = Storage(root, "User 1"), Storage(root, "Other")
    one.write_json(MAPPINGS, {"a": 1})
    assert (root / "profiles" / "User 1" / MAPPINGS).is_file()
    assert two.read_json(MAPPINGS, {}) == {}
    assert one.read_json(MAPPINGS, {}) == {"a": 1}


def test_file_names_used_in_phase_2() -> None:
    assert (MAPPINGS, DECK_SETTINGS, HINTS) == ("mappings.json", "deck_settings.json", "hints.json")


@pytest.mark.parametrize("name", ["../x.json", "a/b.json", "", ".hidden", "a\\b"])
def test_rejects_paths_as_names(st: Storage, name: str) -> None:
    with pytest.raises(ValueError):
        st.path(name)


# ---------------------------------------------------------------------------
# Read / write
# ---------------------------------------------------------------------------


def test_missing_file_returns_a_copy_of_the_default(st: Storage) -> None:
    default: dict[str, Any] = {"x": [1]}
    got = st.read_json(HINTS, default)
    assert got == default
    got["x"].append(2)
    assert default == {"x": [1]}


def test_round_trip_and_envelope(st: Storage) -> None:
    data = {"12": {"0": {"answer_field": "Back"}}, "ü": "ünïcode"}
    st.write_json(MAPPINGS, data)
    raw = st.path(MAPPINGS).read_bytes()
    assert b"\r\n" not in raw
    assert json.loads(raw) == {"schemaVersion": 1, "data": data}
    assert st.read_json(MAPPINGS, None) == data
    assert not st.path(MAPPINGS).with_name("mappings.json.tmp").exists()


def test_write_is_tmp_fsync_replace(st: Storage, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    real_fsync, real_replace = os.fsync, os.replace

    def fsync(fd: int) -> None:
        calls.append("fsync")
        real_fsync(fd)

    def replace(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        calls.append(f"replace {Path(src).name} -> {Path(dst).name}")
        real_replace(src, dst)

    monkeypatch.setattr(storage.os, "fsync", fsync)
    monkeypatch.setattr(storage.os, "replace", replace)
    st.write_json(HINTS, {"1:0": "a___"})
    assert calls == ["fsync", "replace hints.json.tmp -> hints.json"]


def test_failed_replace_keeps_the_old_file(st: Storage, monkeypatch: pytest.MonkeyPatch) -> None:
    st.write_json(HINTS, {"old": "1"})

    def boom(src: object, dst: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(storage.os, "replace", boom)
    with pytest.raises(OSError, match="disk full"):
        st.write_json(HINTS, {"new": "2"})
    monkeypatch.undo()
    assert st.read_json(HINTS, None) == {"old": "1"}
    assert not st.path(HINTS).with_name("hints.json.tmp").exists()


def test_unserializable_data_never_touches_the_file(st: Storage) -> None:
    st.write_json(HINTS, {"old": "1"})
    with pytest.raises(TypeError):
        st.write_json(HINTS, {"bad": object()})
    with pytest.raises(ValueError):
        st.write_json(HINTS, {"nan": float("nan")})
    assert st.read_json(HINTS, None) == {"old": "1"}
    assert not st.path(HINTS).with_name("hints.json.tmp").exists()


def test_bom_is_accepted(st: Storage) -> None:
    st.dir.mkdir(parents=True)
    st.path(HINTS).write_bytes(
        b"\xef\xbb\xbf" + json.dumps({"schemaVersion": 1, "data": {}}).encode()
    )
    assert st.read_json(HINTS, None) == {}
    assert st.path(HINTS).exists()


# ---------------------------------------------------------------------------
# Corrupt files
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        b"{not json",
        b"\xff\xfe\x00garbage",
        b'["no", "envelope"]',
        b'{"data": {}}',
        b'{"schemaVersion": 2, "data": {}}',
        b'{"schemaVersion": 1}',
        b"",
    ],
)
def test_corrupt_file_is_set_aside_and_default_returned(
    st: Storage, content: bytes, caplog: pytest.LogCaptureFixture
) -> None:
    st.dir.mkdir(parents=True)
    st.path(MAPPINGS).write_bytes(content)
    with caplog.at_level(logging.ERROR, logger="recalldrill.storage"):
        assert st.read_json(MAPPINGS, {"d": 1}) == {"d": 1}
    assert not st.path(MAPPINGS).exists()
    (aside,) = st.dir.glob("mappings.json.corrupt-*")
    assert aside.read_bytes() == content
    assert "unreadable" in caplog.text
    # The next write starts fresh; the set-aside copy stays.
    st.write_json(MAPPINGS, {"x": 1})
    assert st.read_json(MAPPINGS, None) == {"x": 1}
    assert aside.exists()


def test_two_corruptions_in_one_second_keep_both(
    st: Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(storage.time, "strftime", lambda fmt: "20261002-120000")
    st.dir.mkdir(parents=True)
    for content in (b"one", b"two"):
        st.path(HINTS).write_bytes(content)
        assert st.read_json(HINTS, {}) == {}
    names = sorted(p.name for p in st.dir.glob("hints.json.corrupt-*"))
    assert names == ["hints.json.corrupt-20261002-120000", "hints.json.corrupt-20261002-120000-1"]


def test_unreadable_path_returns_default_without_renaming(st: Storage) -> None:
    # A directory where the file should be: reading raises an OSError.
    st.path(HINTS).mkdir(parents=True)
    assert st.read_json(HINTS, {"d": 1}) == {"d": 1}
    assert st.path(HINTS).is_dir()
    assert list(st.dir.glob("hints.json.corrupt-*")) == []
