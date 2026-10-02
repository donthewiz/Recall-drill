"""Local JSON files under the add-on's ``user_files/`` folder, one folder per profile.

Pure: no anki, aqt or Qt. The caller passes the ``user_files/`` path in
(``__init__.py`` builds it from ``os.path.dirname(__file__)``), so tests use
``tmp_path``.

Layout: ``user_files/profiles/<sanitized profile name>/<name>.json`` (or
``<folder>/<name>.json``, one folder level: ``sessions/``, ``history/``). Anki
shares one ``user_files/`` across all profiles, and note, card and deck ids
only mean something inside one profile's collection.

Every file is ``{"schemaVersion": 1, "data": ...}``.

- Writes are atomic: ``<name>.tmp``, flush, ``os.fsync``, then ``os.replace``.
  A crash mid-write leaves the old file intact.
- A file that can't be parsed (bad JSON, bad encoding, no envelope, another
  schema version) is renamed to ``<name>.corrupt-<timestamp>`` and the default
  is returned. That is logged, never raised: a bad file must not stop a drill.
  The renamed file keeps the bytes for a human to look at.

JSONL logs (``history/*.jsonl``) are the exception to the envelope: one JSON
object per line, appended and never rewritten. A line that doesn't parse (a
crash mid-append) is skipped with a warning when read.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, cast

SCHEMA_VERSION = 1

MAPPINGS = "mappings.json"
"""Note type id, then template ord -> mapping override."""
DECK_SETTINGS = "deck_settings.json"
"""Deck id -> per-deck drill settings."""
HINTS = "hints.json"
"""``"<note id>:<ord>"`` -> manual disambiguation hint (``""`` suppresses)."""
ESTIMATES = "estimates.json"
"""Session key -> cold-start history (the web app's ``cold-start-history:<slug>``)."""
SESSIONS_DIR = "sessions"
"""``sessions/<session key>.json``: one saved drill session each."""
HISTORY_DIR = "history"
"""``history/<deck or search key>.jsonl``: completed-session log, append-only."""

log = logging.getLogger(__name__)

_NAME_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*")
_UNSAFE_RE = re.compile(r"[^\w .-]")
_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)
_MAX_PROFILE_DIR = 64


def sanitize_profile_name(name: str) -> str:
    """A folder name for a profile that is safe on Windows, macOS and Linux.

    Names that need no change are kept as they are. Any other name gets a short
    hash of the original appended, so two profiles never share a folder (e.g.
    ``a/b`` and ``a_b``).
    """
    safe = _UNSAFE_RE.sub("_", name).strip(" .")[:_MAX_PROFILE_DIR].rstrip(" .")
    if not safe:
        safe = "_"
    if safe.split(".")[0].upper() in _WINDOWS_RESERVED:
        safe = "_" + safe
    if safe != name:
        safe += "-" + hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
    return safe


class Storage:
    """JSON files for one profile."""

    def __init__(self, root: str | os.PathLike[str], profile: str) -> None:
        self.root = Path(root)
        self.profile = profile
        self.dir = self.root / "profiles" / sanitize_profile_name(profile)

    def path(self, name: str) -> Path:
        """``name`` is a plain file name, or ``<folder>/<file name>`` (one level)."""
        parts = name.split("/")
        if len(parts) > 2 or not all(_NAME_RE.fullmatch(p) for p in parts):
            raise ValueError(f"not a plain file name: {name!r}")
        return self.dir.joinpath(*parts)

    def exists(self, name: str) -> bool:
        return self.path(name).is_file()

    def delete(self, name: str) -> bool:
        """Removes the file; False if it wasn't there."""
        try:
            self.path(name).unlink()
        except FileNotFoundError:
            return False
        return True

    def list_names(self, folder: str, suffix: str) -> list[str]:
        """``<folder>/<file>`` for every file in ``folder`` ending in ``suffix``, sorted."""
        base = self.path(folder)
        if not base.is_dir():
            return []
        return sorted(
            f"{folder}/{p.name}"
            for p in base.iterdir()
            if p.is_file() and p.name.endswith(suffix) and _NAME_RE.fullmatch(p.name)
        )

    def append_jsonl(self, name: str, record: Any) -> None:
        """Appends one JSON line and fsyncs. Raises on failure.

        A crash mid-append can leave a partial last line; :meth:`read_jsonl`
        skips it, and the next append starts on a fresh line.
        """
        path = self.path(name)
        line = json.dumps(record, ensure_ascii=False, allow_nan=False)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a+b") as f:
            f.seek(0, os.SEEK_END)
            prefix = b""
            if f.tell() > 0:
                f.seek(-1, os.SEEK_END)
                if f.read(1) != b"\n":
                    prefix = b"\n"
            f.write(prefix + line.encode("utf-8") + b"\n")
            f.flush()
            os.fsync(f.fileno())

    def read_jsonl(self, name: str) -> list[Any]:
        """Every line that parses, in order; [] if the file is missing or unreadable."""
        path = self.path(name)
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            return []
        except OSError:
            log.warning("Recall Drill: could not read %s", path, exc_info=True)
            return []
        out: list[Any] = []
        for n, line in enumerate(raw.decode("utf-8-sig", errors="replace").split("\n"), 1):
            if not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                log.warning("Recall Drill: %s line %d is not JSON; skipped", path, n)
        return out

    def read_json(self, name: str, default: Any) -> Any:
        """The file's ``data``, or a copy of ``default`` if the file is missing,
        can't be read, or is corrupt (corrupt files are set aside first)."""
        path = self.path(name)
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            return copy.deepcopy(default)
        except OSError:
            # Locked or no permission: the bytes may be fine, so leave them.
            log.warning("Recall Drill: could not read %s; using defaults", path, exc_info=True)
            return copy.deepcopy(default)
        try:
            # utf-8-sig: Notepad may have added a BOM.
            doc: object = json.loads(raw.decode("utf-8-sig"))
            if not isinstance(doc, dict) or "data" not in doc:
                raise ValueError("no {schemaVersion, data} envelope")
            envelope = cast(dict[str, object], doc)
            version = envelope.get("schemaVersion")
            if version != SCHEMA_VERSION:
                raise ValueError(f"schemaVersion {version!r}, expected {SCHEMA_VERSION}")
        except ValueError as exc:  # JSONDecodeError and UnicodeDecodeError included
            self._set_aside(path, exc)
            return copy.deepcopy(default)
        return envelope["data"]

    def write_json(self, name: str, data: Any) -> None:
        """Atomically replaces the file. Raises on failure; the old file stays."""
        path = self.path(name)
        text = json.dumps(
            {"schemaVersion": SCHEMA_VERSION, "data": data},
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        try:
            with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                f.write(text + "\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except BaseException:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def _set_aside(self, path: Path, exc: Exception) -> None:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        target = path.with_name(f"{path.name}.corrupt-{stamp}")
        n = 1
        while target.exists():
            target = path.with_name(f"{path.name}.corrupt-{stamp}-{n}")
            n += 1
        try:
            os.rename(path, target)
        except OSError:
            log.error(
                "Recall Drill: %s is unreadable (%s) and could not be renamed; using defaults",
                path,
                exc,
                exc_info=True,
            )
            return
        log.error(
            "Recall Drill: %s is unreadable (%s); moved it to %s and using defaults",
            path,
            exc,
            target.name,
        )
