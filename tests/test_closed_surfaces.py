"""Closed author surfaces: a write to a name the object does not have raises.

Rule (Scena Design, "Entity ink vs ``st``"; Testing Design, family CS): only
Entity (ink) and ``st`` create names on write. Every other author object
accepts writes only to names it already has. Before, ``bloom.itnensity = 2``,
``audio.vloume = 0`` or ``clock.puased = True`` stored a dead attribute and
nothing happened.

* ``TestClosedHelper`` — ``scena.closed`` on toy classes: sealing, messages,
  subclasses, wrapper order (the seal must fire under
  ``install_friendly_constructor``, which wraps every export after its class
  body ran).

    python -m unittest tests.test_closed_surfaces -v
"""
from __future__ import annotations

import functools
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scena.closed import (  # noqa: E402
    ClosedSurface, closed_setattr, is_sealed, make_closed_setattr, seal_after_init,
)
from scena.validate import install_friendly_constructor  # noqa: E402


class Knob(ClosedSurface):
    enabled = True          # class default: writable

    def __init__(self, intensity=1.0):
        self.intensity = intensity
        self._cache = None
        self._radius = 2.0

    @property
    def radius(self):
        return self._radius

    @radius.setter
    def radius(self, value):
        self._radius = float(value)

    @property
    def area(self):         # read-only
        return self._radius ** 2

    def remove(self):
        return "removed"


class TestClosedHelper(unittest.TestCase):
    def test_constructor_fields_then_sealed(self):
        k = Knob(2.0)
        self.assertTrue(is_sealed(k))
        self.assertEqual(k.intensity, 2.0)

    def test_junk_and_typo_raise_and_store_nothing(self):
        k = Knob()
        for name in ("itnensity", "xyz", "Radius"):
            with self.subTest(name=name):
                with self.assertRaises(AttributeError) as cm:
                    setattr(k, name, 3)
                self.assertNotIn(name, vars(k))
                self.assertIn(f"Knob has no {name!r}", str(cm.exception))
        with self.assertRaises(AttributeError) as cm:
            k.itnensity = 3
        msg = str(cm.exception)
        self.assertIn("Did you mean 'intensity'?", msg)
        self.assertIn("Writable on Knob: enabled, intensity, radius.", msg)
        self.assertNotIn("area", msg)                 # read-only: not listed
        self.assertNotIn("__init__", msg)             # a near miss is a typo: no subclass advice

    def test_known_names_still_write(self):
        k = Knob()
        k.intensity = 4.0
        k.radius = 3
        k.enabled = False
        k._anything_private = 1
        self.assertEqual((k.intensity, k.radius, k.enabled), (4.0, 3.0, False))
        self.assertTrue(Knob.enabled)                 # instance write, class untouched

    def test_read_only_property_keeps_its_own_error(self):
        with self.assertRaises(AttributeError) as cm:
            Knob().area = 1
        self.assertIn("area", str(cm.exception))
        self.assertNotIn("Writable on", str(cm.exception))

    def test_method_assignment_raises(self):
        k = Knob()
        with self.assertRaises(AttributeError) as cm:
            k.remove = None
        self.assertIn("Knob.remove is a method", str(cm.exception))
        self.assertEqual(k.remove(), "removed")

    def test_failed_constructor_does_not_seal(self):
        class Fails(ClosedSurface):
            def __init__(self):
                self.a = 1
                raise ValueError("boom")
        obj = Fails.__new__(Fails)
        with self.assertRaises(ValueError):
            obj.__init__()
        self.assertFalse(is_sealed(obj))
        self.assertNotIn("_init_depth", vars(obj))

    def test_custom_who_and_hint(self):
        class Bus(ClosedSurface):
            _closed_who = "audio"

            def __init__(self):
                self.volume = 1.0

            def _closed_hint(self, name):
                if name == "pan":
                    return "audio.pan lives on each Sound: sound.pan = ..."
                return None
        bus = Bus()
        with self.assertRaises(AttributeError) as cm:
            bus.vloume = 0
        self.assertIn("audio has no 'vloume'. Did you mean 'volume'?", str(cm.exception))
        with self.assertRaises(AttributeError) as cm:
            bus.pan = 0
        self.assertEqual(str(cm.exception), "audio.pan lives on each Sound: sound.pan = ...")

    def test_long_writable_list_is_capped(self):
        class Wide(ClosedSurface):
            def __init__(self):
                for i in range(30):
                    setattr(self, f"knob{i:02d}", i)
        with self.assertRaises(AttributeError) as cm:
            Wide().zz = 1
        self.assertIn("knob19, …", str(cm.exception))
        self.assertNotIn("knob20", str(cm.exception))


