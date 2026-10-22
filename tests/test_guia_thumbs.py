"""Guia catalog thumbnails (tools/guide/make_guia_thumbs.py).

Snippet choice, staleness hashing, the page data file, and the render guards
(blank look, animated look that does not move).

    python -m unittest tests.test_guia_thumbs -v
"""
from __future__ import annotations

import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUIDE = os.path.join(ROOT, "tools", "guide")   # tests/repo_layout.GUIDE_TOOLS
sys.path.insert(0, GUIDE)

import make_guia_thumbs as mt  # noqa: E402
import validate_guia as vg  # noqa: E402


def _card(**kw):
    item = {"id": "visual-x", "kind": "glow", "family": "visual", "name": "Neon",
            "code": 'c.visual = Neon("magenta")', "params": [{"name": "color", "def": "None"}]}
    item.update(kw)
    return item


class TestSnippet(unittest.TestCase):
    def test_first_statement_that_names_the_card(self):
        code = 'c.visual = Neon("magenta")\nc.visual = Neon("cyan", flicker=0.6)'
        self.assertEqual(mt.default_snippet(code, "Neon"), 'c.visual = Neon("magenta")')

    def test_setup_lines_before_it_come_along(self):
        code = "set_extrude_focus(600, 40)\nship.visual = Extrude(depth=40, layers=5)"
        self.assertEqual(mt.default_snippet(code, "Extrude"), code)

    def test_method_cards_match_the_attribute(self):
        self.assertEqual(mt.default_snippet("canvas.flash(0.6)\ncanvas.flash(1)", "canvas.flash"),
                         "canvas.flash(0.6)")

    def test_thumb_field_wins(self):
        self.assertEqual(mt.thumb_code(_card(thumb="Rain(p1=(0, 0), p2=(9, 9))")),
                         "Rain(p1=(0, 0), p2=(9, 9))")

    def test_every_card_in_scope_has_a_snippet_that_compiles(self):
        for bag in vg.load_catalogs().values():
            for it in bag:
                if mt.in_scope(it):
                    with self.subTest(it["id"]):
                        compile(mt.thumb_code(it), it["id"], "exec")


class TestHash(unittest.TestCase):
    def h(self, item, source="class Neon: pass"):
        return mt.entry_hash(item, source=source)

    def test_stable_for_the_same_inputs(self):
        self.assertEqual(self.h(_card()), self.h(_card()))

    def test_changes_with_each_input(self):
        base = self.h(_card())
        self.assertNotEqual(base, self.h(_card(code='c.visual = Neon("cyan")')))
        self.assertNotEqual(base, self.h(_card(thumb='c.visual = Neon("lime")')))
        self.assertNotEqual(base, self.h(_card(params=[{"name": "color", "def": "red"}])))
        self.assertNotEqual(base, self.h(_card(anim=True)))
        self.assertNotEqual(base, self.h(_card(), source="class Neon: x = 1"))
        old = dict(mt.SCENES["shape"])
        try:
            mt.SCENES["shape"]["v"] += 1
            self.assertNotEqual(base, self.h(_card()))
        finally:
            mt.SCENES["shape"] = old

    def test_unrelated_text_does_not_count(self):
        # The idea / search text is prose: editing it must not re-render.
        self.assertEqual(self.h(_card()), self.h(_card(idea="outro texto", search="neon")))


