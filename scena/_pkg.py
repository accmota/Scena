"""The framework's own package name, for "is this a framework class?" checks.

Derived from ``__name__`` so no check spells the package as a literal (the
package was renamed in 0.6.0; a literal would silently stop matching).
"""
from __future__ import annotations

PKG = __name__.split(".")[0]


def is_framework_module(mod: str) -> bool:
    """True for the package and its submodules (``scena``, ``scena.shapes``),
    never for a sibling that only shares the prefix (``scena_editor``)."""
    return mod == PKG or mod.startswith(PKG + ".")
