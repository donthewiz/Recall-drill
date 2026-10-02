"""Recall Drill add-on entry point. Anki imports this folder as a package.

Tools-menu items: the About box, and (Phase 2, temporary) a dev preview of
what the drill reads from the current deck.

The guard keeps this file importable outside Anki: pytest imports it as a
package node, with no parent package for the relative import to resolve.
"""

if __package__:
    import os

    from .recalldrill.ui.about import register_menu
    from .recalldrill.ui.preview import register_preview_menu

    register_menu()
    # Local, non-syncing data (user_files/ survives add-on upgrades).
    register_preview_menu(os.path.join(os.path.dirname(__file__), "user_files"))
