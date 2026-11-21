"""Argo (Argonne) provider shims for llm-rosetta, delivered as a plugin package.

llm-rosetta discovers the ``llm_rosetta.shim_providers`` entry point and calls
:func:`register_shims`, which loads this package's bundled shim directory into
the shim registry.  Shims registered this way behave exactly like the built-in
ones; a plugin shim of the same name replaces the built-in (the loader runs
plugins last).
"""

from __future__ import annotations

from pathlib import Path

__version__ = "0.3.0"

_PROVIDERS_DIR = Path(__file__).parent / "providers"


def register_shims() -> None:
    """Load the bundled ``argo--*`` shims into llm-rosetta.

    The import is local so that importing this package does not require
    llm-rosetta to be installed.  The ``argo-tunnel`` console script
    lives here too, and it talks to ssh, not to the core library: an
    operator who only wants the tunnel should not have to install the
    translation layer to get it.

    Entry point for the ``llm_rosetta.shim_providers`` group.
    """
    from llm_rosetta.contracts.shim import load_providers_from_dir

    load_providers_from_dir(_PROVIDERS_DIR)
