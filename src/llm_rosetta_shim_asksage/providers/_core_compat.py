"""Transition bridge for llm-rosetta cores before 0.14.0.dev35.

Core 0.14.0.dev35 moved the shim-facing names into ``llm_rosetta.contracts``.
A gateway preset tracks this repository's ``main`` with no pinned ref, so a
merged commit reaches gateways still running an older core; each name below is
taken from ``llm_rosetta.contracts`` when the core has it and from its earlier
home otherwise.  Remove this module once ``llm-rosetta>=0.14.0`` is the floor,
and no later than 0.15.0.

It lives under ``providers/`` because the release archive is rooted there: a
module outside that directory would not ship to a gateway that loads the
archive, and ``transforms.py`` reaches this one by relative import inside the
loader's namespace for the providers root.

``auth.py`` carries the same ``try``/``except`` inline instead of importing
this module: the loader executes it as a top-level module, so it has no
package to import this one relatively from.  Its names are listed here as
well, so the tests take them from one place and check that both agree.

It must not import ``llm_rosetta.api``: the entry point runs during
``import llm_rosetta``, when that module cannot be imported yet.
"""

from __future__ import annotations

try:
    from llm_rosetta.contracts.shim import (
        load_providers_from_dir,
    )
except ImportError:  # a core before 0.14.0.dev35
    from llm_rosetta.shims import (  # type: ignore[no-redef]
        load_providers_from_dir,
    )

try:
    from llm_rosetta.contracts.auth import (
        AuthContext,
        AuthExchangeError,
        BaseAuthExchange,
    )
except ImportError:  # a core before 0.14.0.dev35
    from llm_rosetta.shims.auth_exchange import (  # type: ignore[no-redef]
        AuthContext,
        AuthExchangeError,
        BaseAuthExchange,
    )

try:
    from llm_rosetta.contracts.transform import (
        rename_field,
    )
except ImportError:  # a core before 0.14.0.dev35
    from llm_rosetta.transforms import (  # type: ignore[no-redef]
        rename_field,
    )

__all__ = [
    "AuthContext",
    "AuthExchangeError",
    "BaseAuthExchange",
    "load_providers_from_dir",
    "rename_field",
]
