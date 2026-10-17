"""PreToolUse hook (Edit/Write/MultiEdit/NotebookEdit): block hand edits to protected paths.

Exit 2 blocks the tool call; the message on stderr goes back to Claude as the reason.
Copying files in with a shell command (the documented way to update both folders) is
not blocked: only the file-editing tools are. core/SOURCE.md stays editable (its hash table).
"""

import json
import os
import sys

PROTECTED = {
    "mathpath-addon/core/": (
        "mathpath-addon/core/ is copied unchanged from the anki-math-cards plugin and a test "
        "checks its hashes (core/SOURCE.md). Fix bugs in the plugin, or work around them in "
        "Math Path's own adapter code (math_path/palette.py)."
    ),
    "anki-addon/tests/golden/": (
        "The golden traces are generated, never hand-edited. Regenerate them from the repo "
        "root with `npx tsx anki-addon/tools/export_golden.ts` in the same commit as the TS "
        "and Python engine change (anki-addon/docs/DECISIONS.md, 'Changing the engine now')."
    ),
}


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    tool_input = data.get("tool_input") or {}
    path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    if not path:
        return 0
    root = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
    full = os.path.abspath(os.path.join(root, path))
    rel = os.path.relpath(full, os.path.abspath(root)).replace(os.sep, "/")
    if rel == "mathpath-addon/core/SOURCE.md":
        return 0  # its hash table is updated by hand after a fresh copy
    for prefix, why in PROTECTED.items():
        if rel.startswith(prefix):
            print(f"Blocked: {rel} is protected. {why}", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
