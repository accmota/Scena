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


class RetiredClassMeta(type):
    """Metaclass of a retired class name's stub (``Scene``, ``EquilateralTriangle``).

    The stub raises when called or subclassed; ``isinstance`` / ``issubclass``
    against it raise too (they were silently False, so an old type test skipped
    its branch: A3 of RA 0.9.0). The stub names the fix in
    ``_retired_type_test(spelling)``, ``spelling`` being ``"isinstance(x, {new})"``
    shaped text built here."""

    def __instancecheck__(cls, obj):
        raise TypeError(cls._retired_type_test("isinstance(x, {new})"))

    def __subclasscheck__(cls, sub):
        raise TypeError(cls._retired_type_test("issubclass(cls, {new})"))
