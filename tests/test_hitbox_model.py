"""Every hitbox is a ``Hitbox``: ``graphic.hitbox`` (main) and ``add_hitbox`` parts.

Rule under test (Sprite Design.md, "Hitboxes: one type"): the main hitbox and
the parts share one vocabulary — ``shape`` / ``source`` / ``anchor`` /
``scale`` / ``active`` / ``box``. ``Sprite(hitbox_X=)`` sets
``sprite.hitbox.X``; ``add_hitbox(X=)`` sets ``part.X``. The main hitbox
stands and is pushed by ``resolve()``; a part only detects. The old flat
names raise with the new spelling. ``hitbox.active = False`` switches the
main hitbox alone; ``collidable`` switches every hitbox.

Bug class guarded: a second spelling or a silent no-op (an old name turning
into ink), a main-only switch that leaks into parts (or the reverse), and a
measurement that disagrees with the collider the engine uses.

    python -m unittest tests.test_hitbox_model -v
"""
import unittest

from scena import Circle, Hitbox, Rect, Sheet, Sprite, Text, collide, collision, resolve
from scena.collision import STATIC, get_collision_system
from scena.scenamath import Vec2

from tests.test_sprite import SpriteTestCase, _write_padded_png

_BAR = (24, 8, 16, 48)          # 16×48 opaque bar on a 64×64 canvas


class ModelCase(SpriteTestCase):
    _origin = 0

    def setUp(self):
        super().setUp()
        ModelCase._origin += 5000
        self.o = float(ModelCase._origin)

    def at(self, x, y):
        return (self.o + x, self.o + y)

    def step(self):
        get_collision_system().step()

    def png(self, name="bar.png"):
        path = self.tmp(name)
        _write_padded_png(path, canvas_w=64, canvas_h=64, blob=_BAR)
        return path

    def sprite(self, **kw):
        kw.setdefault("center", self.at(0, 0))
        return self.track(Sprite(self.png(), width=64, height=64, **kw))


class TestOneVocabulary(ModelCase):
    def test_constructor_sets_the_main_hitbox(self):
        s = self.sprite(hitbox_shape="rect", hitbox_source=0,
                        hitbox_anchor="bottom", hitbox_scale=(0.5, 1))
        h = s.hitbox
        self.assertIsInstance(h, Hitbox)
        self.assertEqual((h.shape, h.source, h.anchor, h.scale),
                         ("rect", 0, "bottom", (0.5, 1.0)))

    def test_main_and_part_share_names_and_parsers(self):
        s = self.sprite()
        part = s.add_hitbox(group="hurt")
        for hb in (s.hitbox, part):
            with self.subTest(hb=hb):
                hb.shape = "ellipse"
                hb.anchor = "bottom"
                hb.scale = 0.5
                self.assertEqual((hb.shape, hb.anchor, hb.scale), ("ellipse", "bottom", (0.5, 0.5)))
                with self.assertRaises(ValueError):
                    hb.shape = "blob"
                with self.assertRaises(ValueError):
                    hb.scale = -1
                with self.assertRaises(ValueError):
                    hb.anchor = "middle"

    def test_hitbox_is_the_same_object_every_read(self):
        s = self.sprite()
        self.assertIs(s.hitbox, s.hitbox)

    def test_hitboxes_lists_main_first(self):
        s = self.sprite()
        a = s.add_hitbox(group="a")
        b = s.add_hitbox(group="b")
        self.assertEqual(s.hitboxes, (s.hitbox, a, b))
        s.remove_hitbox(a)
        self.assertEqual(s.hitboxes, (s.hitbox, b))


