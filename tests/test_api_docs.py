"""Author-facing errors, signatures and docs stay honest across the surface.

Bug classes (API documentation audit, 2026-09-29):

* **Engine words in a message** — the unknown-keyword "Valid:" list printed
  ``cls`` for looks built with ``__new__``.
* **Python's arity message** — ``Polygon.__init__() got an unexpected
  keyword argument 'pionts'``: no fix, and an ``__init__`` the author never
  wrote. Walked over every exported class.
* **Guia names ≠ keyword names** — ``remap(v, in0, …)`` while the code says
  ``remap(value, in_min, …)``: a keyword call copied from the Guia fails.
  ``validate_guia.check_parameter_rows`` compares every row and signature
  line to the real signature.

Pair sides and ``Handle()`` from the same audit: ``test_pair_sides``,
``test_process.TestHandleConstruction``.
"""
from __future__ import annotations

import enum
import inspect
import os
import re
import sys
import unittest
import warnings

from tests.source_support import iter_files
from tests import repo_layout as layout  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

import scena
from scena import init, Vec2, Color, Colormap, Entity


def _raw_arity_message(msg: str) -> bool:
    """Python's own binding error: ``X.__init__() got …`` / ``… takes N …``."""
    return (
        "__init__()" in msg
        or "__new__()" in msg
        or "got an unexpected keyword argument '" in msg
    )


class TestUnknownKeywordMessages(unittest.TestCase):
    """Every exported class answers a typo with the fix, never ``__init__()``."""

    @classmethod
    def setUpClass(cls):
        init(width=400, height=300)

    def _classes(self):
        for name in scena.__all__:
            obj = getattr(scena, name)
            if not inspect.isclass(obj) or issubclass(obj, (enum.Enum, BaseException)):
                continue
            # Singletons and engine-built records: authors never construct them.
            if name in {"Mouse", "KeyPressed", "Clock", "ColorNames",
                        "CollisionInfo", "TouchingContact", "State", "Attribute"}:
                continue
            yield name, obj

    def test_unknown_keyword_names_the_fix(self):
        for name, cls in self._classes():
            with self.subTest(cls=name):
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    try:
                        cls(zzq_not_a_knob=1)
                    except TypeError as exc:
                        msg = str(exc)
                    except Exception as exc:   # e.g. Act() base-class refusal
                        msg = str(exc)
                    else:
                        self.fail(f"{name}(zzq_not_a_knob=1) was accepted")
                self.assertFalse(_raw_arity_message(msg), f"{name}: {msg}")
                self.assertNotRegex(msg, r"\bcls\b|\bself\b")

    def test_valid_list_has_no_cls(self):
        for name, cls in self._classes():
            with self.subTest(cls=name):
                try:
                    cls(amout=1)
                except Exception as exc:
                    msg = str(exc)
                    if "Valid:" in msg:
                        valid = msg.split("Valid:")[1]
                        self.assertNotRegex(valid, r"\bcls\b")

    def test_typo_gets_did_you_mean(self):
        cases = [
            (lambda: scena.Polygon(pionts=[(0, 0), (1, 0), (0, 1)]), "points"),
            (lambda: Entity(gruop="a"), "group"),
            (lambda: scena.Sheet("a.png", colss=2), "cols"),
            (lambda: scena.History(max_point=3), "max_points"),
            (lambda: scena.Palette("plasma", step=3), "steps"),
            (lambda: scena.Neon(amout=1), "amount"),
        ]
        for call, fix in cases:
            with self.assertRaises(TypeError) as ctx:
                call()
            self.assertIn(f"Did you mean '{fix}'", str(ctx.exception))

    def test_missing_argument_shows_the_call(self):
        with self.assertRaises(TypeError) as ctx:
            scena.Grid(cols=2)
        self.assertIn("Grid() needs parent", str(ctx.exception))
        self.assertIn("Write Grid(parent, cols, rows", str(ctx.exception))

    def test_color_keyword_shows_the_forms(self):
        with self.assertRaises(TypeError) as ctx:
            Color(r=1)
        self.assertIn('Color("red")', str(ctx.exception))

    def test_author_entity_subclass_gets_the_same_help(self):
        class Heroi(Entity):
            def __init__(self, vida):
                super().__init__()
                self.vida = vida
        with self.assertRaises(TypeError) as ctx:
            Heroi()
        self.assertIn("Heroi() needs vida. Write Heroi(vida)", str(ctx.exception))
        with self.assertRaises(TypeError) as ctx:
            Heroi(vidda=3)
        self.assertIn("Did you mean 'vida'", str(ctx.exception))
        self.assertEqual(Heroi(3).vida, 3)

    def test_setup_still_runs_once_after_the_outer_init(self):
        runs = []

        class Base(Entity):
            def setup(self):
                runs.append(type(self).__name__)

        class Child(Base):
            def __init__(self, n=1):
                super().__init__()

        Child()
        self.assertEqual(runs, ["Child"])

    def test_error_raised_inside_the_body_passes_through(self):
        with self.assertRaises(ValueError):
            Color(300, 0, 0)          # right shape, wrong value: the body's own message


