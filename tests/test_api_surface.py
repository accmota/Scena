"""Public names on author objects must be documented or explicitly allowed.

A new engine helper without a leading underscore fails this module. Names
the Guia already spells are allowed automatically. The explicit set is the
rest of today's surface.

Three walks over ``scena.__all__`` (not a hand-picked list of objects):

* every exported **class** — members found by ``dir(cls)``;
* every constructible class as an **instance** — attributes set in
  ``__init__`` (``Metal.seed_color`` was one) that ``dir(cls)`` misses;
* every exported **object** (``canvas``, ``ui``, ``group``, …);
* every **reachable** object (``canvas.layers["far"]``, ``canvas.effects``,
  a Handle, ``shape.group``) — ``_reachable_objects``;
* look / post / background / audio-fx / filter classes against their **own**
  family's Guia sections (owner-aware), and every surface against
  ``TestEngineHooksAreUnderscored.HOOK_WORDS`` (engine vocabulary).

Members a class inherits from a builtin (``BaseException.add_note``,
``with_traceback``) are Python's, not Scena's, and are skipped.

``draw``, ``undraw``, ``update``, ``owner``, and ``parts`` stay public on
purpose: renaming them collides with the draw walk and Container ownership.
"""
from __future__ import annotations

import builtins
import inspect
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

import scena
from tests import repo_layout as layout  # noqa: E402
from scena import init, Circle, Rect, Polygon, Vec2, Color, Point, Sprite

# Kept public. Do not underscore these.
KEPT_PUBLIC = frozenset({"draw", "undraw", "update", "owner", "parts"})

# Public today, not spelled in the Guia. Adding a name here is a decision;
# a name that appears in neither the Guia nor this set fails the test.
SURFACE_NOT_IN_GUIA = frozenset({
    "GUIDE_ALPHA", "GUIDE_COLOR", "GUIDE_RADIUS",
    "HANDLE_ALPHA", "HANDLE_COLOR", "HANDLE_HOVER_RADIUS", "HANDLE_RADIUS",
    "abs_angle_to", "accent_color", "attr_name", "clamp_length_to", "color4f",
    "contrast_tone", "do_rotation", "field_type", "from_square",
    "get_defaults", "is_none", "model", "monochromatic",
    "no_drag", "no_drop", "no_points", "no_wheel_rotate", "reject",
    "reject_from", "shield_scale", "split_complementary",
    "tangent_line_from_angle", "tetradic", "to_array",
    "BTN_1", "BTN_2", "BTN_3", "BTN_4", "BTN_5", "BTN_6", "BTN_7", "BTN_8",
    # Clock.advance: tests step the clock with it.
    "advance",
    # canvas diagnostics: bench / profiling knobs. canvas.fx_quality is the
    # taught preset; these tune one axis of it or read the RT pool.
    "batch_shared_filters", "post_fx_scale", "shape_fx_scale",
    "shape_fx_surface_stats", "reset_shape_fx_surface_stats",
    # canvas camera rest look (zero offset for parallax), read-only.
    "pan_rest_x", "pan_rest_y",
})