class TestOldNamesRaise(ModelCase):
    def test_sprite_keywords(self):
        for kw, new in (("hitbox", "hitbox_shape"), ("hitbox_from", "hitbox_source")):
            with self.subTest(kw=kw), self.assertRaises(TypeError) as cm:
                Sprite(self.png(), **{kw: "rect" if kw == "hitbox" else 0})
            self.assertIn(new, str(cm.exception))

    def test_class_keywords(self):
        with self.assertRaises(TypeError) as cm:
            class Nave(Sprite, hitbox="rect"):
                pass
        self.assertIn("hitbox_shape", str(cm.exception))

    def test_sprite_attributes_do_not_become_ink(self):
        s = self.sprite()
        for name, new in (("hitbox_scale", "hitbox.scale"), ("hitbox_anchor", "hitbox.anchor"),
                          ("hitbox_from", "hitbox.source"), ("hitbox_shape", "hitbox.shape"),
                          ("hitbox_source", "hitbox.source")):
            with self.subTest(name=name):
                with self.assertRaises(AttributeError) as cm:
                    setattr(s, name, 0.5)
                self.assertIn(new, str(cm.exception))
                with self.assertRaises(AttributeError):
                    getattr(s, name)
                self.assertNotIn(name, (getattr(s, "_ink", None) or {}))

    def test_hitbox_is_not_a_setting(self):
        s = self.sprite()
        with self.assertRaises(TypeError) as cm:
            s.hitbox = "rect"
        self.assertIn("hitbox.shape", str(cm.exception))

    def test_part_keywords_and_attributes(self):
        s = self.sprite()
        with self.assertRaises(TypeError) as cm:
            s.add_hitbox(hitbox_scale=0.5)
        self.assertIn("scale=", str(cm.exception))
        part = s.add_hitbox()
        for name, new in (("hitbox", "shape"), ("hitbox_from", "source"),
                          ("hitbox_anchor", "anchor"), ("hitbox_scale", "scale"),
                          ("width", "box.width"), ("height", "box.height")):
            with self.subTest(name=name):
                with self.assertRaises(AttributeError) as cm:
                    setattr(part, name, 1)
                self.assertIn(new, str(cm.exception))
                with self.assertRaises(AttributeError):
                    getattr(part, name)


class TestRoles(ModelCase):
    def test_main_hitbox_claims_no_groups(self):
        s = self.sprite()
        for call in (lambda h: h.tag("x"), lambda h: h.untag("x"),
                     lambda h: h.add_to_group("x"), lambda h: h.remove_from_group("x")):
            with self.assertRaises(TypeError) as cm:
                call(s.hitbox)
            self.assertIn("sprite.tag", str(cm.exception))

    def test_main_group_is_the_graphics_groups_minus_claims(self):
        """Read-only answer to "who answers for what": a part's claim wins."""
        s = self.sprite(group=["heroi", "dor"])
        self.assertEqual(s.hitbox.group, frozenset({"heroi", "dor"}))
        part = s.add_hitbox(group="dor")
        self.assertEqual(s.hitbox.group, frozenset({"heroi"}))
        self.assertTrue(s.hitbox.tagged("heroi"))
        self.assertFalse(s.hitbox.tagged("dor"))
        self.assertEqual(part.group, frozenset({"dor"}))
        s.tag("alvo")
        self.assertEqual(s.hitbox.group, frozenset({"heroi", "alvo"}))
        s.remove_hitbox(part)                # "dor" was the sprite's own: it stays (HP13)
        self.assertEqual(s.hitbox.group, frozenset({"heroi", "alvo", "dor"}))
        r = self.track(Rect(center=self.at(0, 0), width=4, height=4, group="bloco"))
        self.assertEqual(r.hitbox.group, frozenset({"bloco"}))

    def test_main_hitbox_takes_no_px_shape_and_is_not_removable(self):
        s = self.sprite()
        self.assertIsNone(s.hitbox.px_rect)
        with self.assertRaises(TypeError):
            s.hitbox.px_rect = (0, 0, 4, 4)
        with self.assertRaises(TypeError) as cm:
            s.remove_hitbox(s.hitbox)
        self.assertIn("active", str(cm.exception))

    def test_main_hitbox_is_not_a_collision_side(self):
        s = self.sprite(group="heroi")
        for call in (lambda: resolve(s.hitbox, "chao"),
                     lambda: collide(s.hitbox, "chao")(lambda a, b, info: None)):
            with self.assertRaises(TypeError) as cm:
                call()
            self.assertIn("not its main hitbox", str(cm.exception))


