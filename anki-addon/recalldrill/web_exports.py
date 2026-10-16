"""The one ``setWebExports`` pattern for this add-on's ``web/`` folder (pure).

Anki keeps a single pattern per add-on, so every window that serves files registers this
same one: the exam tracker's two files, and the math field (MathLive, its fonts and
``rd_math_input.js``).
"""

from __future__ import annotations

from .math_input import web_pattern

EXAM_TRACKER_FILES = r"exam_tracker\.(js|css)"

PATTERN = rf"web/({EXAM_TRACKER_FILES}|{web_pattern()})"
