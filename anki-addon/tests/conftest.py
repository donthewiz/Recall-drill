from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import anki.lang
import pytest

# strip_html (and other i18n-backed helpers) crash without a language set.
anki.lang.set_lang("en_US")

from anki.collection import Collection  # noqa: E402  (after set_lang)

ADDON_ROOT = Path(__file__).resolve().parent.parent
RECALLDRILL = ADDON_ROOT / "recalldrill"

# Make `import recalldrill` work without importing the add-on entry
# (anki-addon/__init__.py needs a running Anki main window).
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))


@pytest.fixture
def col(tmp_path: Path) -> Iterator[Collection]:
    """A scratch collection with FSRS on. Never a real profile."""
    c = Collection(str(tmp_path / "collection.anki2"))
    c.set_config("fsrs", True)
    try:
        yield c
    finally:
        c.close()
