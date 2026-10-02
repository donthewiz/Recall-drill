"""Package the add-on as ``dist/recall_drill-<version>.ankiaddon``.

    python anki-addon/build.py [--allow-dirty] [--skip-tests] [--out DIR]

An .ankiaddon is a zip of the add-on folder's *contents* (no top-level folder)
with a ``manifest.json`` at its root. Only the runtime files go in: the
package, ``config.json``/``config.md``, and ``user_files/README.txt``. Tests,
tools, docs, the venv and build files stay out. ``user_files/`` otherwise holds
the user's own data and is never packaged.

The build refuses to run on a dirty git tree (``--allow-dirty`` overrides, for
the test) and when any ``tests/engine`` test fails (``--skip-tests`` overrides,
for the test). The version comes from ``VERSION`` in ``recalldrill/__init__.py``;
the minimum Anki version from ``manifest.json`` (docs/DECISIONS.md, Versions).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PACKAGE = "recall_drill"
NAME = "Recall Drill"

TOP_FILES = ("__init__.py", "config.json", "config.md")
"""Root files that go in the package, besides the manifest."""
README = "user_files/README.txt"

_ZIP_TIME = (2020, 1, 1, 0, 0, 0)
"""Fixed entry timestamp, so the same sources always zip to the same bytes."""


class BuildError(RuntimeError):
    """The build refused to run or can't package."""


def read_version(root: Path = ROOT) -> str:
    text = (root / "recalldrill" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^VERSION\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if match is None:
        raise BuildError("recalldrill/__init__.py has no VERSION constant")
    return match.group(1)


def package_files(root: Path = ROOT) -> list[str]:
    """The files that go in the package, as sorted posix paths (the manifest is added apart)."""
    files = list(TOP_FILES) + [README]
    files += [
        p.relative_to(root).as_posix()
        for p in (root / "recalldrill").rglob("*.py")
        if "__pycache__" not in p.parts
    ]
    missing = [f for f in files if not (root / f).is_file()]
    if missing:
        raise BuildError(f"missing files: {', '.join(missing)}")
    return sorted(set(files))


def manifest(root: Path = ROOT, *, mod: int | None = None) -> dict[str, object]:
    base = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    return {
        "package": PACKAGE,
        "name": NAME,
        "min_point_version": base["min_point_version"],
        "human_version": read_version(root),
        "mod": int(time.time()) if mod is None else mod,
    }


def check_clean(root: Path = ROOT) -> None:
    out = subprocess.run(
        ["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True, check=False
    )
    if out.returncode != 0:
        raise BuildError(f"git status failed: {out.stderr.strip()}")
    if out.stdout.strip():
        raise BuildError(
            "the git tree is dirty; commit or stash first (or --allow-dirty):\n" + out.stdout
        )


def run_engine_tests(root: Path = ROOT) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/engine", "-q"], cwd=root, check=False
    )
    if result.returncode != 0:
        raise BuildError("tests/engine failed; not packaging")


def build(
    root: Path = ROOT,
    out_dir: Path | None = None,
    *,
    allow_dirty: bool = False,
    skip_tests: bool = False,
) -> Path:
    if not allow_dirty:
        check_clean(root)
    if not skip_tests:
        run_engine_tests(root)
    out_dir = out_dir if out_dir is not None else root / "dist"
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = manifest(root)
    target = out_dir / f"{PACKAGE}-{meta['human_version']}.ankiaddon"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        entries: list[tuple[str, bytes]] = [
            ("manifest.json", (json.dumps(meta, indent=2) + "\n").encode("utf-8"))
        ]
        entries += [(f, (root / f).read_bytes()) for f in package_files(root)]
        for name, data in sorted(entries):
            info = zipfile.ZipInfo(name, _ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, data)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--allow-dirty", action="store_true", help="build from a dirty git tree")
    parser.add_argument("--skip-tests", action="store_true", help="don't run tests/engine first")
    parser.add_argument("--out", type=Path, help="output folder (default: anki-addon/dist)")
    args = parser.parse_args(argv)
    try:
        target = build(ROOT, args.out, allow_dirty=args.allow_dirty, skip_tests=args.skip_tests)
    except BuildError as exc:
        print(f"build refused: {exc}", file=sys.stderr)
        return 1
    with zipfile.ZipFile(target) as z:
        names = z.namelist()
    print(f"{target} ({target.stat().st_size} bytes, {len(names)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
