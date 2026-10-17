"""Math Path add-on entry point. Anki imports this folder as a package.

Wires the Tools → Math Path menu and the reviewer hooks (``math_path/ui/entry.py``).

The guard keeps this file importable outside Anki: pytest imports it as a package node, with no
parent package for the relative import to resolve.
"""

if __package__:
    import os

    from .math_path.ui.entry import register

    # Local, non-syncing data (user_files/ survives add-on upgrades).
    register(__name__, os.path.join(os.path.dirname(__file__), "user_files"))
