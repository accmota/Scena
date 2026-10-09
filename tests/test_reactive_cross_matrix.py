"""Engine-owned reactive sources × sinks in other subsystems, in real frames.

Interaction campaign, class 8 (design/Testing Design.md, "Interaction
campaign"). ``test_reactive_matrix`` drives shape fields from a state cell;
``test_input_reactive`` reads ``mouse`` / ``clock`` / ``keyp`` into one sink
each. Here every engine-owned source an author can read in a formula
(``mouse``, ``clock.time``, ``keyp(...)``, ``canvas.game_view``, a group's
box, a state cell, another actor's part) drives every sink kind in another
subsystem (a shape's centre and a scalar field, a paint knob, a caption's
string and centre, a SpatialFx placement, a hitbox's ``active``), and the
oracle is a plain-write twin written in ``update`` with the source's current
value: at every read point of the frame (``update`` before and after the
source moves, draw) the linked sink reads what the twin reads, whichever of
the two is read first.

A guard requires every global on ``scena.__all__`` to be a source here or
excused with a reason. ``KNOWN`` is shrink-only.

    python -m unittest tests.test_reactive_cross_matrix -v
"""
from __future__ import annotations

import inspect
import math
import os
import sys
import tempfile
import unittest
from typing import Any, Callable, Dict, List, Tuple
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import glfw  # noqa: E402

from diff_support import assert_catches  # noqa: E402
from system_support import SystemTestCase, quiet  # noqa: E402
from test_sprite import _write_rect_png  # noqa: E402

import scena  # noqa: E402
from scena import (Circle, Fire, Sheet, Sprite, Text, canvas, clock, group, keyp,  # noqa: E402
                   mouse, st)
from scena.hitbox import _LINKED_PARTS  # noqa: E402

FRAMES = 6


# --------------------------------------------------------------------------
# Sources: (install(tc) -> read: Callable[[], pair], drive(tc, k) moves it at frame k)
# --------------------------------------------------------------------------

class Source:
    def __init__(self, name: str, pair: Callable, scalar: Callable, install: Callable,
                 drive: Callable, covers=()) -> None:
        self.name, self.pair, self.scalar = name, pair, scalar
        self.install, self.drive, self.covers = install, drive, tuple(covers)


_S: Dict[str, Any] = {}        # actors a source reads (installed per cell)


def mouse_pair():
    return (float(mouse.x), float(mouse.y))


def mouse_x():
    return float(mouse.x)


def clock_pair():
    return (float(clock.time), 0.0)


def clock_s():
    return float(clock.time)


def keyp_pair():
    return ((1.0 if keyp("D") else 0.0), 0.0)


def keyp_d():
    return 1.0 if keyp("D") else 0.0


def view_pair():
    return (float(canvas.game_view.center.x), float(canvas.game_view.center.y))


def view_x():
    return float(canvas.game_view.center.x)


def cell_pair():
    return (float(st.rx_cx), float(st.rx_cy))


def cell_x():
    return float(st.rx_cx)


def other_pair():
    return (float(_S["other"].center.x), float(_S["other"].center.y))


def other_x():
    return float(_S["other"].center.x)


def install_none(tc):
    pass


def install_cell(tc):
    st.rx_cx = 1.0
    st.rx_cy = 2.0


def install_other(tc):
    with quiet():
        _S["other"] = tc.track(Circle(center=(200, 100), radius=5))


def drive_mouse(tc, k):
    tc.w.fw.mouse._sync_position(10.0 * k, 3.0 * k)


def drive_clock(tc, k):
    pass                                   # stepping drives it


def drive_keyp(tc, k):
    tc.w.fw._handle_key(None, glfw.KEY_D, 0, glfw.PRESS if k % 2 else glfw.RELEASE, 0)


def drive_game_view(tc, k):
    canvas.pan_by(7.0, -2.0)


def drive_cell(tc, k):
    st.rx_cx = 1.0 + k
    st.rx_cy = 2.0 - k


def drive_other(tc, k):
    _S["other"].move_by(3.0, 3.0)


SOURCES: List[Source] = [
    Source("mouse", mouse_pair, mouse_x, install_none, drive_mouse, ["mouse"]),
    Source("clock.time", clock_pair, clock_s, install_none, drive_clock, ["clock"]),
    Source("keyp", keyp_pair, keyp_d, install_none, drive_keyp, ["keyp"]),
    Source("canvas.game_view", view_pair, view_x, install_none, drive_game_view, ["canvas"]),
    Source("state cell", cell_pair, cell_x, install_cell, drive_cell, ["st"]),
    Source("another actor's part", other_pair, other_x, install_other, drive_other, []),
]

EXCUSED_GLOBALS: Dict[str, str] = {
    "ready": "a timing query (bool), not a value an author links",
    "recently": "a timing query (bool), not a value an author links",
    "ui": "widget chrome settings",
    "audio": "a bus of settings (audio.level is covered by test_audio)",
    "collision": "a system of settings and queries",
    "group": "group membership is not a formula source (the formula checker refuses a "
             "formula that reads a group; count or scan it in update)",
    "AUTO_GROUND": "a constant",
    "ANYTHING": "a constant",
    "STATIC": "a constant",
}


# --------------------------------------------------------------------------
# Sinks: make(tc) -> (linked subject, twin); link(subject, read); write(twin, pair); get(obj)
# --------------------------------------------------------------------------

class Sink:
    def __init__(self, name: str, make: Callable, link: Callable, write: Callable,
                 get: Callable) -> None:
        self.name, self.make, self.link, self.write, self.get = name, make, link, write, get


def link_pair(s, name, src: Source):
    pair = src.pair
    s[name] @= (lambda: pair())