class TestVec2OperatorMessages(unittest.TestCase):
    def test_messages_name_the_fix(self):
        v = Vec2(1, 2)
        cases = [
            (lambda: v + 5, "v + (5, 5)"),
            (lambda: v - "a", "(x, y) pair"),
            (lambda: v * "a", "v * 2"),
            (lambda: v / "a", "v / 2"),
            (lambda: v * Vec2(1, 1), "v.dot(w)"),
        ]
        for call, fix in cases:
            with self.assertRaises(TypeError) as ctx:
                call()
            msg = str(ctx.exception)
            self.assertIn(fix, msg)
            self.assertNotIn("<class", msg)
            self.assertNotIn("sequence", msg)
        self.assertEqual(v * 2, Vec2(2, 4))
        self.assertEqual(v / 2, Vec2(0.5, 1))


class TestRenamedParameters(unittest.TestCase):
    """Keyword names the Guia spells are the real ones."""

    @classmethod
    def setUpClass(cls):
        init(width=400, height=300)

    def test_keywords_from_the_guia_work(self):
        cm = Colormap([(0, "black"), (1, "white")])
        self.assertAlmostEqual(cm.get_color(t=1.0).rgb[1], 1.0, places=5)
        self.assertEqual(scena.remap(value=5, in_min=0, in_max=10, out_min=0, out_max=100), 50)
        self.assertEqual(scena.heading(origin=(0, 0), target=(1, 0)), 0)
        self.assertIsNotNone(scena.nearest(origin=(0, 0), items=[(1, 1)]))
        Color.interpolate(color1=Color("red"), color2=Color("blue"), t=0.5)
        self.assertIn("cell", inspect.signature(scena.Slider).parameters)
        self.assertIn("fn", inspect.signature(Entity.goto_mode).parameters)


class TestGuiaParameterRows(unittest.TestCase):
    """``validate_guia.check_parameter_rows``: Guia names are real keywords."""

    @classmethod
    def setUpClass(cls):
        init(width=400, height=300)
        sys.path.insert(0, layout.GUIDE_TOOLS)
        import validate_guia  # type: ignore
        cls.v = validate_guia

    def test_guia_rows_match_signatures(self):
        self.assertEqual(self.v.check_parameter_rows(), [])

    def test_canary_planted_row_is_caught(self):
        row = (
            '<tr><td><code>remap(v, in0)</code></td><td class="sig">'
            '<span class="params">Parâmetros: v (número), in0 (número)</span></td></tr>'
        )
        errors = self.v.check_parameter_rows(row)
        self.assertEqual(len(errors), 1)
        self.assertIn("'v'", errors[0])

    def test_canary_planted_signature_line_is_caught(self):
        line = '<p class="sig"><code>heading(de, para)</code></p>'
        self.assertEqual(len(self.v.check_parameter_rows(line)), 1)

    def test_star_args_placeholders_are_allowed(self):
        row = (
            '<tr><td><code>Color(nome)</code></td><td class="sig">'
            '<span class="params">Parâmetros: nome (str)</span></td></tr>'
        )
        self.assertEqual(self.v.check_parameter_rows(row), [])


