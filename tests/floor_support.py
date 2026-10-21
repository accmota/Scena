"""A world with a floor, for the tests of gravity scenes.

``collision.floor`` is off in a fresh world (2026-10-21, Collision Design "A
world with a floor"): nothing stands on anything. The tests written for
walkers, ramps, lifts, seam steps and resting piles describe worlds with
gravity, so they run with a floor, as a game with gravity writes
``collision.floor = True``::

    from floor_support import with_floor

    @with_floor
    class TestRiderCarry(unittest.TestCase): ...

Every collision system made while a test runs (``reset_collision_system()``
in a ``setUp``, a fresh world) starts with a floor; the test's end gives the
default back. A whole module: ``setUpModule, tearDownModule = floor_module()``.
"""
from __future__ import annotations

import functools
import importlib

from scena.collision import get_collision_system

# The module, not the author's ``collision`` object of the same name.
_collision = importlib.import_module("scena.collision")


def _on() -> bool:
    was = _collision._FLOOR_DEFAULT
    _collision._FLOOR_DEFAULT = True
    get_collision_system().floor = True
    return was


def _off(was: bool) -> None:
    _collision._FLOOR_DEFAULT = was
    get_collision_system().floor = was


def with_floor(cls):
    """Class decorator: every test of ``cls`` runs in a world with a floor."""
    setup, teardown = cls.setUp, cls.tearDown

    @functools.wraps(setup)
    def set_up(self):
        self._floor_was = _on()
        setup(self)
        get_collision_system().floor = True    # a setUp that made a new system

    @functools.wraps(teardown)
    def tear_down(self):
        try:
            teardown(self)
        finally:
            _off(getattr(self, "_floor_was", False))

    cls.setUp, cls.tearDown = set_up, tear_down
    return cls


def floor_module():
    """``setUpModule, tearDownModule`` for a module of gravity scenes."""
    state = {}

    def set_up_module():
        state["was"] = _on()

    def tear_down_module():
        _off(state.get("was", False))

    return set_up_module, tear_down_module