class TestClosedSubclasses(unittest.TestCase):
    def test_author_subclass_fields_in_init_after_super(self):
        class Footprints(Knob):
            def __init__(self):
                super().__init__(0.5)
                self.steps = []          # after super(): still constructing
        f = Footprints()
        self.assertTrue(is_sealed(f))
        f.steps = [1]
        with self.assertRaises(AttributeError) as cm:
            f.colour = "red"
        msg = str(cm.exception)
        self.assertIn("Footprints has no 'colour'", msg)
        self.assertIn("steps", msg)
        self.assertIn("create it in __init__", msg)

    def test_inherited_init_subclass_is_sealed(self):
        class Plain(Knob):
            pass
        p = Plain()
        self.assertTrue(is_sealed(p))
        with self.assertRaises(AttributeError):
            p.junk = 1

    def test_seal_survives_friendly_constructor_wrapper(self):
        # scena/__init__.py wraps every export's own __init__ after the class
        # body: the seal must not depend on being the outermost wrapper.
        class Exported(ClosedSurface):
            def __init__(self, level=1):
                self.level = level
        install_friendly_constructor(Exported)
        e = Exported(level=2)
        self.assertTrue(is_sealed(e))
        with self.assertRaises(AttributeError):
            e.lvel = 3
        with self.assertRaises(TypeError) as cm:     # the friendly rewrite still works
            Exported(levle=2)
        self.assertIn("Did you mean 'level'", str(cm.exception))

    def test_seal_survives_any_outer_wrapper(self):
        class Wrapped(ClosedSurface):
            def __init__(self):
                self.a = 1
        inner = Wrapped.__init__

        @functools.wraps(inner)
        def outer(self, *args, **kwargs):
            inner(self, *args, **kwargs)
        Wrapped.__init__ = outer
        w = Wrapped()
        self.assertTrue(is_sealed(w))
        with self.assertRaises(AttributeError):
            w.b = 2

    def test_nested_construction_of_another_instance(self):
        class Node(ClosedSurface):
            def __init__(self, depth=0):
                self.child = Node(depth + 1) if depth < 2 else None
                self.depth = depth
        n = Node()
        self.assertTrue(is_sealed(n) and is_sealed(n.child) and is_sealed(n.child.child))
        self.assertEqual(n.depth, 0)

    def test_seal_after_init_is_idempotent(self):
        class Twice(ClosedSurface):
            def __init__(self):
                self.a = 1
        before = Twice.__init__
        seal_after_init(Twice)
        self.assertIs(Twice.__init__, before)


class TestFastSetattr(unittest.TestCase):
    def test_fast_names_and_guard(self):
        class Cell:
            __setattr__ = make_closed_setattr(("value",))

            def __init__(self):
                self.value = 0
        seal_after_init(Cell)
        c = Cell()
        c.value = 5
        self.assertEqual(c.value, 5)
        with self.assertRaises(AttributeError):
            c.valeu = 6

    def test_plain_closed_setattr_without_mixin(self):
        class Bare:
            __setattr__ = closed_setattr

            def __init__(self):
                self.x = 1
        seal_after_init(Bare)
        b = Bare()
        b.x = 2
        with self.assertRaises(AttributeError):
            b.y = 3


