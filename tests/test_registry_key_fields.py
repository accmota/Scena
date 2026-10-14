"""
Handle fields that double as a registry / cache key must be read-only.

Bug class: a public field is also the key some registry stores the object
under. A plain write changes the field but not the registry, so the two
silently disagree. Instances fixed together (see Testing Design, bug
catalogue D-keys):

- ``Layer.name``           → ``canvas.layers`` key  (tests/test_registry_layers.py)
- ``Handle.name`` / ``.owner`` → scheduler slot ``(id(owner), name)``
- ``shape.group`` (in place) → registry ``group_map`` / collision tags
- interned looks / filters → intern cache key (``Neon("red")`` is shared)

Run headless:

    python -m unittest tests.test_registry_key_fields -v
"""

import inspect
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scena
from scena import Circle, after, canvas, clock, group, init
from scena.canvas import ScenaCanvas
from scena.entity import GroupTags
from scena.process import get_scheduler, reset_process_scheduler, tick_processes
from scena.recipes import Recolor
from scena.shapes import Point
from scena.style import FilterEffect
from scena.visuals import Visual


def _frame(real_dt=0.1):
    clock.advance(real_dt)
    tick_processes()


class _Case(unittest.TestCase):
    def setUp(self):
        init(width=1000, height=800)
        reset_process_scheduler()
        self._owned = []

    def tearDown(self):
        for s in self._owned:
            try:
                s.destroy()
            except Exception:
                pass
        reset_process_scheduler()

    def track(self, shape):
        self._owned.append(shape)
        return shape

    def circle(self, **kw):
        return self.track(Circle(center=(0, 0), radius=5, **kw))


class TestHandleSlotKey(_Case):
    def test_name_write_refused_and_slot_intact(self):
        h = after(10, lambda: None, name="spawn")
        with self.assertRaises(TypeError) as cm:
            h.name = "renamed"
        self.assertIn("name='renamed'", str(cm.exception))
        self.assertEqual(h.name, "spawn")
        h.cancel()
        # Regression: the renamed handle stayed parked in ``_named`` after
        # cancel because ``_forget`` rebuilt the key from the new name.
        self.assertFalse(
            any(v is h for v in get_scheduler()._named.values()),
            "cancelled handle must leave its name= slot",
        )

    def test_owner_write_refused_and_destroy_still_cancels(self):
        c = self.circle()
        d = self.circle()
        h = c.after(10, lambda: None, name="blink")
        with self.assertRaises(TypeError) as cm:
            h.owner = d
        self.assertIn("other.after", str(cm.exception))
        self.assertIs(h.owner, c)
        c.destroy()
        # Regression: after ``h.owner = d`` the job outlived its real owner.
        self.assertTrue(h.cancelled)

    def test_unnamed_handle_name_is_none_and_read_only(self):
        h = after(10, lambda: None)
        self.assertIsNone(h.name)
        with self.assertRaises(TypeError):
            h.name = "late"

    def test_named_slot_replacement_still_works(self):
        ran = []
        h1 = after(0.5, lambda: ran.append(1), name="tail")
        h2 = after(0.5, lambda: ran.append(2), name="tail")
        self.assertTrue(h1.cancelled)
        for _ in range(8):
            _frame()
        self.assertEqual(ran, [2])
        self.assertTrue(h2.done)


class TestGroupSnapshot(_Case):
    def test_group_is_read_only_snapshot(self):
        c = self.circle(group="enemies")
        self.assertIsInstance(c.group, GroupTags)
        self.assertIsInstance(c.group, frozenset)
        self.assertEqual(c.group, {"enemies"})

    def test_every_in_place_mutator_refused(self):
        # Bug class: any in-place set method bypassed group_map. Enumerate
        # them from ``set`` itself so a future mutator cannot slip past.
        c = self.circle(group="enemies")
        mutators = [
            m for m in dir(set)
            if not m.startswith("_") and m not in dir(frozenset)
        ]
        self.assertIn("add", mutators)
        for m in mutators:
            with self.subTest(method=m):
                fn = getattr(c.group, m)
                args = () if m in ("pop", "clear") else (
                    ({"boss"},) if m.endswith("update") else ("boss",)
                )
                with self.assertRaises(AttributeError) as cm:
                    fn(*args)
                self.assertIn("tag(", str(cm.exception))
        self.assertEqual(c.group, {"enemies"})
        self.assertNotIn(c, list(group["boss"]))
        self.assertIn(c, list(group["enemies"]))

    def test_augmented_assignment_rebinds_through_sync(self):
        c = self.circle(group="enemies")
        c.group |= {"boss"}
        self.assertIn(c, list(group["boss"]))
        c.group -= {"enemies"}
        self.assertNotIn(c, list(group["enemies"]))
        self.assertIsInstance(c.group, GroupTags)

    def test_tag_untag_keep_snapshot_and_index_in_sync(self):
        c = self.circle()
        before = c.group
        c.tag("a", "b")
        self.assertEqual(c.group, {"a", "b"})
        self.assertEqual(before, frozenset())  # old snapshot never changes
        c.untag("a")
        self.assertEqual(c.group, {"b"})
        self.assertEqual([m for m in group["a"]], [])
        self.assertIn(c, list(group["b"]))

    def test_bulk_tag_through_group_operator(self):
        c = self.circle(group="src")
        group["src"].tag("dst")
        self.assertIn("dst", c.group)
        self.assertIsInstance(c.group, GroupTags)