class TestPageData(unittest.TestCase):
    def test_thumbs_file_is_valid_and_points_at_real_cards(self):
        errors, _warnings = vg.check_thumbs(vg.load_catalogs())
        self.assertEqual(errors, [])

    def test_the_english_guide_shares_the_portuguese_pictures(self):
        # The thumbnails are rendered from the Portuguese cards. The English
        # cards translate prose defaults ("segue o objeto" → "follows the
        # object"), which are hash inputs: asked of the English cards, 102
        # pictures read as stale (2026-10-22).
        pt_warnings = vg.check_thumbs(vg.load_catalogs())[1]
        vg.set_lang("en")
        try:
            errors, en_warnings = vg.check_thumbs(vg.load_catalogs())
        finally:
            vg.set_lang("pt")
        self.assertEqual(errors, [])
        self.assertEqual(en_warnings, pt_warnings)

    def test_status_sees_stale_and_missing(self):
        bags = vg.load_catalogs()
        manifest = mt.load_manifest()
        it = next(i for i in mt.select(bags) if i["id"] in manifest)
        tampered = {it["id"]: dict(manifest[it["id"]], hash="0" * 16)}
        self.assertEqual(mt.status([it], tampered)[it["id"]], "stale")
        gone = {it["id"]: dict(manifest[it["id"]], src="thumbs/nope.webp")}
        self.assertEqual(mt.status([it], gone)[it["id"]], "missing")
        self.assertEqual(mt.status([it], {})[it["id"]], "missing")

    def test_card_fields_only_in_thumbnail_families(self):
        bags = {"FILTERS": [dict(_card(family="filter", id="flt"), thumb="Blur()")]}
        self.assertTrue(vg.validate_catalogs(bags))
        bags = {"LOOKS": [dict(_card(), thumb="c.visual = (")]}
        self.assertTrue(any("thumb" in e for e in vg.validate_catalogs(bags)))

    def test_only_the_toggle_remembers_the_view(self):
        # A gallery card click opened Abas *and saved it*: from then on that
        # catalog opened without its gallery (seen in one browser, not in a
        # fresh one). Every other way into Abas (a card, a link) is for now.
        src = vg.CATALOGS.read_text(encoding="utf-8")
        calls = re.findall(r"showView\(([^()]*)\)", src)
        self.assertTrue(calls)
        saved = [c for c in calls if not re.search(r",\s*(false|remember)\s*$", c)]
        self.assertEqual(saved, ["el, b.dataset.view, true"])


class TestVariants(unittest.TestCase):
    """``variants: "style"``: one picture per value the *code* accepts."""

    def setUp(self):
        self.bags = vg.load_catalogs()
        self.cards = {it["id"]: it for bag in self.bags.values() for it in bag}

    def test_choices_come_from_the_engine(self):
        from scena.visuals import HALO_STYLES
        self.assertEqual(mt.probe_choices(self.cards["visual-halo"], "style"), list(HALO_STYLES))

    def test_variant_sets_the_cards_own_call(self):
        v = {x["_value"]: x for x in mt.variant_items(self.cards["visual-halo"])}
        self.assertEqual(v["pulse"]["thumb"], 'c.visual = Halo(style="pulse")')
        self.assertEqual(mt._variant_label(v["pulse"]), 'Halo(style="pulse")')

    def test_positional_slot_is_replaced_not_duplicated(self):
        # SkyGradient("night"): palette is the 1st positional; a keyword too would raise.
        v = mt.variant_items(self.cards["bg-sky"])
        self.assertIn('SkyGradient("dawn")', [x["thumb"] for x in v])

    def test_guia_order_when_the_lists_agree(self):
        values = [x["_value"] for x in mt.variant_items(self.cards["bg-sky"])]
        self.assertEqual(values[:3], ["day", "dawn", "sunset"])     # the engine sorts them

    def test_guia_lists_every_value_the_code_accepts(self):
        self.assertEqual(vg.check_variant_choices(self.bags), [])

    def test_drift_between_guia_and_code_is_an_error(self):
        card = dict(self.cards["visual-halo"])
        card["params"] = [dict(p, meaning="hollow · fill") if p["name"] == "style" else p
                          for p in card["params"]]
        mt._CHOICES.pop((card["id"], "style"), None)
        errors = vg.check_variant_choices({"LOOKS": [card]})
        self.assertTrue(errors and "pulse" in errors[0], errors)

    def test_guide_choice_parsing(self):
        self.assertEqual(vg.guide_choices("camp · soft · <code>plume</code>"), ["camp", "soft", "plume"])
        self.assertEqual(vg.guide_choices("spark = impacto · fork = raios"), ["spark", "fork"])
        self.assertEqual(vg.guide_choices("haze · heat. Só na construção."), ["haze", "heat"])

    def test_page_data_nests_every_variant_under_its_card(self):
        data = vg.read_thumbs_js()
        for iid, card in self.cards.items():
            params = mt.variant_params(card)
            if not params:
                continue
            with self.subTest(iid):
                want = sum(len(mt.ordered_choices(card, p)) for p in params)
                self.assertEqual(len(data[iid].get("variants", [])), want)