class TestMainActive(ModelCase):
    def world(self):
        floor = self.track(Rect(center=self.at(0, -10), width=300, height=20, group="chao"))
        floor.mass = STATIC
        hero = self.track(Rect(center=self.at(0, 20.5), width=20, height=40, group="heroi"))
        hero.mass = 1.0
        hero.vel = Vec2(0, 0)
        resolve("heroi", "chao", bounce=0.0)
        return floor, hero

    def fall(self, h, n=10):
        for _ in range(n):
            h.vel.y -= 15.0
            h.move_by(0, h.vel.y / 60.0)
            self.step()

    def test_off_means_no_resolve_no_touching_no_floor_no_queries(self):
        floor, hero = self.world()
        self.fall(hero)
        self.assertIn("bottom", hero.touching_sides)
        self.assertIn(hero, collision.query_point(hero.center))
        hero.hitbox.active = False
        self.assertFalse(hero.hitbox.active)
        self.fall(hero)
        self.assertEqual(hero.touching_sides, frozenset())
        self.assertLess(hero.box.bottom, self.o - 5.0, "sank into the floor: resolve skipped it")
        self.assertIsNone(hero.floor_below())
        self.assertNotIn(hero, collision.query_point(hero.center))
        self.assertIsNotNone(hero.hitbox.box, "box still measures an inactive hitbox")

    def test_off_fires_exit_and_on_resumes(self):
        a = self.track(Circle(center=self.at(0, 0), radius=10, group="a"))
        b = self.track(Circle(center=self.at(5, 0), radius=10, group="b"))
        log = []

        @collide("a", "b")
        def _hit(x, y, info):
            log.append("enter")

        from scena import collide_exit

        @collide_exit("a", "b")
        def _gone(x, y, info):
            log.append("exit")

        self.step()
        a.hitbox.active = False
        self.step()
        a.hitbox.active = True
        self.step()
        self.assertEqual(log, ["enter", "exit", "enter"])

    def test_part_keeps_detecting_while_main_is_off(self):
        s = self.sprite(group="alvo")
        s.add_hitbox(group="dor")
        bullet = self.track(Circle(center=self.at(0, 0), radius=3, group="bala"))
        hits = []

        @collide("bala", "dor")
        def _part(b, t, info):
            hits.append("part")

        @collide("bala", "alvo")
        def _main(b, t, info):
            hits.append("main")

        s.hitbox.active = False
        self.step()
        self.assertEqual(hits, ["part"])

    def test_linked_active(self):
        s = self.sprite(group="alvo")
        from scena import st
        st.fantasma = False
        s.hitbox["active"] @= lambda: not st.fantasma
        self.assertTrue(s.hitbox.active)
        st.fantasma = True
        self.assertFalse(s.hitbox.active)
        with self.assertRaises(Exception):
            s.hitbox.active = True        # linked: unlink first
        s.hitbox["active"].unlink()
        s.hitbox.active = True
        self.assertTrue(s.hitbox.active)