class TestEngineValueRegressions(unittest.TestCase):
    """Targeted regressions on engine objects (needs the engine booted)."""

    @classmethod
    def setUpClass(cls):
        from hypothesis_support import boot
        boot()

    def test_cell_payload_write_raises_with_the_reactive_fix(self):
        from scena import st, Vec2
        st.cs_pos = Vec2(1, 2)
        with self.assertRaises(AttributeError) as cm:
            st.cs_pos.x = 5
        msg = str(cm.exception)
        self.assertIn("st.cs_pos holds a Vec2", msg)
        self.assertIn("st.cs_pos = Vec2(..., st.cs_pos.y)", msg)
        self.assertEqual((st.cs_pos.value.x, st.cs_pos.value.y), (1.0, 2.0))
        self.assertNotIn("x", vars(st.cs_pos))
        st.cs_pos = Vec2(5, st.cs_pos.y)            # the reactive spelling
        self.assertEqual(st.cs_pos.x, 5.0)

    def test_cell_value_write_stays_open(self):
        from scena import st
        st.cs_hp = 3
        st.cs_hp = 4
        cell = st.cs_hp
        cell.value = 5
        self.assertEqual(st.cs_hp.value, 5)
        with self.assertRaises(AttributeError):
            cell.valeu = 6

    def test_snapshot_boxes_are_sealed(self):
        # Box._snapshot builds through __new__ (graphic.box, canvas.game_view).
        import scena
        c = scena.Circle(center=(0, 0), radius=5)
        try:
            for box in (c.box, scena.canvas.game_view):
                with self.subTest(box=box):
                    self.assertTrue(is_sealed(box))
                    with self.assertRaises(AttributeError) as cm:
                        box.widht = 3
                    self.assertIn("Did you mean 'width'?", str(cm.exception))
            with self.assertRaises(AttributeError) as cm:
                scena.canvas.game_view.topp = 1          # read-only names are suggested too
            self.assertIn("Did you mean 'top'?", str(cm.exception))
        finally:
            c.destroy()

    def test_history_subclass_keeps_its_own_fields(self):
        import scena

        class Footprints(scena.History):
            def __init__(self):
                super().__init__()
                self.steps = []

        f = Footprints()
        f.steps = [1]
        f.duration = 2.0
        with self.assertRaises(AttributeError) as cm:
            f.colour = "red"
        self.assertIn("create it in __init__", str(cm.exception))

    def test_collision_info_and_parts_are_slotted(self):
        import scena
        from scena import Vec2
        from scena.collision import CollisionInfo
        c = scena.Circle(center=(0, 0), radius=5)
        try:
            info = CollisionInfo(c, c, Vec2(1, 0), 1.0)
            with self.assertRaises(AttributeError):
                info.nromal = 1
            info.depth = 2.0
            with self.assertRaises(AttributeError):
                c.parts.junk = 1
        finally:
            c.destroy()


class TestContainerPlumbing(unittest.TestCase):
    """``parts`` / ``field_type`` were plain public attributes: a write
    silently corrupted the part tree (``ship.field_type = 3``)."""

    @classmethod
    def setUpClass(cls):
        from hypothesis_support import boot
        boot()

    def test_field_type_and_parts_are_read_only_everywhere(self):
        import scena
        from scena import Vec2
        from scena.state import FieldType
        c = scena.Circle(center=(0, 0), radius=5)
        try:
            for obj in (c, Vec2(1, 2), scena.canvas.game_view, scena.clock):
                with self.subTest(obj=type(obj).__name__):
                    before = obj.field_type
                    with self.assertRaises(AttributeError) as cm:
                        obj.field_type = 3
                    self.assertIn("field_type is read-only", str(cm.exception))
                    self.assertIs(obj.field_type, before)
                    parts = obj.parts
                    with self.assertRaises(TypeError) as cm:
                        obj.parts = []
                    self.assertIn("self.pieces = [...]", str(cm.exception))
                    self.assertIs(obj.parts, parts)
            self.assertIs(c.center.field_type, FieldType.Defining)
            self.assertIn(c.center, list(c.parts))
        finally:
            c.destroy()


