"""
A SpatialFx kind's float knobs are fields: ``=``, ``tween``, ``@=`` and a
constructor function all reach the value the effect draws.

``amount=`` / ``speed=`` / ``twist=`` … were plain attributes stored in
``__init__``: ``luz["amount"] @= lambda: …`` (tutorial 23) made an ink field
the attribute shadowed, so the glow never followed, and
``tween(warp["amount"], …)`` raised "the field itself (the handle)"
(showcase B1, 2026-10-23). The same shadow caught an author's own value
written above ``super().__init__()``: a bracket now moves a plain number or
string into the field it reaches.

Bug class guarded: an object attribute a bracket link cannot reach while the
bracket accepts the link (a silently dead ``@=``), and a constructor knob
added as a plain attribute (``test_no_public_float_left_plain`` walks every
public kind and every Fire style).

Run:

    python tests/run_tiers.py focused test_fx_knobs
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from program_support import FRAME  # noqa: E402
from system_support import boot, system_world  # noqa: E402

import scena  # noqa: E402
from scena import Circle, GlowSpot, Warp, st, tween  # noqa: E402
from scena.spatial_fx import SpatialFx, _fx_knob_names  # noqa: E402
from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()

boot()


FIRE_STYLES = ("plume", "blaze", "tongues", "embers", "soft")


def kinds():
    """Every public kind (Fire once per style), as ``(label, factory)``."""
    out = []
    for name in scena.__all__:
        cls = getattr(scena, name)
        if not (isinstance(cls, type) and issubclass(cls, SpatialFx)) or cls is SpatialFx:
            continue
        if name == "Rain":
            out.append((name, lambda c=cls: c(p1=(100, 100), p2=(200, 200))))
        elif name == "Jet":
            out.append((name, lambda c=cls: c(p1=(100, 100), p2=(200, 100))))
        else:
            out.append((name, lambda c=cls: c(center=(150, 150))))
    for style in FIRE_STYLES:
        out.append((f"Fire({style})", lambda s=style: scena.Fire(style=s, center=(150, 150))))
    return out


class TestKnobsAreFields(unittest.TestCase):
    def test_every_knob_takes_set_link_and_tween(self):
        seen = set()
        with system_world(draw=True) as w:
            for label, make in kinds():
                fx = make()
                knobs = _fx_knob_names(type(fx))
                for name in knobs:
                    with self.subTest(kind=label, knob=name):
                        seen.add(name)
                        setattr(fx, name, 0.7)
                        self.assertAlmostEqual(getattr(fx, name), 0.7)
                        st.k = 0.25
                        fx[name] @= lambda: 0.5 + st.k
                        self.assertAlmostEqual(getattr(fx, name), 0.75)
                        st.k = 1.0
                        w.step(1, dt=FRAME)
                        self.assertAlmostEqual(getattr(fx, name), 1.5)
                        fx[name].unlink()
                        h = tween(fx[name], 2.0, time=0.05)
                        w.step(6, dt=FRAME)
                        self.assertTrue(h.done)
                        self.assertAlmostEqual(getattr(fx, name), 2.0)
                fx.destroy()
        self.assertTrue({"amount", "speed", "twist", "glow", "rate"} <= seen, seen)

    def test_constructor_function_links(self):
        with system_world(draw=False) as w:
            st.k = 0.0
            fx = Warp(center=(100, 100), amount=lambda: 1 + st.k, twist=lambda: st.k)
            self.assertAlmostEqual(fx.amount, 1.0)
            st.k = 0.5
            w.step(1, dt=FRAME)
            self.assertAlmostEqual(fx.amount, 1.5)
            self.assertAlmostEqual(fx.twist, 0.5)
            self.assertTrue(fx["amount"].is_linked)

    def test_portal_angle_links_and_tweens(self):
        from scena import Portal
        with system_world(draw=True) as w:
            st.k = 0.0
            p = Portal(center=(100, 100), tilt=0.5, angle=lambda: 10 + 100 * st.k)
            st.k = 0.5
            w.step(1, dt=FRAME)
            self.assertAlmostEqual(p.angle, 60.0)
            p["angle"].unlink()
            h = tween(p["angle"], 90.0, time=0.05)
            w.step(6, dt=FRAME)
            self.assertTrue(h.done)
            self.assertAlmostEqual(p.angle, 90.0)
            p.angle = 15
            self.assertAlmostEqual(p.angle, 15.0)
            p.destroy()

    def test_tutorial_23_glow_follows_its_formula(self):
        # estudio_voz: luz["amount"] @= lambda: 0.3 + st.voz
        with system_world(draw=False) as w:
            st.voz = 0.0
            luz = GlowSpot(center=(100, 100), color="gold")
            luz["amount"] @= lambda: 0.3 + st.voz
            st.voz = 0.6
            w.step(1, dt=FRAME)
            self.assertAlmostEqual(luz.amount, 0.9)

    def test_no_public_float_left_plain(self):
        # A float a kind keeps as a plain attribute is one a bracket cannot
        # link: each public float of a built effect is a slot (or a property).
        with system_world(draw=False):
            for label, make in kinds():
                fx = make()
                plain = sorted(
                    k for k, v in vars(fx).items()
                    if not k.startswith("_") and type(v) is float
                    and k not in _fx_knob_names(type(fx))
                    and k not in fx._field_slots()
                )
                with self.subTest(kind=label):
                    # soft_edge, a plain field of every effect, moves into
                    # the field a bracket reaches.
                    self.assertEqual([k for k in plain if k != "soft_edge"], [], label)
                fx.destroy()


class TestBracketOnPlainValue(unittest.TestCase):
    def test_value_written_before_super_init_links(self):
        class Hero(Circle):
            def __init__(self, **kw):
                self.hp = 3
                super().__init__(**kw)

        with system_world(draw=False) as w:
            st.k = 0.0
            hero = Hero(center=(10, 10), radius=5)
            self.assertEqual(hero.hp, 3)
            hero["hp"] @= lambda: 10 * st.k
            st.k = 0.4
            w.step(1, dt=FRAME)
            self.assertAlmostEqual(hero.hp, 4.0)
            hero["hp"].unlink()
            hero.hp = 7
            self.assertEqual(hero.hp, 7)
            hero.destroy()

    def test_a_string_written_before_super_init_links(self):
        # The CHANGELOG says "a number or string" (release audit: only the
        # number had a test).
        class Hero(Circle):
            def __init__(self, **kw):
                self.title = "novice"
                super().__init__(**kw)

        with system_world(draw=False) as w:
            st.level = 1
            hero = Hero(center=(10, 10), radius=5)
            self.assertEqual(hero.title, "novice")
            hero["title"] @= lambda: f"level {st.level}"
            st.level = 2
            w.step(1, dt=FRAME)
            self.assertEqual(hero.title, "level 2")
            hero.destroy()

    def test_migration_keeps_the_other_fields(self):
        # ``_ink`` is a slot on shapes: the move must add to the object's
        # ink, never replace it (a first draft read ``__dict__`` and would
        # have dropped every field made after construction).
        class Hero(Circle):
            def __init__(self, **kw):
                self.hp = 3
                super().__init__(**kw)

        with system_world(draw=False):
            hero = Hero(center=(10, 10), radius=5)
            hero.mana = 9
            st.k = 0.4
            hero["hp"] @= lambda: 10 * st.k
            self.assertEqual((hero.hp, hero.mana), (4.0, 9))
            hero.destroy()

    def test_value_written_before_super_init_tweens(self):
        class Hero(Circle):
            def __init__(self, **kw):
                self.hp = 3.0
                super().__init__(**kw)

        with system_world(draw=False) as w:
            hero = Hero(center=(10, 10), radius=5)
            h = tween(hero["hp"], 0.0, time=0.05)
            w.step(6, dt=FRAME)
            self.assertTrue(h.done)
            self.assertAlmostEqual(hero.hp, 0.0)
            hero.destroy()

    def test_non_scalar_plain_value_refuses(self):
        class Hero(Circle):
            def __init__(self, **kw):
                self.bag = [1, 2]
                super().__init__(**kw)

        with system_world(draw=False):
            hero = Hero(center=(10, 10), radius=5)
            with self.assertRaises(AttributeError) as cm:
                hero["bag"] @= lambda: [3]
            self.assertIn("hero.bag", str(cm.exception))
            hero.destroy()


if __name__ == "__main__":
    unittest.main()