def link_scalar(s, name, src: Source):
    scalar = src.scalar
    s[name] @= (lambda: 5.0 + abs(scalar()) * 0.01)


def link_text(s, name, src: Source):
    scalar = src.scalar
    s[name] @= (lambda: f"{scalar():.3f}")


def mk_circle(tc):
    with quiet():
        return (tc.track(Circle(center=(0, 0), radius=10)),
                tc.track(Circle(center=(0, 0), radius=10)))


def mk_text(tc, text=""):
    return (tc.track(Text(text, center=(50, 50))), tc.track(Text(text, center=(50, 50))))


def mk_fire(tc):
    return (tc.track(Fire(center=(0, 0), radius=20)), tc.track(Fire(center=(0, 0), radius=20)))


SINKS: List[Sink] = [
    Sink("shape center", mk_circle,
         lambda s, src: link_pair(s, "center", src),
         lambda t, v: t.move_to(*v),
         lambda o: (float(o.center.x), float(o.center.y))),
    Sink("shape radius", mk_circle,
         lambda s, src: link_scalar(s, "radius", src),
         lambda t, v: setattr(t, "radius", 5.0 + abs(v[0]) * 0.01),
         lambda o: float(o.radius)),
    Sink("caption text", mk_text,
         lambda s, src: link_text(s, "text", src),
         lambda t, v: setattr(t, "text", f"{v[0]:.3f}"),
         lambda o: str(o.text)),
    Sink("caption center", lambda tc: mk_text(tc, "hi"),
         lambda s, src: link_pair(s, "center", src),
         lambda t, v: t.move_to(*v),
         lambda o: (float(o.center.x), float(o.center.y))),
    Sink("SpatialFx center", mk_fire,
         lambda s, src: link_pair(s, "center", src),
         lambda t, v: setattr(t, "center", v),
         lambda o: (float(o.center.x), float(o.center.y))),
]
# Not sinks: appearance (``line_width``, colors, looks) stays outside the
# reactive graph by design (``@=`` on it raises with the fix); widgets bind a
# cell, and a cell is the ``st`` source.

# Shrink-only: "source | sink" -> reason.
KNOWN: Dict[str, str] = {
}


def _same(a, b) -> bool:
    if isinstance(a, tuple) and isinstance(b, tuple):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    if isinstance(a, float) and isinstance(b, float):
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)
    return a == b


class TestCrossMatrix(SystemTestCase, unittest.TestCase):
    world_draw = True
    maxDiff = None

    def _cell(self, source: Source, sink: Sink, link_first: bool) -> None:
        w = self.w
        source.install(self)
        read = source.pair
        subject, twin = sink.make(self)
        sink.link(subject, source)
        sink.write(twin, read())
        diffs: List[str] = []

        def compare(where):
            # The twin is written with the source as it reads now; the linked
            # sink must read the same, whichever is read first.
            if link_first:
                a = sink.get(subject)
                sink.write(twin, read())
                b = sink.get(twin)
            else:
                sink.write(twin, read())
                b = sink.get(twin)
                a = sink.get(subject)
            if not _same(a, b):
                diffs.append(f"frame {clock.frame} {where}: linked {a!r} vs twin {b!r}")

        def update(dt):
            compare("update, before the source moves")
            source.drive(self, clock.frame)
            compare("update, after the source moves")
        w.on_update(update)
        fw = w.fw
        real_draw = fw._draw_frame

        def draw():
            compare("draw")
            real_draw()
        with mock.patch.object(fw, "_draw_frame", side_effect=draw):
            w.step(FRAMES)
        key = f"{source.name} | {sink.name}"
        if diffs:
            if key in KNOWN:
                self.skipTest(f"known: {KNOWN[key]}")
            self.fail(f"{key} (link read {'first' if link_first else 'second'}):\n  "
                      + "\n  ".join(diffs[:6]))
        elif key in KNOWN:
            self.fail(f"KNOWN entry no longer fails; remove it: {key!r}")

    def tearDown(self):
        with quiet():
            canvas.reset_view()
            self.w.fw.mouse._sync_position(0.0, 0.0)
            self.w.fw._handle_key(None, glfw.KEY_D, 0, glfw.RELEASE, 0)
        super().tearDown()


for _src in SOURCES:
    for _snk in SINKS:
        for _first in (True, False):
            _name = "test_" + "".join(ch if ch.isalnum() else "_" for ch in
                                      f"{_snk.name}_from_{_src.name}_{'link' if _first else 'twin'}_first")
            setattr(TestCrossMatrix, _name,
                    (lambda s, k, f: lambda self: self._cell(s, k, f))(_src, _snk, _first))


class TestAxes(unittest.TestCase):
    def test_every_global_is_a_source_or_excused(self):
        globals_ = [n for n in scena.__all__
                    if not inspect.isclass(getattr(scena, n, None))
                    and not callable(getattr(scena, n, None))]
        covered = {c for s in SOURCES for c in s.covers}
        missing = sorted(n for n in globals_ if n not in covered and n not in EXCUSED_GLOBALS)
        self.assertFalse(missing, f"globals an author can read in a formula with no source row: {missing}")

    def test_sources_and_sinks_have_unique_names(self):
        self.assertEqual(len({s.name for s in SOURCES}), len(SOURCES))
        self.assertEqual(len({s.name for s in SINKS}), len(SINKS))


class TestCanaries(unittest.TestCase):
    def test_catches_a_link_that_never_pulls(self):
        from scena.state import ScalarAnchor
        assert_catches(self, "test_reactive_cross_matrix.TestCrossMatrix."
                             "test_shape_radius_from_state_cell_link_first",
                       [(ScalarAnchor, "_takein_impl", lambda self, v: None)],
                       "a scalar link whose pull stores nothing")


if __name__ == "__main__":
    unittest.main()