class TestContainerFastInit(unittest.TestCase):
    """``Container.__init__`` writes its private fields through ``__dict__``
    only where that equals a normal write (``state._container_dict_init``)."""

    @classmethod
    def setUpClass(cls):
        from hypothesis_support import boot
        boot()

    def test_which_classes_take_the_dict_path(self):
        import scena
        from scena.box import Box
        from scena.state import Attribute, _container_dict_init
        self.assertTrue(_container_dict_init(Box))
        self.assertTrue(_container_dict_init(Attribute))
        self.assertTrue(_container_dict_init(scena.Entity))
        self.assertTrue(_container_dict_init(scena.Vec2))
        # Shape slots _in_batch_update: a dict write would hide behind the slot.
        self.assertFalse(_container_dict_init(scena.Circle))

    def test_no_python_setattr_means_plain_writes(self):
        from scena.state import Container, _container_dict_init

        class Open(Container):
            pass
        self.assertFalse(_container_dict_init(Open))

    def test_an_owner_or_refresh_name_override_keeps_the_normal_path(self):
        # The dict path skips the owner setter for an ownerless object; a
        # class that changes what that setter does must run it.
        from scena.closed import ClosedSurface
        from scena.state import Container, _container_dict_init

        class OwnRefresh(ClosedSurface, Container):
            def _refresh_name(self):
                super()._refresh_name()

        class OwnOwner(ClosedSurface, Container):
            owner = property(Container.owner.fget, Container.owner.fset)

        self.assertFalse(_container_dict_init(OwnRefresh))
        self.assertFalse(_container_dict_init(OwnOwner))

    def test_a_setattr_that_sees_private_names_keeps_the_normal_path(self):
        from scena.state import Container, _container_dict_init
        seen = []

        class Watcher(Container):
            def __setattr__(self, name, value):
                seen.append(name)
                object.__setattr__(self, name, value)

        self.assertFalse(_container_dict_init(Watcher))
        Watcher()
        self.assertIn("_dirty", seen)

    def test_both_paths_leave_the_same_fields(self):
        import scena
        from scena.state import _CONTAINER_INIT_FIELDS, FieldType
        fast = scena.Box(center=(0, 0), width=4, height=2)
        slow = scena.Circle(center=(0, 0), radius=5)
        try:
            for obj in (fast, slow, scena.Vec2(1, 2)):
                with self.subTest(cls=type(obj).__name__):
                    for name in _CONTAINER_INIT_FIELDS:
                        self.assertTrue(hasattr(obj, name), name)   # Shape slots one
                    self.assertIs(obj._field_type, FieldType.Defining)
                    self.assertFalse(obj._dirty)
        finally:
            slow.destroy()

    def test_ownerless_skip_leaves_what_the_owner_setter_left(self):
        # The dict path skips ``self.owner = None`` on an ownerless object:
        # owner, name and ownership root must match the setter's result.
        import scena
        from scena.state import Container
        for v in (scena.Vec2(1, 2), scena.Vec2.temp(1, 2), scena.Vec2(attr_name="aim")):
            with self.subTest(name=v._attr_name):
                self.assertIsNone(v.owner)
                self.assertEqual(v.name, v._attr_name)
                self.assertEqual(list(v._iter_subtree()), [v])
                Container.owner.fset(v, None)          # what the setter would do
                self.assertIsNone(v.owner)
                self.assertEqual(v.name, v._attr_name)

    def test_an_owned_value_still_runs_the_owner_setter(self):
        import scena
        holder = scena.Vec2(0, 0, attr_name="holder")
        part = scena.Vec2(1, 2, owner=holder, attr_name="tip")
        self.assertIs(part.owner, holder)
        self.assertIn(part, list(holder.parts))
        self.assertEqual(part.name, "holder.tip")