class TestInternedLooksFrozen(_Case):
    def test_recolor_key_write_refused(self):
        a = Recolor("blue", "tomato")
        b = Recolor("blue", "tomato")
        self.assertIs(a, b)
        with self.assertRaises(AttributeError) as cm:
            a.key = "red"
        self.assertIn("Recolor(key='red')", str(cm.exception))
        # Regression: the write leaked into b and into the next constructor.
        self.assertEqual(b.key, "blue")
        self.assertEqual(Recolor("blue", "tomato").key, "blue")

    def test_every_exported_interned_look_refuses_public_writes(self):
        # Bug class: any exported Visual / filter that interns. Covers
        # existing fields (color) and new names (typos landing silently).
        checked = []
        for name in dir(scena):
            cls = getattr(scena, name)
            if not (inspect.isclass(cls) and issubclass(cls, (Visual, FilterEffect))):
                continue
            try:
                a, b = cls(), cls()
            except TypeError:
                continue  # needs required args (e.g. ComposeFx)
            if a is not b:
                continue  # not interned (Tail, bases)
            checked.append(name)
            for field in ("color", "brand_new_field"):
                with self.subTest(look=name, field=field):
                    with self.assertRaises(AttributeError):
                        setattr(a, field, "red")
        self.assertGreaterEqual(len(checked), 40, checked)
        self.assertIn("Neon", checked)
        self.assertIn("Blur", checked)

    def test_the_suggested_call_builds_on_every_style(self):
        """RA 0.8.1: ``Bolt(style="filaments").amount = 6`` suggested
        ``Bolt(amount=6)`` (core: raises), ``Shield(style="nebula").color =``
        suggested ``Shield(color=…)`` (the bubble), and a Halo style named its
        private class (``HaloPulse(rings=5)``). Bug class: every styled look ×
        style × knob — the suggestion builds the same style, or the message
        carries the constructor's own refusal."""
        import re
        import typing
        checked = 0
        for name in scena.__all__:
            cls = getattr(scena, name)
            if not (inspect.isclass(cls) and issubclass(cls, (Visual, FilterEffect))):
                continue
            params = inspect.signature(cls).parameters
            if "style" not in params:
                continue
            styles = typing.get_args(typing.get_type_hints(cls.__init__)["style"])
            self.assertTrue(styles, name)
            for st in styles:
                look = cls(style=st)
                for knob in params:
                    if knob == "style" or not hasattr(look, knob):
                        continue
                    with self.subTest(look=name, style=st, knob=knob):
                        with self.assertRaises(AttributeError) as cm:
                            setattr(look, knob, getattr(look, knob))
                        msg = str(cm.exception)
                        self.assertTrue(msg.startswith(f"{name}.{knob} is read-only"), msg)
                        if "cannot take it either" in msg:
                            continue
                        call = re.search(r"value you want, (.*), and assign", msg).group(1)
                        built = eval(call, vars(scena))
                        self.assertIs(type(built), type(look), msg)
                        checked += 1
        self.assertGreater(checked, 20)

    def test_private_caches_still_writable(self):
        n = scena.Neon()
        n._scratch = 1
        self.assertEqual(n._scratch, 1)

    def test_fresh_tail_stays_writable(self):
        t = scena.Tail()
        self.assertIsNot(t, scena.Tail())
        t.size = 3  # not shared: no cache to poison
        self.assertEqual(t.size, 3)

    def test_recolor_by_host_still_swaps_instances(self):
        c = self.circle()
        red = scena.Neon(color="red")
        c.visual = red
        c.color = "green"  # de-seed path swaps, never mutates
        self.assertEqual(scena.Neon(color="red")._seed_color, red._seed_color)


class TestNoEntityIdKey(_Case):
    """``Entity.id`` used to be the ``obj(...)`` key. There are no ids now:
    ``id`` is ordinary ink and the roster is keyed by a private serial."""

    def test_id_is_plain_ink_and_leaves_the_roster_alone(self):
        c = self.circle()
        registry = ScenaCanvas.get_current().registry
        key = c._reg_key
        c.id = "villain"
        self.assertEqual(c.id, "villain")
        self.assertEqual(c._reg_key, key)
        self.assertTrue(registry.is_live(c))

    def test_every_registered_item_is_live_once(self):
        items = [self.circle() for i in range(4)]
        registry = ScenaCanvas.get_current().registry
        live = registry.live_objects()
        for it in items:
            self.assertEqual(live.count(it), 1)


if __name__ == "__main__":
    unittest.main()