class TestGuiaConstructorRows(unittest.TestCase):
    """Every keyword of a documented constructor has a row that explains it.

    Bug class: ``Texture(…, scale=, tile_size=, angle=, color=, shift=)`` and
    the widgets' ``width=`` / ``height=`` were spelled in the signature line but
    had no row; ``Fire(angle=, rate=, tongues=)`` had no catalog row and the gap
    check was blind to them (it read ``__new__`` / ``__init__``, not the class's
    published ``__signature__``).
    """

    @classmethod
    def setUpClass(cls):
        init(width=400, height=300)
        sys.path.insert(0, layout.GUIDE_TOOLS)
        import validate_guia  # type: ignore
        cls.v = validate_guia

    def test_guia_constructor_rows_are_complete(self):
        self.assertEqual(self.v.check_constructor_rows(), [])

    def test_canary_signature_without_rows_is_caught(self):
        section = (
            '<p class="sig"><code>Texture(source, fit=, scale=)</code></p>'
            '<table><tr><td><code>source</code></td><td>1º</td></tr>'
            '<tr><td><code>fit</code></td><td>nome=</td></tr></table></section>'
        )
        errors = self.v.check_constructor_rows(section)
        self.assertEqual(len(errors), 1)
        self.assertIn("scale", errors[0])

    def test_family_shared_keywords_are_not_required(self):
        # layer= / group= live in "Todo objeto na tela"; color= / visual= /
        # line_width= in "todo Shape".
        section = (
            '<p class="sig"><code>Circle(center=, radius=)</code></p><table>'
            + "".join(f'<tr><td><code>{n}</code></td></tr>' for n in (
                "center", "radius", "box", "angle", "spread", "use_center",
                "perimeter_point", "p1", "p2"))
            + '</table></section>'
        )
        self.assertEqual(self.v.check_constructor_rows(section), [])

    def test_class_signature_knobs_are_seen(self):
        # Fire publishes angle= / rate= / tongues= only through __signature__.
        real, _kw, _pos = self.v.real_parameters(scena.Fire)
        self.assertTrue({"angle", "rate", "tongues", "soft_edge"} <= set(real))

    def test_canary_catalog_card_missing_a_knob_is_a_gap(self):
        bags = self.v.load_catalogs()
        card = dict(next(c for c in bags["SPATIAL"] if c["name"] == "Fire"))
        card["params"] = [p for p in card["params"] if p["name"] != "tongues"]
        _errors, gaps = self.v.check_catalog_signatures({"SPATIAL": [card]})
        self.assertTrue(any("tongues" in g for g in gaps), gaps)


class TestGuiaSymbolsAreDescribed(unittest.TestCase):
    """Search-index entries land on a section that names the symbol.

    Bug class: ``WaterFill`` / ``Stroke`` / ``ParallaxLayerError`` had a
    ``symbols.json`` entry pointing at a section that never mentioned them —
    "documented" only in the index.
    """

    @classmethod
    def setUpClass(cls):
        init(width=400, height=300)
        sys.path.insert(0, layout.GUIDE_TOOLS)
        import validate_guia  # type: ignore
        cls.v = validate_guia

    def _symbols(self):
        bags = self.v.load_catalogs()
        return bags, self.v.catalog_symbols(bags) + self.v.core_symbols()

    def test_every_symbol_anchor_names_it(self):
        bags, symbols = self._symbols()
        self.assertEqual(self.v.check_symbols_described(symbols, bags), [])

    def test_canary_misplaced_anchor_is_caught(self):
        bags, _ = self._symbols()
        planted = [{"name": "WaterFill", "anchor": "reativo-liga", "catalog": False}]
        self.assertEqual(len(self.v.check_symbols_described(planted, bags)), 1)

    def test_every_export_has_a_symbol(self):
        _bags, symbols = self._symbols()
        names = {s["name"] for s in symbols}
        self.assertEqual(sorted(set(scena.__all__) - names), [])


class TestEngineToolingIsNotExported(unittest.TestCase):
    def test_banner_helpers_live_in_process(self):
        # They read / clear the SCENA WARNING banner, not author errors
        # (those raise). Engine tooling, like set_leak_detector.
        for name in ("last_author_error", "clear_author_error"):
            self.assertNotIn(name, scena.__all__)
        from scena.process import clear_author_error, last_author_error  # noqa: F401