class TestClosedVec2(unittest.TestCase):
    """Vec2 was left open for speed (a Python ``__setattr__`` on each of its
    18 construction writes cost ~60% on arithmetic). Its construction now
    makes no ``__setattr__`` call, so it is closed at no arithmetic cost."""

    @classmethod
    def setUpClass(cls):
        from hypothesis_support import boot
        boot()

    def test_typo_raises_and_names_the_axis(self):
        import scena
        v = scena.Vec2(3, 4)
        for typo, real in (("lenght", "length"), ("agnle", "angle")):
            with self.subTest(typo=typo):
                with self.assertRaises(AttributeError) as cm:
                    setattr(v, typo, 1)
                self.assertIn(f"Did you mean {real!r}?", str(cm.exception))
                self.assertNotIn(typo, vars(v))
        with self.assertRaises(AttributeError) as cm:
            v.z = 1
        # length / angle are computed: offered as a did-you-mean (their own
        # error then speaks), not listed as writable.
        self.assertIn("Writable on Vec2: x, y.", str(cm.exception))
        v.x = 6
        v.y = 8
        self.assertEqual((v.x, v.y, v.length), (6, 8, 10))

    def test_every_way_to_build_one_is_sealed(self):
        import scena
        a, b = scena.Vec2(1, 2), scena.Vec2.temp(3, 4)
        made = {
            "Vec2(x, y)": a, "Vec2()": scena.Vec2(), "Vec2((x, y))": scena.Vec2((1, 2)),
            "Vec2(lambda)": scena.Vec2(lambda: (a.x, a.y)), "temp": b,
            "a + b": a + b, "a - b": a - b, "a * 2": a * 2, "-a": -a,
            "normalize": a.normalize(), "rotate": a.rotate(30),
        }
        for label, v in made.items():
            with self.subTest(made=label):
                self.assertTrue(is_sealed(v))
                with self.assertRaises(AttributeError):
                    v.junk = 1
                self.assertNotIn("_processed_params", vars(v))

    def test_construction_makes_no_setattr_call(self):
        # The bug class behind the old exemption (Testing Design CS8): any
        # write that goes back through __setattr__ on the construction path
        # costs ~100 ns per Vec2, i.e. per arithmetic result.
        import scena
        Vec2 = scena.Vec2
        cls_setattr = Vec2.__dict__["__setattr__"]
        seen = []

        def spy(self, name, value):
            seen.append(name)
            cls_setattr(self, name, value)
        spy._scena_private_passthrough = True
        a, b = Vec2.temp(1, 2), Vec2.temp(3, 4)
        Vec2.__setattr__ = spy
        try:
            for build in (lambda: Vec2.temp(1, 2), lambda: Vec2(1, 2),
                          lambda: a + b, lambda: a * 2):
                build()
        finally:
            Vec2.__setattr__ = cls_setattr
        self.assertEqual(seen, [])

    def test_author_subclass_creates_fields_in_init(self):
        import scena

        class Heading(scena.Vec2):
            def __init__(self, x, y, *, label):
                self.label = label            # before super(): still constructing
                super().__init__(x, y)
                self.seen = 0                 # after super(): still constructing

        h = Heading(1, 2, label="north")
        self.assertTrue(is_sealed(h))
        h.seen = 3
        self.assertEqual((h.x, h.y, h.label, h.seen), (1, 2, "north", 3))
        with self.assertRaises(AttributeError) as cm:
            h.colour = "red"
        self.assertIn("create it in __init__", str(cm.exception))

    def test_author_subclass_without_init_is_sealed(self):
        import scena

        class Plain(scena.Vec2):
            pass

        p = Plain(1, 2)
        self.assertTrue(is_sealed(p))
        with self.assertRaises(AttributeError):
            p.junk = 1


class TestInkTranspositionGuard(unittest.TestCase):
    """A 5-letter property one adjacent swap away (``anlge``) used to become
    ink: the old rule needed 6+ letters and the same first letter."""

    @classmethod
    def setUpClass(cls):
        from hypothesis_support import boot
        boot()

    def test_swapped_letters_raise_and_name_the_property(self):
        import scena
        r = scena.Rect(center=(0, 0), width=10, height=5)
        try:
            for typo, real in (("anlge", "angle"), ("widht", "width"), ("aplha", "alpha"),
                               ("lyaer", "layer"), ("gruop", "group"), ("nagle", "angle")):
                with self.subTest(typo=typo):
                    with self.assertRaises(AttributeError) as cm:
                        setattr(r, typo, 1)
                    self.assertIn(f"Did you mean {real!r}?", str(cm.exception))
                    self.assertNotIn(typo, vars(r))
        finally:
            r.destroy()

    def test_deletions_and_free_names_stay_ink(self):
        import scena
        r = scena.Rect(center=(0, 0), width=10, height=5)
        try:
            for name in ("coor", "laer", "score", "lives"):
                with self.subTest(name=name):
                    setattr(r, name, 3)
                    self.assertEqual(getattr(r, name), 3)
        finally:
            r.destroy()

    def test_transposed_helper(self):
        from scena.entity import _one_edit_apart, _transposed
        self.assertTrue(_transposed("anlge", "angle"))
        self.assertTrue(_transposed("nagle", "angle"))
        self.assertFalse(_transposed("angle", "angle"))
        self.assertTrue(_transposed("agnle", "angle"))
        self.assertFalse(_transposed("enlga", "angle"))      # swap, but not adjacent
        self.assertFalse(_transposed("ange", "angle"))
        self.assertTrue(_one_edit_apart("rotaton", "rotation"))
        self.assertTrue(_one_edit_apart("roation", "rotation"))


