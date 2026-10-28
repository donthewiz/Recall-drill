from __future__ import annotations

import sys
from pathlib import Path

ADDON_ROOT = Path(__file__).resolve().parent.parent

# Make `import card_triage` work without importing the add-on entry (the root __init__.py needs a
# running Anki main window).
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))
_TESTS = Path(__file__).resolve().parent
for sub in ("", "anki_io"):
    p = str(_TESTS / sub) if sub else str(_TESTS)
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    import anki.lang
except ModuleNotFoundError:
    pass
else:
    anki.lang.set_lang("en_US")