class TestScenes(unittest.TestCase):
    def test_reductions_keep_or_average_small_lights(self):
        import numpy as np
        px = np.zeros((3, 3, 4), np.uint8)
        px[..., 3] = 255
        px[1, 1, :3] = 255                                   # one star in a 3×3 block
        area = mt._downscale(px, (1, 1), "area")[0, 0, 0]
        detail = mt._downscale(px, (1, 1), "detail")[0, 0, 0]
        top = mt._downscale(px, (1, 1), "max")[0, 0, 0]
        self.assertEqual((int(area), int(top)), (28, 255))
        self.assertTrue(area < detail < top)

    def test_gallery_lift_keeps_the_base(self):
        import numpy as np
        base = mt._hex_rgb(mt.BG)
        px = np.zeros((10, 10, 4), np.uint8)
        px[..., :3] = base
        px[..., 3] = 255
        px[5, 5, :3] = (base[0] + 40, base[1] + 40, base[2] + 40)    # a dim star
        out = mt._lift(px)
        self.assertEqual(tuple(out[0, 0, :3]), base)                   # the base stays
        lifted = int(out[5, 5, 0]) - base[0]
        self.assertAlmostEqual(lifted, 40 * mt.CARD_LIFT_MAX, delta=1)  # capped gain
        bright = px.copy()
        bright[4:7, 4:7, :3] = 250                                     # a lit area, not one pixel
        self.assertTrue((mt._lift(bright) == bright).all())           # already readable

    def test_measuring_uses_the_engines_domain(self):
        class Fx:
            def _domain_aabb(self):
                return (1, 2, 3, 40)
        self.assertEqual(mt._domain_box(Fx()), (1.0, 2.0, 3.0, 40.0))

    def test_impacts_have_their_own_scene(self):
        self.assertEqual(mt.scene_for(_card(family="impact", kind="screen", name="canvas.shake")), "impact")
        self.assertEqual(mt.poster_rule(_card(family="impact", kind="point", name="canvas.zap_at")), "peak")

    def test_transients_and_opt_out(self):
        self.assertEqual(mt.scene_for(_card(family="hit", kind="hit", name="flash")), "transient")
        self.assertEqual(mt.poster_rule(_card(family="life", kind="life", name="burn_out")), "event")
        self.assertFalse(mt.in_scope(_card(family="life", thumb=False)))
        self.assertTrue(mt.in_scope(_card(family="life")))



class TestPinnedSurface(unittest.TestCase):
    """The capture surface survives the engine's post → direct switch.

    Bug: ``bolas.py``'s README clip froze on the GPU. ``canvas.hit_at`` puts the
    frame on the post path; when the hit ends, ``_recover_direct_fb_path``
    rebinds the drawing surface to the (hidden, 64 px) window framebuffer, and
    the capture kept reading a surface nothing drew to. Any capture tool that
    sets ``fw._drawing_surface`` by hand must go through ``_pin_surface``.
    """

    def _fw(self):
        from types import SimpleNamespace
        bound = []
        draw = SimpleNamespace(rebind=lambda canvas, pixel_ratio: bound.append(canvas),
                               _shape_fx_surface=None, _shape_fx_pool=[])
        ctx = SimpleNamespace(flush=lambda: None, freeGpuResources=lambda: None,
                              resetGLTextureBindings=lambda: None)
        fw = SimpleNamespace(_scena_draw=draw, _context=ctx, _post_fx_stack=None,
                             _scene_surface=None, _fx_surface=None, _fx_surface2=None)
        fw._create_drawing_surface = lambda: setattr(fw, "_drawing_surface", "window FB")
        return fw, bound

    def test_leaving_the_post_path_keeps_drawing_into_the_capture(self):
        from scena.orchestration import ScenaFramework
        surf = SimpleSurface()
        fw, bound = self._fw()
        mt._pin_surface(fw, surf, 2.0)
        self.assertIs(fw._drawing_surface, surf)
        ScenaFramework._recover_direct_fb_path(fw)      # the engine's own switch
        self.assertIs(fw._drawing_surface, surf)
        self.assertIs(fw._drawing_canvas, surf.canvas)
        self.assertEqual(bound, [surf.canvas, surf.canvas])

    def test_readme_clips_pin_through_the_same_helper(self):
        with open(os.path.join(ROOT, "tools", "readme", "make_readme_media.py"),
                  encoding="utf-8") as fh:
            text = fh.read()
        bind = re.compile(r"fw\._drawing_surface,\s*fw\._drawing_canvas\s*=\s*surf,")
        self.assertEqual(len(bind.findall(text)), 0, "set the capture surface with _pin_surface")
        with open(mt.__file__, encoding="utf-8") as fh:
            self.assertEqual(len(bind.findall(fh.read())), 1, "only _pin_surface binds by hand")

class SimpleSurface:
    def __init__(self):
        self.canvas = object()

    def getCanvas(self):
        return self.canvas


if __name__ == "__main__":
    unittest.main()