# ---------------------------------------------------------------------------
# The bug-class guard: every author object, exported or reachable
# ---------------------------------------------------------------------------

# Open on purpose (class name -> reason). A new class must choose a side:
# close it (scena.closed) or add it here with the reason.
EXEMPT = {
    "State": "st: a write creates a cell (the app bag)",
    "Visual": "abstract base, never constructed bare (no __init__ to seal); "
              "every subclass is sealed",
    "ColorNames": "static namespace class, never instantiated",
}
# Entities (ink) are open by design: Entity and every subclass.

JUNK = "zz_not_a_name"


def _swap(name: str) -> str:
    """``name`` with two adjacent letters swapped (first pair that differs)."""
    for i in range(len(name) - 1):
        if name[i] != name[i + 1] and name[i].isalpha() and name[i + 1].isalpha():
            return name[:i] + name[i + 1] + name[i] + name[i + 2:]
    return name


def _author_objects():
    """(label, object) for every export, global object and reachable attribute."""
    import enum
    import io
    import contextlib
    import inspect
    import scena
    from scena.entity import Entity
    from scena.collision import CollisionInfo, collision
    from surface_support import EXCLUDED, constructor_names, family_of, make_instance

    roots, made = [], []
    sink = io.StringIO()
    for name in constructor_names():
        try:
            with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                obj = make_instance(name)
        except TypeError:
            continue          # needs arguments; reached below or as an attribute
        roots.append((f"{name}()", obj))
        made.append(obj)
    wav = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "examples", "media", "audio", "explosion01.wav")
    sound = scena.Sound(wav)
    roots.append(("Sound(file)", sound))
    roots.append(("play_sound()", scena.play_sound(sound)))   # .effects: AudioEffectStack
    a = scena.Circle(center=(0, 0), radius=5)
    b = scena.Rect(center=(1, 0), width=5, height=5)
    made += [a, b]
    roots += [
        ("Collider", scena.Collider([a, b])),
        ("CollisionInfo", CollisionInfo(a, b, scena.Vec2(1, 0), 1.0)),
        ("after()", scena.after(10, lambda: None)),
        ("canvas", scena.canvas), ("ui", scena.ui), ("clock", scena.clock),
        ("audio", scena.audio), ("collision", collision), ("mouse", scena.mouse),
        ("keyp", scena.keyp), ("ready", scena.ready), ("recently", scena.recently),
        ("canvas.playfield", scena.canvas.playfield),
        ("canvas.background", scena.canvas.background),
        ("canvas.effects", scena.canvas.effects),
        ("canvas.game_view", scena.canvas.game_view),
        ("circle.box", a.box),
    ]
    made.append(scena.Circle(center=(0, 0), radius=2, layer=7))
    scena.canvas.layers.create("cs_named")
    for key in ("cs_named", "default", "top", "ui", 7):
        roots.append((f"canvas.layers[{key!r}]", scena.canvas.layers[key]))

    seen, out = set(), []

    def visit(obj, label, depth):
        cls = type(obj)
        if isinstance(obj, type) or not (cls.__module__ or "").startswith("scena"):
            return
        if isinstance(obj, (enum.Enum, BaseException)):
            return
        if cls not in seen and not isinstance(obj, Entity):
            seen.add(cls)
            out.append((label, obj))
        if depth == 0:
            return
        names = {n for n in dir(cls) if not n.startswith("_")}
        names |= {n for n in getattr(obj, "__dict__", {}) if isinstance(n, str) and not n.startswith("_")}
        for n in sorted(names):
            try:
                static = inspect.getattr_static(obj, n)
            except AttributeError:
                continue
            if inspect.isfunction(static) or isinstance(static, (staticmethod, classmethod)):
                continue
            try:
                with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                    value = getattr(obj, n)
            except Exception:
                continue
            if isinstance(value, (list, tuple)) and value:
                value = value[0]
            if callable(value) and not hasattr(value, "__dict__"):
                continue
            visit(value, f"{label}.{n}", depth - 1)

    for label, obj in roots:
        visit(obj, label, 2)
    return out, made