class TestCircularLinkMessage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init(width=400, height=300)

    def test_message_names_both_ends_and_the_fix(self):
        from scena import Circle
        from scena.state import CircularReferenceError
        a = Circle()
        b = Circle()
        try:
            a["radius"] @= lambda: b.radius + 1
            with self.assertRaises(CircularReferenceError) as ctx:
                b["radius"] @= lambda: a.radius + 1
            msg = str(ctx.exception)
            self.assertIn("radius of the Circle made at test_api_docs.py:", msg)
            self.assertEqual(msg.count("the Circle made at"), 3)  # b, a, then b again
            self.assertIn("Link one direction only", msg)
            self.assertNotIn("dependency graph", msg)
        finally:
            a.destroy()
            b.destroy()


class TestMenuMaterialBackground(unittest.TestCase):
    """A20: ``Menu(background=Gradient(…))`` crashed on the first draw.
    A29: the A20 fix drew a solid end stop — its test checked the paint's
    type, not the pixels. The raw material shader lives at the origin; the
    panel is far from it. Pixel checks live in ``tests/test_menu.py``
    (``MenuBackgroundTest``); this is the smoke over both materials."""

    @classmethod
    def setUpClass(cls):
        init(width=400, height=300)

    def test_gradient_and_texture_backgrounds_paint_the_panel(self):
        import numpy as np
        import skia
        from scena import Menu, Gradient, Texture
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")          # missing file: checkerboard
            backgrounds = (Gradient("red", "blue"), Texture("tex_missing.png"))
        for bg in backgrounds:
            with self.subTest(bg=type(bg).__name__):
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    menu = Menu(options=["A", "B"], background=bg, modal=False)
                try:
                    info = skia.ImageInfo.Make(400, 300, skia.kRGBA_8888_ColorType,
                                               skia.kPremul_AlphaType)
                    surface = skia.Surface.MakeRaster(info)
                    menu.draw(surface.getCanvas())
                    img = surface.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)
                    y = int((menu._y1 + menu._y2) * 0.5)
                    row = img[y, int(menu._x1) + 3:int(menu._x2) - 3, :3].astype(int)
                    spread = int(np.abs(row - row[0]).max())
                    self.assertGreater(spread, 60, f"{bg!r} painted a flat panel")
                finally:
                    menu.destroy()


class TestMaterialShadersStayInTheirFrame(unittest.TestCase):
    """Bug class of A29: a Gradient / Texture shader read outside a Shape host.

    ``_skia_shader`` / ``_shader_for_scale`` / ``_shader_for_local`` are
    origin-centered local-frame shaders. Only ``style.py`` (which owns the
    Shape host fit and the wallpaper frame) and ``recipes.py`` (procedural
    fills, not host-fit) may read them. Any other drawer goes through
    ``style._material_paint_for_rect``.
    """

    ALLOWED = {"style.py", "recipes.py"}
    PATTERN = re.compile(r"\._(skia_shader|shader_for_scale|shader_for_local)\b")

    def _offenders(self, sources):
        return sorted(
            name for name, text in sources.items()
            if name not in self.ALLOWED and self.PATTERN.search(text)
        )

    def test_no_module_reads_material_shaders_directly(self):
        pkg = os.path.join(ROOT, "scena")
        sources = {}
        for path in iter_files(pkg, ".py"):
            with open(path, encoding="utf-8") as fh:
                sources[os.path.basename(path)] = fh.read()
        self.assertEqual(
            self._offenders(sources), [],
            "Draw Gradient / Texture outside a Shape with "
            "style._material_paint_for_rect(material, cx, cy, hw, hh).",
        )

    def test_canary_direct_shader_read_is_caught(self):
        planted = {"uiwidget.py": "paint.setShader(bg._skia_shader)\n"}
        self.assertEqual(self._offenders(planted), ["uiwidget.py"])


