"""A paint write changes one actor, never its relatives (graphics review R5).

HP1 (2026-10-08): ``set_alpha`` and ``Color.alpha =`` mutated the material in
place, and default paint is one shared Color. ``Circle().set_alpha(0.3)``
turned every later default Circle and Rect to alpha 0.3, across acts. The
same write leaked through ``clone()``, ``look_like``, ``save_visual`` /
``restore_visual`` (the snapshot shared the Color), and a Gradient shared by
two shapes.

The guard enumerates paint-writing verbs × kinds × relatives of the written
actor:

* another default actor made before the write, and one made after;
* a clone made before the write;
* the actor a ``look_like`` copied from, and the actor that copied it;
* the actor's own ``save_visual`` snapshot, read after ``restore_visual``;
* a second actor that shares the same Gradient.

The oracle is each relative's paint reads and its pixels, compared before and
after the write. Known violations are shrink-only
(``graphics_known.MATERIAL``).

    python tests/run_tiers.py focused test_material_isolation
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402

from hypothesis_support import fresh_world, quiet  # noqa: E402
from test_diff_draw import render  # noqa: E402

import scena  # noqa: E402

KINDS = {
    "Circle": lambda: scena.Circle(center=(80, 60), radius=20),
    "Rect": lambda: scena.Rect(center=(80, 60), width=50, height=30),
    "Ellipse": lambda: scena.Ellipse(center=(80, 60), width=50, height=30),
    "Polygon": lambda: scena.Polygon(points=[(60, 40), (100, 45), (85, 80)]),
    "RegularPolygon": lambda: scena.RegularPolygon(center=(80, 60), radius=20, n=6),
    "Line": lambda: scena.Line(p1=(50, 50), p2=(110, 70)),
}

WRITES = {
    "set_alpha(0.3)": lambda o: o.set_alpha(0.3),
    "color.alpha = 0.2": lambda o: setattr(o.color, "alpha", 0.2),
    "fill.alpha = 0.2": lambda o: setattr(o.fill, "alpha", 0.2),
    "set_color('blue')": lambda o: o.set_color("blue"),
    "fill = 'green'": lambda o: setattr(o, "fill", "green"),
    "line_width = 6": lambda o: setattr(o, "line_width", 6),
}


def _mat(m):
    if type(m).__name__ == "Color":
        return ("Color",) + tuple(round(float(c), 6) for c in m.rgb)
    colors = getattr(m, "_colors", None)
    if colors is not None:
        return (type(m).__name__,) + tuple(_mat(c) for c in colors)
    return type(m).__name__


def paint(obj) -> tuple:
    with quiet():
        return (_mat(obj.fill), _mat(obj.line), round(float(obj.line_width), 6))


def look(obj):
    """Paint reads plus pixels (the paint a read can miss: a cached Skia paint)."""
    return paint(obj), render([obj]).tobytes()


def _relatives(kind, subject):
    """(name, relative, reader) built BEFORE the write; ``reader`` reads it later."""
    make = KINDS[kind]
    out = [("other default", make(), look)]
    clone = subject.clone()
    out.append(("clone", clone, look))
    src = make()
    src.set_color("orchid")
    copier = make()
    copier.look_like(subject)
    out.append(("look_like copier", copier, look))
    return out, src


def isolation_violations() -> dict:
    out = {}
    with fresh_world() as w:
        for kind, make in KINDS.items():
            for wname, write in WRITES.items():
                key = f"{kind} | {wname}"
                defaults = _default_paints()     # HP1: put the shared prototypes back after
                # Relatives of a default-painted subject.
                subject = w.track(make())
                fresh_before = look(make())
                rels, src = _relatives(kind, subject)
                w.track(src)
                for _n, r, _f in rels:
                    w.track(r)
                # The look_like source: the subject copies from it, then is written.
                taker = w.track(make())
                taker.look_like(src)
                src_before = look(src)
                before = {n: f(r) for n, r, f in rels}
                subject.save_visual()
                saved = look(subject)
                try:
                    with quiet():
                        write(subject)
                        write(taker)
                except Exception:  # noqa: BLE001  (a refused write changes nothing here)
                    pass
                for n, r, f in rels:
                    if f(r) != before[n]:
                        out[f"{key} | {n}"] = ""
                if look(src) != src_before:
                    out[f"{key} | look_like source"] = ""
                if look(w.track(make())) != fresh_before:
                    out[f"{key} | default made after"] = ""
                subject.restore_visual()
                if look(subject) != saved:
                    out[f"{key} | save_visual snapshot"] = ""
                _restore(defaults)
            # A Gradient two actors share.
            for wname in ("set_alpha(0.3)",):
                g = scena.Gradient("red", "blue")
                a, b = w.track(make()), w.track(make())
                a.fill = g
                b.fill = g
                b_before = look(b)
                with quiet():
                    try:
                        WRITES[wname](a)
                    except Exception:  # noqa: BLE001
                        pass
                if look(b) != b_before:
                    out[f"{kind} | {wname} | shared Gradient"] = ""
    return out


def _default_paints():
    from test_refusal_atomic import _default_paints as snap
    return snap()


def _restore(defaults):
    for mat, a in defaults:
        object.__setattr__(mat, "_a", a)


class TestMaterialIsolation(unittest.TestCase):
    def test_a_paint_write_stays_on_its_actor(self):
        from graphics_known import shrink_only
        shrink_only(self, isolation_violations(), "MATERIAL")

    def test_canary_set_color_that_paints_the_shared_material(self):
        from diff_support import assert_catches
        from scena.style import PaintState

        def bad_set_color(self, *a, **k):
            object.__setattr__(self.fill, "_g", 0.9)   # writes into the shared Color
            return self
        assert_catches(self, "test_material_isolation.TestMaterialIsolation.test_a_paint_write_stays_on_its_actor",
                       [(PaintState, "set_color", bad_set_color)], "a colour write into a shared material")


class TestPaintWritesStayPut(unittest.TestCase):
    """HP2 / HP3 / HP4 (graphics review): a paint knob kept by every path."""

    def test_liquify_leaves_the_cached_fill_alpha_alone(self):
        # HP2: the ghost alpha was written into the shape's cached fill paint,
        # so a Gradient body drew at the ghost's alpha afterwards.
        # The ghost pass is skipped at lite fidelity, so the helper every ghost
        # look calls is tested directly.
        from scena.recipes import _host_fill_paint
        with fresh_world() as w:
            c = w.track(scena.Circle(center=(80, 60), radius=25))
            c.fill = scena.Gradient("red", "blue")
            before = c._to_skia_fill_paint().getAlphaf()
            ghost = _host_fill_paint(c, alpha=0.3)
            self.assertAlmostEqual(ghost.getAlphaf(), 0.3)
            self.assertAlmostEqual(c._to_skia_fill_paint().getAlphaf(), before)

    def test_a_refused_look_keeps_the_current_one(self):
        # HP3: a sprite-only look on a Shape stripped the current look first.
        with fresh_world() as w:
            c = w.track(scena.Circle(center=(80, 60), radius=25))
            c.visual = scena.Halo()
            look, pixels = c.visual, render([c]).tobytes()
            with self.assertRaises(TypeError):
                c.visual = scena.Recolor("red")
            self.assertIs(c.visual, look)
            self.assertEqual(render([c]).tobytes(), pixels)

    def test_sprite_restore_visual_keeps_alpha(self):
        # HP4: restore_visual reset a Sprite's body alpha to 1.0.
        from tests.media_support import media
        with fresh_world() as w:
            s = w.track(scena.Sprite(media("space", "enemyGreen1.png"), center=(80, 60), height=60))
            s.alpha = 0.4
            s.save_visual()
            s.alpha = 0.9
            s.visual = scena.Recolor("red")
            s.restore_visual()
            self.assertAlmostEqual(s.alpha, 0.4)
            self.assertIsNone(s.visual)

    def test_color_alpha_is_read_only_and_names_the_fix(self):
        c = scena.Color("red")
        with self.assertRaises(AttributeError) as cm:
            c.alpha = 0.5
        self.assertIn("with_alpha", str(cm.exception))
        self.assertIn("set_alpha", str(cm.exception))
        self.assertEqual(c.alpha, 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
