from __future__ import annotations

import sys
from pathlib import Path

ADDON_ROOT = Path(__file__).resolve().parent.parent
RECALLDRILL = ADDON_ROOT / "recalldrill"

# Make `import recalldrill` work without importing the add-on entry
# (anki-addon/__init__.py needs a running Anki main window).
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))

# The engine tests need nothing but pytest: CI's addon-engine job runs them
# without anki installed. Everything else does need anki.
try:
    import anki.lang
except ModuleNotFoundError:
    pass
else:
    # strip_html (and other i18n-backed helpers) crash without a language set.
    anki.lang.set_lang("en_US")