class TestDeadAndReadOnly(ModelCase):
    """Every write on a hitbox out of play raises DestroyedError; reads stay.

    The writable set is discovered, not listed: every property with a real
    setter (read-only ones refuse via ``_read_only``), plus the group verbs and
    the ``["active"] @=`` link — a new writer that forgets the check fails here.
    """

    WRITE_VALUES = {"shape": "rect", "source": "each", "anchor": "bottom", "scale": 0.5,
                    "active": False, "px_rect": (0, 0, 4, 4), "px_circle": (1, 1, 1)}
    READ_ONLY = ("box", "host", "is_alive", "layer", "group")

    @staticmethod
    def writable(cls):
        import inspect
        out = []
        for name in dir(cls):
            if name.startswith("_"):
                continue
            attr = inspect.getattr_static(cls, name)
            if isinstance(attr, property) and attr.fset is not None \
                    and not getattr(attr.fset, "_scena_read_only", False):
                out.append(name)
        return sorted(out)

    def test_the_writable_set_is_known(self):
        from scena.hitbox import _MainHitbox
        for cls in (Hitbox, _MainHitbox):
            self.assertEqual(set(self.writable(cls)), set(self.WRITE_VALUES), cls.__name__)

    def dead_hitboxes(self):
        s = self.sprite()
        part = s.add_hitbox(group="dor")
        removed = s.add_hitbox(group="x")
        s.remove_hitbox(removed)
        main = s.hitbox
        yield "removed part", removed, False
        s.destroy()
        yield "part of a destroyed sprite", part, False
        yield "main of a destroyed sprite", main, True

    def test_every_write_raises_destroyed_error(self):
        from scena.hitbox import _MainHitbox
        from scena.state import DestroyedError
        for label, hb, is_main in self.dead_hitboxes():
            for name in self.writable(type(hb)):
                if is_main and name.startswith("px_"):
                    continue                       # a role error on the main hitbox, dead or not
                with self.subTest(hitbox=label, field=name), self.assertRaises(DestroyedError):
                    setattr(hb, name, self.WRITE_VALUES[name])
            if not is_main:
                for verb in (lambda h: h.tag("z"), lambda h: h.untag("dor"),
                             lambda h: h.add_to_group("z"), lambda h: h.remove_from_group("dor")):
                    with self.subTest(hitbox=label, verb=verb), self.assertRaises(DestroyedError):
                        verb(hb)
            with self.subTest(hitbox=label, verb="link"), self.assertRaises(DestroyedError):
                ref = hb["active"]
                ref @= (lambda: True)

    def test_reads_keep_answering_after_death(self):
        for label, hb, is_main in self.dead_hitboxes():
            with self.subTest(hitbox=label):
                self.assertFalse(hb.is_alive)
                self.assertIsNone(hb.host)
                self.assertIn(hb.shape, ("auto", "rect"))
                self.assertEqual(hb.scale, (1.0, 1.0))

    def test_read_only_fields_speak_scena(self):
        s = self.sprite()
        part = s.add_hitbox(group="dor")
        r = self.track(Rect(center=self.at(0, 0), width=4, height=4))
        for label, hb in (("main", s.hitbox), ("part", part), ("shape main", r.hitbox)):
            for name in self.READ_ONLY:
                with self.subTest(hitbox=label, field=name):
                    with self.assertRaises(AttributeError) as cm:
                        setattr(hb, name, 1)
                    msg = str(cm.exception)
                    self.assertNotIn("has no setter", msg)
                    self.assertTrue(msg.startswith(("hb.", "g.hitbox.", "hitbox.")), msg)
        with self.assertRaises(AttributeError) as cm:
            s.hitboxes = ()
        self.assertIn("add_hitbox", str(cm.exception))


class TestShapeHitbox(ModelCase):
    def test_rect_hitbox_is_its_geometry(self):
        r = self.track(Rect(center=self.at(0, 0), width=30, height=10))
        self.assertEqual(r.hitbox.shape, "rect")
        b = r.hitbox.box
        self.assertEqual([round(v, 6) for v in (b.left, b.bottom, b.right, b.top)],
                         [self.o - 15, self.o - 5, self.o + 15, self.o + 5])
        for knob in ("scale", "anchor", "source"):
            with self.subTest(knob=knob), self.assertRaises(TypeError) as cm:
                setattr(r.hitbox, knob, 1)
            self.assertIn("own geometry", str(cm.exception))

    def test_text_has_no_hitbox(self):
        t = self.track(Text("oi"))
        with self.assertRaises(TypeError):
            t.hitbox


class TestCloneAndBox(ModelCase):
    def test_clone_copies_the_main_knobs(self):
        s = self.sprite(hitbox_shape="rect", hitbox_anchor="bottom", hitbox_scale=(0.5, 1))
        c = self.track(s.clone())
        self.assertEqual((c.hitbox.shape, c.hitbox.anchor, c.hitbox.scale),
                         ("rect", "bottom", (0.5, 1.0)))
        self.assertIsNot(c.hitbox, s.hitbox)

    def test_box_is_the_collider_the_engine_uses(self):
        """hitbox.box == union of the prims collision tests (not the drawn cell)."""
        from scena.collision import snapshot_shape
        s = self.sprite(hitbox_shape="rect")
        prims = snapshot_shape(s)
        b = s.hitbox.box
        self.assertAlmostEqual(b.left, min(p.aabb[0] for p in prims))
        self.assertAlmostEqual(b.top, max(p.aabb[3] for p in prims))
        self.assertAlmostEqual(b.width, 16.0)
        self.assertAlmostEqual(s.box.width, 64.0)
        part = s.add_hitbox(scale=0.5)
        self.assertAlmostEqual(part.box.width, 8.0)
        self.assertIsNone(getattr(s, "_collider", None), "measuring enrolled the sprite")


if __name__ == "__main__":
    unittest.main()