class TestLinkClaimsUseLambda(unittest.TestCase):
    """Prose that calls a constructor point a link must spell it with ``lambda``.

    Construction copies a bare value (``Line(p1=a.center)`` is a snapshot) and
    links a callable ([Guia — Fórmulas nos construtores]). The Anchor docstring
    and four design-doc lines once said the bare spelling linked. Heuristic: a
    line with a bare dotted point keyword and a link word, no copy word and no
    ``lambda`` (a mixed line already teaches both).
    """

    KW = (r"(?:p1|p2|center|top_left|top_right|bottom_left|bottom_right|"
          r"top_center|bottom_center|left_center|right_center|vertex|"
          r"perimeter_point|start|end)")
    BARE = re.compile(r"\b" + KW + r"=(?!lambda\b|None\b|True\b|False\b)"
                      r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*(?![\w.(\[])")
    LINK = re.compile(r"link|\bliga|follows|\bsegue|acompanha", re.I)
    COPY = re.compile(r"\bcop|snapshot|cópia|não acompanha|not follow", re.I)

    def _offenders(self, sources):
        out = []
        for name, text in sources.items():
            for i, line in enumerate(text.splitlines(), 1):
                if ("lambda" not in line and self.BARE.search(line)
                        and self.LINK.search(line) and not self.COPY.search(line)):
                    out.append(f"{name}:{i}: {line.strip()[:120]}")
        return out

    def _sources(self):
        paths = (iter_files(os.path.join(ROOT, "scena"), ".py")
                 + iter_files(layout.DESIGN, ".md")
                 + [layout.GUIDE_HTML]
                 + iter_files(layout.TUTORIAL, ".html"))
        out = {}
        for path in paths:
            with open(path, encoding="utf-8") as fh:
                out[os.path.relpath(path, ROOT)] = fh.read()
        return out

    def test_no_bare_part_is_called_a_link(self):
        self.assertEqual(
            self._offenders(self._sources()), [],
            "A bare point in a constructor is copied. Write the link as "
            "Line(p1=lambda: a.center), or say it copies.",
        )

    def test_canary_bare_link_claim_is_caught(self):
        planted = {"shapes.py": "Outbound links (e.g. ``Line(p1=a.center, …)``) are fine.\n"
                                "Line(p1=lambda: a.center)  # links\n"
                                "Line(p1=a.center)  # copies once\n"}
        self.assertEqual(len(self._offenders(planted)), 1)


class TestMessagesNameTheFix(unittest.TestCase):
    """Second wave of the audit: messages that named no fix or leaked reprs."""

    @classmethod
    def setUpClass(cls):
        init(width=400, height=300)

    def _msg(self, call, exc=Exception):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with self.assertRaises(exc) as ctx:
                call()
        return str(ctx.exception)

    def test_every_missing_layer_lists_layers_and_the_create_fix(self):
        from scena import above, below, canvas
        calls = {
            "above": lambda: above("nolayer"),
            "below": lambda: below("nolayer"),
            "using": lambda: canvas.layers.using("nolayer").__enter__(),
            "default=": lambda: setattr(canvas.layers, "default", "nolayer"),
            "layer=": lambda: setattr(scena.Circle(), "layer", "nolayer"),
        }
        for label, call in calls.items():
            with self.subTest(call=label):
                msg = self._msg(call, ValueError)
                self.assertIn("Existing layers: default", msg)
                self.assertIn("canvas.layers.create('nolayer'", msg)
        self.assertIn("Did you mean 'default'",
                      self._msg(lambda: above("defualt"), ValueError))

    def test_no_python_type_repr_in_messages(self):
        from scena import distance, closest_point, Color, Vec2
        calls = [
            lambda: Color(object()),
            lambda: scena.shapes._xy_of(object(), required=True),
            lambda: Vec2(1, 2) + object(),
        ]
        for call in calls:
            msg = self._msg(call, TypeError)
            self.assertNotIn("<class", msg)

    def test_geometry_helper_names_what_it_supports(self):
        from scena.geom import _shape_center
        msg = self._msg(lambda: _shape_center(object()), TypeError)
        self.assertIn("supported: Line, Circle", msg)

    def test_presets_suggest_the_close_name(self):
        from scena import Palette, Colormap
        for call in (lambda: Palette("plasm"), lambda: Colormap.from_preset("plasm")):
            msg = self._msg(call, ValueError)
            self.assertIn("Did you mean 'plasma'", msg)
            self.assertLess(len(msg), 300)          # not a dump of every preset

    def test_set_defaults_typo(self):
        msg = self._msg(lambda: scena.set_defaults(line_widht=2), TypeError)
        self.assertIn("Did you mean 'line_width'", msg)
        self.assertIn("Valid:", msg)

    def test_microphone_backends_is_checked(self):
        from scena import Microphone
        for bad in (5, "null", []):
            with self.subTest(bad=bad):
                msg = self._msg(lambda: Microphone(backends=bad), TypeError)
                self.assertIn("miniaudio.Backend", msg)

    def test_spatial_fx_on_ui_is_a_ui_layer_error(self):
        from scena.registry import UiLayerError
        self._msg(lambda: scena.Orb(layer="ui"), UiLayerError)


class TestEverythingHasHoverDocs(unittest.TestCase):
    """What an editor shows on hover: every export, every public member, every
    parameter. Convention (Scena Design, author surface): a one-line summary,
    optional prose, then ``Args:`` (``Attributes:`` for engine-built records)
    naming each public parameter.

    Bug class: 14 exports, ~250 public members and ~700 parameters had no
    docstring text (C1–C3 of the 2026-09 API documentation audit).
    """

    @classmethod
    def setUpClass(cls):
        init(width=400, height=300)

    @staticmethod
    def _full_doc(obj) -> str:
        doc = inspect.getdoc(obj) or ""
        if inspect.isclass(obj):
            for hook in ("__init__", "__new__"):
                fn = obj.__dict__.get(hook)
                if fn is not None:
                    fn = inspect.unwrap(getattr(fn, "__func__", fn))
                    doc += "\n" + (inspect.getdoc(fn) or "")
        return doc

    def _exports(self):
        for name in scena.__all__:
            obj = getattr(scena, name)
            if inspect.isclass(obj) or inspect.isroutine(obj):
                yield name, obj

    def test_every_export_has_a_docstring(self):
        bad = [n for n, o in self._exports() if not (o.__doc__ or "").strip()]
        self.assertEqual(bad, [])

    def test_every_public_member_has_a_docstring(self):
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from test_api_surface import KEPT_PUBLIC, SURFACE_NOT_IN_GUIA, _reachable_objects
        owners = [o for _n, o in self._exports() if inspect.isclass(o)]
        owners += [type(o) for o in (scena.canvas, scena.group, scena.ui, scena.audio,
                                     scena.collision, scena.st, scena.ready, scena.recently)]
        owners += [type(o) for o in _reachable_objects().values()]
        seen, bad = set(), []
        for klass in owners:
            for name in dir(klass):
                if name.startswith("_") or name in KEPT_PUBLIC or name in SURFACE_NOT_IN_GUIA:
                    continue
                owner = next((k for k in klass.__mro__ if name in vars(k)), None)
                if owner is None or not (owner.__module__ or "").split(".")[0] == "scena":
                    continue
                if (owner, name) in seen:
                    continue
                seen.add((owner, name))
                raw = vars(owner)[name]
                fn = raw.fget if isinstance(raw, property) else getattr(raw, "__func__", raw)
                if not (isinstance(raw, property) or inspect.isfunction(fn)):
                    continue
                if not ((fn.__doc__ or "").strip() or (isinstance(raw, property) and raw.__doc__)):
                    bad.append(f"{owner.__name__}.{name}")
        self.assertEqual(sorted(bad), [])

    def test_every_parameter_is_described(self):
        bad = {}
        for name, obj in self._exports():
            if inspect.isclass(obj) and issubclass(obj, (enum.Enum, BaseException)):
                continue
            try:
                sig = inspect.signature(obj)
            except (TypeError, ValueError):
                continue
            doc = self._full_doc(obj)
            missing = [
                p.name for p in sig.parameters.values()
                if p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
                and not p.name.startswith("_")
                and not re.search(rf"\b{re.escape(p.name)}\b", doc)
            ]
            if missing:
                bad[name] = missing
        self.assertEqual(bad, {})


class TestSignaturesReadWell(unittest.TestCase):
    """What ``help()`` / IDLE calltips / editor autocomplete show.

    Bug classes: placeholder defaults printed as ``<object object at 0x…>``;
    constructors ending in ``**kwargs`` that hid real keywords (``layer=`` /
    ``group=`` on SpatialFx) or only existed to reject typos; one
    lone ``@overload`` (``Sprite(source=None, **kwargs)``) that made static
    tools hide all twenty real parameters; shape model keywords shown as
    required although ``Circle()`` works.
    """

    @classmethod
    def setUpClass(cls):
        init(width=400, height=300)

    def _callables(self):
        for name in scena.__all__:
            obj = getattr(scena, name)
            if inspect.isroutine(obj):
                yield name, obj
            elif inspect.isclass(obj) and not issubclass(obj, (enum.Enum, BaseException)):
                yield name, obj
                for attr in dir(obj):
                    if attr.startswith("_"):
                        continue
                    member = getattr(obj, attr, None)
                    if inspect.isroutine(member):
                        yield f"{name}.{attr}", member

    def test_no_object_address_in_any_default(self):
        bad = []
        for label, fn in self._callables():
            try:
                sig = inspect.signature(fn)
            except (TypeError, ValueError):
                continue
            if " at 0x" in str(sig):
                bad.append(f"{label}{sig}")
        self.assertEqual(bad, [])

    def test_no_exported_signature_hides_keywords_behind_kwargs(self):
        bad = []
        for label, fn in self._callables():
            if "." in label:
                continue
            try:
                sig = inspect.signature(fn)
            except (TypeError, ValueError):
                continue
            if any(p.kind is p.VAR_KEYWORD for p in sig.parameters.values()):
                bad.append(label)
        self.assertEqual(bad, [], "list the real keywords (or publish __signature__)")

    def test_no_lone_overload_stub(self):
        from typing import get_overloads
        bad = []
        for label, fn in self._callables():
            targets = [fn]
            if inspect.isclass(fn):
                targets = [fn.__dict__.get("__new__"), fn.__dict__.get("__init__")]
            for target in targets:
                if isinstance(target, staticmethod):
                    target = target.__func__
                if not inspect.isfunction(target):
                    continue
                if len(get_overloads(inspect.unwrap(target))) == 1:
                    bad.append(label)
        self.assertEqual(sorted(set(bad)), [])

    def test_shape_models_are_all_optional_and_overloads_cover_gradual_forms(self):
        from typing import get_overloads
        for cls in (scena.Line, scena.Circle, scena.Ellipse, scena.Rect, scena.Square,
                    scena.RegularPolygon, scena.EquilateralTriangle):
            with self.subTest(cls=cls.__name__):
                required = [p.name for p in inspect.signature(cls).parameters.values()
                            if p.default is p.empty and p.kind is not p.VAR_POSITIONAL]
                self.assertEqual(required, [])
                gradual = [
                    ov for ov in get_overloads(cls.__new__)
                    if "center" in inspect.signature(ov).parameters
                    and all(p.default is not p.empty
                            for n, p in inspect.signature(ov).parameters.items() if n != "cls")
                ]
                self.assertTrue(gradual, "no overload for cls() / cls(center=…)")
                ov = inspect.signature(gradual[0]).parameters
                self.assertTrue(all(p.kind is not p.POSITIONAL_OR_KEYWORD
                                    for n, p in ov.items() if n != "cls"), "keyword-only")
                cls().destroy()
                cls(center=(10, 10)).destroy()

    def test_spatial_fx_published_keywords_are_accepted(self):
        for name in ("Fire", "Sunburst", "Starburst", "Rain", "Jet", "Sparks",
                     "GlowSpot", "Orb", "Warp", "Portal"):
            cls = getattr(scena, name)
            params = inspect.signature(cls).parameters
            with self.subTest(cls=name):
                for kw in ("layer", "group", "soft_edge"):
                    self.assertIn(kw, params)
                self.assertNotIn("id", params)
                impl = cls if name != "Fire" else scena.Fire
                self.assertEqual(params["soft_edge"].default, impl._soft_edge)
                fx = cls(soft_edge=params["soft_edge"].default, layer="top", group="probe_fx")
                self.assertAlmostEqual(fx.soft_edge, params["soft_edge"].default)
                fx.destroy()

    def test_varargs_have_names(self):
        for label, fn in (("Gradient", scena.Gradient), ("Palette", scena.Palette),
                          ("Colormap.from_colors", scena.Colormap.from_colors)):
            names = [p.name for p in inspect.signature(fn).parameters.values()
                     if p.kind is p.VAR_POSITIONAL]
            self.assertTrue(names and names[0] != "args", label)

    def test_py_typed_ships(self):
        self.assertTrue(os.path.exists(os.path.join(ROOT, "scena", "py.typed")))
        with open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8") as f:
            self.assertIn('scena = ["py.typed"]', f.read())


if __name__ == "__main__":
    unittest.main()
