"""ALCF (Argonne Leadership Computing Facility): three cluster shims and the Globus credential exchange (auth.py).

The folder is the package, imported as ``llm_rosetta_ext.alcf``; it holds the
shim tree (``provider.yaml`` and the lane folders) and the sidecars the loader
reads.
"""

from __future__ import annotations

__all__ = ["__version__"]
__version__ = "0.4.0"
