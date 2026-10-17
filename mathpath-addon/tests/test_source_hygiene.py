"""Math Path's own files carry no invisible characters and no CRLF: write them as escapes."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVISIBLE = re.compile("[\u2028\u2029\u00a0\u2007\u202f\u200b-\u200d\u2060\ufeff\ue000-\uf8ff]")
SKIP = ("core/", "vendor/", "web/mathlive/")
TEXT = {".py", ".md", ".json", ".js", ".css", ".txt", ".toml", ".yml"}


def own_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z", "."], cwd=ROOT, capture_output=True, check=True
    ).stdout.decode()
    names = [n for n in out.split("\0") if n and not n.startswith(SKIP)]
    return [ROOT / n for n in names if Path(n).suffix in TEXT]


def test_no_invisible_characters_and_lf_line_endings() -> None:
    files = own_files()
    assert files
    for path in files:
        raw = path.read_bytes()
        assert b"\r" not in raw, f"{path.name} has CR line endings"
        found = sorted({hex(ord(c)) for c in INVISIBLE.findall(raw.decode("utf-8"))})
        assert not found, f"{path.relative_to(ROOT)} holds invisible characters {found}"
