"""Card Triage add-on entry point. Anki imports this folder as a package.

Wires the Tools → Card Triage menu and the reviewer hooks (``card_triage/ui/entry.py``).

The guard keeps this file importable outside Anki: pytest imports it as a package node, with no
parent package for the relative import to resolve.
"""

if __package__:
    from .card_triage.ui.entry import register

    register(__name__)