def _guia_words() -> set[str]:
    chunks = []
    for path in (layout.GUIDE_HTML, layout.GUIDE_CATALOGS):
        with open(path, encoding="utf-8") as f:
            chunks.append(f.read())
    return set(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", "\n".join(chunks)))


def _public(obj) -> set[str]:
    return {n for n in dir(obj) if not n.startswith("_")}


def _scena_members(cls: type) -> set[str]:
    """Public names of ``cls`` minus those a builtin base defines."""
    out = set()
    for name in _public(cls):
        owner = next((k for k in cls.__mro__ if name in vars(k)), None)
        if owner is not None and owner.__module__ == builtins.__name__:
            continue
        if owner is not None and type(vars(owner)[name]).__name__ == "_RetiredKnob":
            continue        # a retired name that only raises with its new spelling
        out.add(name)
    return out


def _exports():
    """``(classes, objects)`` of ``scena.__all__``. Functions and plain
    constants have no members to check."""
    classes, objects = {}, {}
    for name in scena.__all__:
        obj = getattr(scena, name)
        if inspect.isclass(obj):
            classes[name] = obj
        elif not inspect.isroutine(obj) and not isinstance(obj, (str, int, float)):
            objects[name] = obj
    return classes, objects


# Objects an author reaches through an exported one (``canvas.layers["far"]``,
# ``canvas.effects``, the Handle ``after`` returns): not in ``scena.__all__``, so
# the class / object walks never saw them — Layer once exposed nine registry
# hooks (``append_object``, ``tombstone_object``, ``objects`` …) this way.
REACHABLE_ALLOW = frozenset({
    # GroupTags (``shape.group``) refuses every set mutator with the synced
    # spelling; frozenset has no *_update methods, so these are Scena's own.
    "difference_update", "intersection_update", "symmetric_difference_update",
})


def _reachable_objects() -> dict:
    from scena import after, group
    circle = Circle(center=(0, 0), radius=5, group="probe")
    handle = after(60.0, lambda: None)
    objs = {
        "canvas.layers": scena.canvas.layers,
        'canvas.layers["default"]': scena.canvas.layers["default"],
        "canvas.effects": scena.canvas.effects,
        "canvas.background": scena.canvas.background,
        "canvas.playfield": scena.canvas.playfield,
        "canvas.fx_quality": scena.canvas.fx_quality,
        "after(...)": handle,
        'group["probe"]': group["probe"],
        "shape.group": circle.group,
        "collision": scena.collision,
    }
    handle.cancel()
    circle.destroy()
    return objs


class TestAuthorSurface(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init(width=400, height=300)
        cls.allow = _guia_words() | KEPT_PUBLIC | SURFACE_NOT_IN_GUIA
        cls.objs = {
            "Circle": Circle(center=(0, 0), radius=10),
            "Rect": Rect(center=(0, 0), width=10, height=10),
            "Polygon": Polygon(points=[(0, 0), (10, 0), (0, 10)]),
            "Vec2": Vec2(1, 2),
            "Color": Color("red"),
            "Point": Point(0, 0),
            "Sprite": Sprite("player.png", center=(0, 0)),
            "mouse": scena.mouse,
            "keyp": scena.keyp,
            "clock": scena.clock,
        }

    def _extra(self, names):
        return sorted(n for n in names if n not in self.allow)

    def test_author_objects_expose_only_documented_members(self):
        for label, obj in self.objs.items():
            self.assertEqual(self._extra(_public(obj)), [], label)

    def test_every_exported_class_exposes_only_documented_members(self):
        classes, _ = _exports()
        self.assertGreater(len(classes), 100)
        bad = {name: extra for name, cls in classes.items()
               if (extra := self._extra(_scena_members(cls)))}
        self.assertEqual(bad, {}, "underscore engine hooks, or document / allowlist author API")

    def test_every_exported_object_exposes_only_documented_members(self):
        _, objects = _exports()
        for required in ("canvas", "ui", "group", "mouse", "clock"):
            self.assertIn(required, objects)
        bad = {name: extra for name, obj in objects.items()
               if (extra := self._extra(_public(obj)))}
        self.assertEqual(bad, {})

    def test_every_constructible_instance_exposes_only_documented_members(self):
        # Attributes assigned in __init__ are invisible to dir(cls).
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import surface_support as ss
        bad, built = {}, 0
        for name in ss.constructor_names():
            if name in ss.ENGINE_BUILT:
                continue
            try:
                with ss.quiet():
                    obj = ss.make_instance(name)
            except Exception:  # noqa: BLE001 — needs arguments; class walk covers it
                continue
            built += 1
            try:
                extra = self._extra(_public(obj) - _public(type(obj)))
                if extra:
                    bad[name] = extra
            finally:
                ss.remove(obj)
        self.assertGreater(built, 100)
        self.assertEqual(bad, {})

    def test_every_reachable_object_exposes_only_documented_members(self):
        bad = {}
        for label, obj in _reachable_objects().items():
            names = {n for n in _public(obj)
                     if next((k for k in type(obj).__mro__ if n in vars(k)), type(obj)).__module__
                     != builtins.__name__}
            extra = sorted(n for n in names if n not in self.allow | REACHABLE_ALLOW)
            if extra:
                bad[label] = extra
        self.assertEqual(bad, {}, "underscore engine members, or document / allowlist author API")

    def test_family_members_are_documented_in_their_family(self):
        # Owner-aware: a look / post effect / background field / audio effect /
        # filter member must appear in that family's Guia sections or catalog
        # cards — not merely somewhere in the Guia (``render`` passed the word
        # bag via an unrelated Svg example).
        import html as _html
        sys.path.insert(0, layout.GUIDE_TOOLS)
        import validate_guia as v  # type: ignore
        from scena.visuals import Visual
        from scena.postfx import PostEffect
        from scena.background import BackgroundField
        from scena.audio_effects import AudioEffect
        from scena.filters import FilterEffect
        src = v.HTML.read_text(encoding="utf-8")
        with open(layout.GUIDE_CATALOGS, encoding="utf-8") as f:
            catalogs = f.read()

        def words(text):
            return set(re.findall(r"\b[A-Za-z_]\w*\b", _html.unescape(re.sub(r"<[^>]+>", " ", text))))

        families = {
            Visual: ("aparencia-visual", "aparencia-selos", "aparencia-cor", "aparencia-blend"),
            PostEffect: ("mundo-post",),
            BackgroundField: ("mundo-background", "mundo-camadas"),
            AudioEffect: ("som-fx",),
            FilterEffect: ("aparencia-filtros",),
        }
        catalog_words = words(catalogs)
        classes, _ = _exports()
        bad = {}
        for base, sections in families.items():
            documented = catalog_words.union(*(words(v._element_by_id(src, s)) for s in sections))
            for name, cls in classes.items():
                if not issubclass(cls, base):
                    continue
                extra = sorted(_scena_members(cls) - KEPT_PUBLIC - SURFACE_NOT_IN_GUIA - documented)
                if extra:
                    bad[name] = extra
        self.assertEqual(bad, {})

    def test_allowlist_names_exist_on_the_surface(self):
        # A stale entry would silently re-open the name for an engine hook.
        classes, objects = _exports()
        seen = set()
        for cls in classes.values():
            seen |= _scena_members(cls)
        for obj in list(objects.values()) + list(self.objs.values()):
            seen |= _public(obj)
        self.assertEqual(sorted(SURFACE_NOT_IN_GUIA - seen), [])

    def test_builtin_members_are_skipped_not_allowed(self):
        # add_note / with_traceback come from BaseException: skipped by
        # owner, never listed as Scena surface.
        classes, _ = _exports()
        errors = [c for c in classes.values() if issubclass(c, BaseException)]
        self.assertTrue(errors)
        for cls in errors:
            self.assertFalse({"add_note", "with_traceback"} & _scena_members(cls), cls)
        self.assertFalse({"add_note", "with_traceback"} & SURFACE_NOT_IN_GUIA)

    def test_kept_public_names_stay_on_the_objects(self):
        circle = self.objs["Circle"]
        for name in KEPT_PUBLIC:
            self.assertTrue(hasattr(circle, name), name)


class TestEngineHooksAreUnderscored(unittest.TestCase):
    """Representatives of the hook families renamed in the surface sweep.

    A public spelling coming back (``look.apply``) would pass the Guia-word
    walk if the word ever reached the Guia for another reason; these pin the
    families by name.
    """

    HOOKS = {
        "Glow": ("apply", "batch_key", "color_role", "is_multipass", "allows_sprite"),
        "Metal": ("primary_tint", "identity_patch"),
        "Shield": ("primary_tint", "styles"),
        "Blur": ("batch_outset", "filter_at_scale"),
        "Vignette": ("cache_key", "is_active", "quality_sensitive", "draw_overlay"),
        "Stars": ("advance_scroll", "apply_scroll_arg", "parallax_uv", "reset_scroll"),
        "Orb": ("collision_specs", "domain_aabb", "point_frame"),
        "Echo": ("process", "fingerprint", "tail_seconds", "reset_state"),
        "Slider": ("has_focus", "pressed", "label_space", "on_focus_lost", "on_mouse_leave",
                   "on_mouse_down", "on_mouse_drag", "on_mouse_up", "on_mouse_scroll"),
        # WidgetManager dispatch (UIWidget is not exported: authors never override these).
        "TextInput": ("on_key", "on_char", "on_mouse_down", "on_key_down", "on_key_up"),
        "Button": ("on_mouse_click", "on_mouse_double_click", "on_mouse_move"),
        "Menu": ("on_mouse_click", "on_mouse_move"),
        "Sheet": ("image_for_frame", "src_rect"),
        "Text": ("displayed_text", "domain_aabb"),
    }

    def test_hooks_are_private(self):
        for cls_name, names in self.HOOKS.items():
            cls = getattr(scena, cls_name)
            for name in names:
                with self.subTest(cls=cls_name, name=name):
                    self.assertFalse(hasattr(cls, name), f"{cls_name}.{name} is public again")

    def test_canary_class_walk_catches_a_public_hook(self):
        class _Probe(scena.Glow):
            def apply(self, shape):   # the pre-sweep spelling
                pass
        allow = _guia_words() | KEPT_PUBLIC | SURFACE_NOT_IN_GUIA
        self.assertIn("apply", _scena_members(_Probe) - allow)

    def test_unused_ypos_is_not_exported(self):
        # No parameter takes YPos (XPos is align=); it stays in scena.shapes.
        self.assertNotIn("YPos", scena.__all__)
        self.assertFalse(hasattr(scena, "YPos"))

    # Engine vocabulary: a public member with one of these names is a hook
    # (draw walk, frame tick, compose, registry bookkeeping), whatever the Guia
    # says elsewhere. ``draw`` / ``update`` stay public on purpose (KEPT_PUBLIC).
    # The word-bag walk above cannot see these: "render", "tick" and "step"
    # are ordinary Guia words (``lib.render()``, "on_update é o tick").
    HOOK_WORDS = frozenset({
        "render", "tick", "step", "invalidate", "compact", "shader",
        "release_surfaces", "hit_feedback", "replaces_sprite_body",
        "append_object", "tombstone_object", "is_neutral_response",
        "exempt_from_post", "live_count", "from_value",
    })

    def _hook_hits(self, names):
        return sorted(set(names) & self.HOOK_WORDS)

    def test_no_exported_class_exposes_a_hook_word(self):
        classes, objects = _exports()
        bad = {n: h for n, c in classes.items() if (h := self._hook_hits(_scena_members(c)))}
        bad.update({n: h for n, o in objects.items() if (h := self._hook_hits(_public(o)))})
        self.assertEqual(bad, {}, "underscore engine hooks (Scena Design, author surface)")

    def test_no_reachable_object_exposes_a_hook_word(self):
        init(width=400, height=300)
        bad = {label: h for label, obj in _reachable_objects().items()
               if (h := self._hook_hits(_public(obj)))}
        self.assertEqual(bad, {})

    def test_canary_hook_word_is_caught(self):
        class _Probe(scena.Vignette):
            def tick(self, dt):
                pass
        self.assertEqual(self._hook_hits(_scena_members(_Probe)), ["tick"])

    def test_removed_second_spellings_stay_gone(self):
        from scena.background import BackgroundField
        from scena.state import Attribute
        for owner, name in ((BackgroundField, "scroll_x"), (BackgroundField, "scroll_y"),
                            (Attribute, "set_value_no_owner_update")):
            with self.subTest(name=name):
                self.assertFalse(hasattr(owner, name))
