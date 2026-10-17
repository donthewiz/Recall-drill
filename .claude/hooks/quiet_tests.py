"""PreToolUse hook (Bash): pipe test runs through test_filter.py so only failures and counts show.

A command is rewritten when it runs pytest, vitest or `npm test` and has no pipe of its
own. The exit code is kept (pipefail). To see the full output, put RD_FULL_OUTPUT=1 in
the command, e.g. `RD_FULL_OUTPUT=1 pytest mathpath-addon/tests -q`.
"""

import json
import os
import re
import shlex
import sys

RUNNER = re.compile(
    r"(^|[\s;&(|])(pytest|vitest)(\s|$)"
    r"|python[0-9.]*\s+-m\s+pytest\b"
    r"|\bnpm\s+(run\s+)?test\b"
)
INSTALL = re.compile(r"\b(pip|uv|npm|pnpm|yarn)\s+(install|add|ci)\b")


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    tool_input = data.get("tool_input") or {}
    cmd = tool_input.get("command") or ""
    if not RUNNER.search(cmd) or INSTALL.search(cmd) or "|" in cmd or "RD_FULL_OUTPUT=1" in cmd:
        return 0
    flt = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_filter.py")
    new_cmd = f"set -o pipefail; ( {cmd}\n) 2>&1 | python3 {shlex.quote(flt)}"
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "updatedInput": {**tool_input, "command": new_cmd},
        }
    }
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
