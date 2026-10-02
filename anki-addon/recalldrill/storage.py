"""Local JSON files under the add-on's ``user_files/`` folder, one folder per profile.

Pure: no anki, aqt or Qt. The caller passes the ``user_files/`` path in
(``__init__.py`` builds it from ``os.path.dirname(__file__)``), so tests use
``tmp_path``.

Layout: ``user_files/profiles/<sanitized profile name>/<name>.json``. Anki
shares one ``user_files/`` across all profiles, and note, card and deck ids
only mean something inside one profile's collection.

Every file is ``{"schemaVersion": 1, "data": ...}``.

- Writes are atomic: ``<name>.tmp``, flush, ``os.fsync``, then ``os.replace``.
  A crash mid-write leaves the old file intact.
- A file that can't be parsed (bad JSON, bad encoding, no envelope, another
  schema version) is renamed to ``<name>.corrupt-<timestamp>`` and the default
  is returned. That is logged, never raised: a bad file must not stop a drill.
  The renamed file keeps the bytes for a human to look at.
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
        if not _NAME_RE.fullmatch(name):
            raise ValueError(f"not a plain file name: {name!r}")
        return self.dir / name

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
        tmp = path.with_name(name + ".tmp")
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
