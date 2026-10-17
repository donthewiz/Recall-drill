"""progress.json and history.jsonl: atomic, per profile, never a crash on a bad file."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from math_path.progress import LEARNED, NoteProgress, ProgressStore
from math_path.storage import HISTORY, PROGRESS, Storage, sanitize_profile_name


def storage(tmp_path: Path, profile: str = "User 1") -> Storage:
    return Storage(tmp_path / "user_files", profile)


def test_progress_round_trips_and_is_written_per_profile(tmp_path: Path) -> None:
    store = ProgressStore(storage(tmp_path))
    store.put(7, NoteProgress(stage="faded", faded_level=2, faded_tries=1, last_seen="t"))
    store.put(8, NoteProgress(stage=LEARNED, solo_clean=2, handed_off=True, needed_help=True))
    again = ProgressStore(storage(tmp_path))
    assert again.get(7) == NoteProgress(stage="faded", faded_level=2, faded_tries=1, last_seen="t")
    assert again.get(8).is_learned and again.get(8).handed_off and again.get(8).needed_help
    assert again.get(99) == NoteProgress()  # unknown notes start at Study
    assert not again.has(99) and again.has(7)
    other = ProgressStore(storage(tmp_path, "Another profile"))
    assert not other.has(7)
    path = storage(tmp_path).path(PROGRESS)
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["schemaVersion"] == 1 and set(on_disk["data"]["notes"]) == {"7", "8"}


def test_a_copy_is_returned_so_a_session_cannot_change_the_store_by_accident(
    tmp_path: Path,
) -> None:
    store = ProgressStore(storage(tmp_path))
    store.put(1, NoteProgress(stage="plan"))
    got = store.get(1)
    got.stage = "solo"
    assert store.get(1).stage == "plan"


def test_a_mistyped_or_hand_edited_value_takes_its_default() -> None:
    p = NoteProgress.from_json(
        {
            "stage": "nonsense",
            "faded_level": 9,
            "faded_tries": -4,
            "solo_clean": "2",
            "needed_help": 1,
        }
    )
    assert p == NoteProgress(faded_level=2, faded_tries=0)
    assert NoteProgress.from_json(None) == NoteProgress()
    assert NoteProgress.from_json([1]) == NoteProgress()


def test_a_corrupt_progress_file_is_set_aside_and_defaults_are_used(tmp_path: Path) -> None:
    st = storage(tmp_path)
    st.path(PROGRESS).parent.mkdir(parents=True)
    st.path(PROGRESS).write_text("{not json", encoding="utf-8")
    store = ProgressStore(st)
    assert store.all() == {}
    aside = [p.name for p in st.dir.iterdir()]
    assert any(n.startswith("progress.json.corrupt-") for n in aside)
    store.put(1, NoteProgress())  # and writing works again
    assert ProgressStore(st).has(1)


def test_keys_that_are_not_note_ids_are_ignored(tmp_path: Path) -> None:
    st = storage(tmp_path)
    st.write_json(PROGRESS, {"notes": {"12": {"stage": "plan"}, "abc": {"stage": "solo"}}})
    store = ProgressStore(st)
    assert list(store.all()) == [12] and store.get(12).stage == "plan"


def test_forget_and_save_leave_no_temporary_file(tmp_path: Path) -> None:
    st = storage(tmp_path)
    store = ProgressStore(st)
    store.put(1, NoteProgress())
    store.forget(1)
    store.forget(1)
    assert not store.has(1)
    assert [p.name for p in st.dir.iterdir()] == ["progress.json"]


def test_history_lines_append_and_a_torn_last_line_is_skipped(tmp_path: Path) -> None:
    st = storage(tmp_path)
    st.append_jsonl(HISTORY, {"type": "problem", "nid": 1, "typed": "é<>&"})
    st.append_jsonl(HISTORY, {"type": "handoff", "nids": [1]})
    path = st.path(HISTORY)
    with open(path, "ab") as f:
        f.write(b'{"type": "prob')  # a crash in the middle of a write
    st.append_jsonl(HISTORY, {"type": "problem", "nid": 2})
    lines = st.read_jsonl(HISTORY)
    assert [x["type"] for x in lines] == ["problem", "handoff", "problem"]
    assert lines[0]["typed"] == "é<>&" and lines[2]["nid"] == 2
    assert path.read_bytes().endswith(b"\n") and b"\r" not in path.read_bytes()


@pytest.mark.parametrize(
    ("name", "safe"),
    [
        ("User 1", "User 1"),
        ("a/b", "a_b-"),
        ("CON", "_CON-"),
        ("", "_-"),
        ("x" * 100, "x" * 64 + "-"),
    ],
)
def test_profile_names_make_safe_folders(name: str, safe: str) -> None:
    out = sanitize_profile_name(name)
    assert out.startswith(safe)
    assert "/" not in out and "\\" not in out
    assert sanitize_profile_name("a/b") != sanitize_profile_name("a_b")


def test_only_plain_file_names_are_allowed(tmp_path: Path) -> None:
    st = storage(tmp_path)
    for bad in ("../x.json", "a/b/c.json", "", "x y.json"):
        with pytest.raises(ValueError):
            st.path(bad)