class TestEveryAuthorObjectIsClosed(unittest.TestCase):
    """Bug class CS: a non-Entity author object stored a write to a name it
    does not have (``bloom.itnensity = 2``, ``clock.puased = True``)."""

    @classmethod
    def setUpClass(cls):
        import warnings
        from hypothesis_support import boot
        boot()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            cls.objects, cls.made = _author_objects()

    @classmethod
    def tearDownClass(cls):
        from surface_support import remove, settle
        for obj in cls.made:
            remove(obj)
        settle()

    def _checked(self):
        for label, obj in self.objects:
            if type(obj).__name__ in EXEMPT:
                continue
            yield label, obj

    def test_walk_reaches_every_family(self):
        names = {type(o).__name__ for _l, o in self.objects}
        for expected in ("Bloom", "Stars", "Echo", "PostFxStack", "AudioEffectStack",
                         "BackgroundStack", "Canvas", "Clock", "Box", "Color", "History",
                         "Sound", "CollisionInfo", "Layer", "ContainerSet", "Attribute"):
            self.assertIn(expected, names)
        self.assertGreater(len(self.objects), 100)

    def test_junk_name_raises_and_stores_nothing(self):
        silent = []
        for label, obj in self._checked():
            try:
                setattr(obj, JUNK, 1)
            except AttributeError:
                continue
            except Exception as exc:       # noqa: BLE001 - report, do not hide
                silent.append(f"{label} ({type(obj).__name__}): {type(exc).__name__}")
                continue
            vars(obj).pop(JUNK, None)
            silent.append(f"{label} ({type(obj).__name__})")
        self.assertEqual(
            silent, [],
            "These objects accept a write to a name they do not have. Close the "
            "class (scena.closed.ClosedSurface) or add it to EXEMPT with the reason.")

    def test_exported_closed_classes_are_sealed(self):
        # Regression: install_friendly_constructor wraps every export's __init__
        # after its class body; a seal keyed on __init__ identity never fired.
        from scena.closed import ClosedSurface, is_sealed
        for label, obj in self._checked():
            if isinstance(obj, ClosedSurface):
                with self.subTest(label=label):
                    self.assertTrue(is_sealed(obj))

    def _writable(self, obj):
        from scena.closed import class_names
        cls = type(obj)
        hidden = set()
        for klass in cls.__mro__:
            hidden.update(vars(klass).get("_closed_hidden", ()))
        own = {n for n, v in vars(obj).items()
               if isinstance(n, str) and not n.startswith("_") and not callable(v)
               and n not in hidden}
        return sorted(class_names(cls)[1] | own), class_names(cls)[0] | own

    def _helper_objects(self):
        from scena.closed import is_sealed
        for label, obj in self._checked():
            if is_sealed(obj):
                yield label, obj

    def test_swapped_letter_typo_names_the_real_name(self):
        misses = []
        for label, obj in self._helper_objects():
            writable, accepted = self._writable(obj)
            for real in writable:
                typo = _swap(real)
                if typo == real or typo in accepted or len(real) < 4:
                    continue
                try:
                    setattr(obj, typo, None)
                except AttributeError as exc:
                    if f"Did you mean {real!r}?" not in str(exc):
                        misses.append(f"{label}.{typo}: {exc}")
                else:
                    vars(obj).pop(typo, None)
                    misses.append(f"{label}.{typo}: stored")
        self.assertEqual(misses, [])

    def test_every_writable_name_writes_back(self):
        from surface_support import global_restore, global_snapshot
        false_positives = []
        snap = global_snapshot()
        try:
            for label, obj in self._helper_objects():
                writable, _accepted = self._writable(obj)
                for name in writable:
                    try:
                        value = getattr(obj, name)
                    except Exception:      # noqa: BLE001 - write-only or lazy
                        continue
                    try:
                        setattr(obj, name, value)
                    except AttributeError as exc:
                        if "has no " in str(exc):
                            false_positives.append(f"{label}.{name}: {exc}")
                    except Exception:      # noqa: BLE001 - the setter's own check
                        pass
        finally:
            global_restore(snap)
        self.assertEqual(false_positives, [])

    def test_unconstructible_closed_classes(self):
        # Microphone opens the OS input device (surface_support.EXCLUDED).
        from scena.audio_capture import Microphone
        from scena.closed import ClosedSurface
        self.assertTrue(issubclass(Microphone, ClosedSurface))


if __name__ == "__main__":
    unittest.main()
