"""The ``llm-rosetta argo`` commands."""

from __future__ import annotations

from collections.abc import Sequence

from . import tunnel as _tunnel


def tunnel(argv: Sequence[str] | None = None) -> int:
    """Open and manage the SSH tunnel to the Argo endpoint."""
    return _tunnel.main(argv, prog="llm-rosetta argo tunnel")


#: Verb to callable; ``llm-rosetta argo tunnel ...`` calls ``tunnel(argv)``.  The
#: standalone ``scripts/argo-tunnel.py`` runs the same code under its own name.
COMMANDS = {"tunnel": tunnel}
