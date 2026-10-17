"""Reads test-runner output on stdin and drops the passing noise.

Dropped: pytest progress lines (dots, `file.py ....  [ 40%]`, `::name PASSED`) and
vitest's per-file check-mark lines. Everything else (failures, tracebacks, errors,
warnings, the short summary and the pass/fail count line) is kept. Very long output is
cut in the middle, so the start of the first failure and the count line stay visible.
"""

import re
import sys

HEAD, TAIL = 150, 60

PASSING = [
    re.compile(r"^[.sxX]+\s*(\[\s*\d+%\])?\s*$"),  # pytest -q progress, no F/E
    re.compile(r"^\S+\.py\s+[.sxX]+\s*(\[\s*\d+%\])?\s*$"),  # pytest default progress
    re.compile(r"::\S.*\s(PASSED|SKIPPED|XFAIL|XPASS)\b"),  # pytest -v
    re.compile(r"^\s*[✓√]\s"),  # vitest passing file/test
]


def main() -> int:
    kept = [ln for ln in sys.stdin.read().splitlines() if not any(p.search(ln) for p in PASSING)]
    while kept and not kept[0].strip():
        kept.pop(0)
    if len(kept) > HEAD + TAIL:
        cut = len(kept) - HEAD - TAIL
        kept = (
            kept[:HEAD]
            + [f"... {cut} lines cut (run again with RD_FULL_OUTPUT=1 in the command for all) ..."]
            + kept[-TAIL:]
        )
    sys.stdout.write("\n".join(kept) + ("\n" if kept else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
