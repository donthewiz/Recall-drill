"""Recall Drill add-on entry point. Anki imports this folder as a package.

Wires the entry points (``recalldrill/ui/entry.py``): Tools → "Recall Drill…",
the deck gear menu, the deck overview's button, and the About box.

The guard keeps this file importable outside Anki: pytest imports it as a
package node, with no parent package for the relative import to resolve.
"""

if __package__:
    import os

    from .recalldrill.ui.about import register_menu
    from .recalldrill.ui.entry import register

    # Local, non-syncing data (user_files/ survives add-on upgrades).
    register(__name__, os.path.join(os.path.dirname(__file__), "user_files"))
    register_menu()
