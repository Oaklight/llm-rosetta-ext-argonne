"""Load this extension's folder in place, as core's extension loader does.

The folder is the package ``llm_rosetta_ext.argo``.  Binding it here lets the
tests import its modules without installing the wheel, and the ``register``
fixture loads its shim tree into a clean registry.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from llm_rosetta.api import load_providers_from_dir, staging_registry
from llm_rosetta.testing import restore_registry, snapshot_registry

_PACKAGES = Path(__file__).resolve().parents[2]
_FOLDER = _PACKAGES / "argo"


def _bind_package() -> None:
    if "llm_rosetta_ext.argo" in sys.modules:
        return
    namespace = sys.modules.setdefault("llm_rosetta_ext", types.ModuleType("llm_rosetta_ext"))
    if not hasattr(namespace, "__path__"):
        namespace.__path__ = []  # type: ignore[attr-defined]
    spec = importlib.util.spec_from_file_location(
        "llm_rosetta_ext.argo",
        _FOLDER / "__init__.py",
        submodule_search_locations=[str(_FOLDER)],
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["llm_rosetta_ext.argo"] = module
    spec.loader.exec_module(module)
    # Also bind it on the namespace, so a dotted path such as
    # monkeypatch.setattr("llm_rosetta_ext.argo.x", ...) resolves.
    setattr(namespace, "argo", module)


_bind_package()


@pytest.fixture()
def register() -> Iterator[Callable[..., None]]:
    """Return ``register(*vendors)``: load those folders into a clean registry."""
    saved = snapshot_registry()

    def _register(*vendors: str) -> None:
        with staging_registry():  # starts empty: only these vendors are present
            for vendor in vendors:
                load_providers_from_dir(_PACKAGES, only_paths=(vendor,))

    yield _register
    restore_registry(saved)
