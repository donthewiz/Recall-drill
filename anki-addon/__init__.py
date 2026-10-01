"""Recall Drill add-on entry point. Anki imports this folder as a package.

Phase 0: one Tools-menu item that shows an About box. Nothing else.

The guard keeps this file importable outside Anki: pytest imports it as a
package node, with no parent package for the relative import to resolve.
"""

if __package__:
    from .recalldrill.ui.about import register_menu

    register_menu()
