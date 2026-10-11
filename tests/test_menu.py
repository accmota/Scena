"""Menu: lifecycle, modal mask, layout, await.

    python -m unittest tests.test_menu -v
"""
from __future__ import annotations

import os
import sys
import unittest
import warnings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena import Button, Circle, Entity, Menu, init, keyp, mouse, st
from scena.input import Mouse
from scena.orchestration import ScenaFramework
from scena.process import reset_process_scheduler, tick_processes
from scena.state import Attribute


def _frame(dt=0.1):
    ScenaFramework.get_instance().clock.advance(dt)
    tick_processes()


class MenuTest(unittest.TestCase):
    def setUp(self):
        init(width=800, height=600)
        reset_process_scheduler()
        self.fw = ScenaFramework.get_instance()
        self.wm = self.fw.widget_manager
        self.clock = self.fw.clock
        self.clock.paused = False
        self.clock.scale = 1.0
        self.keys = self.fw.keys
        self.keys._pressed_keys.clear()
        self.keys._once_fired.clear()
        self.keys._pending_edges.clear()
        self.keys._input_masked = False
        mouse._pressed_buttons.clear()
        mouse._mask_latch_buttons.clear()
        mouse._input_masked = False
        self.owned = []

    def tearDown(self):
        for obj in list(self.owned):
            try:
                obj.destroy()
            except Exception:
                pass
        for menu in (self.wm._open_modal_menu, self.wm._open_nonmodal_menu):
            if menu is not None:
                try:
                    menu.destroy()
                except Exception:
                    pass
        self.clock.paused = False

    def track(self, obj):
        self.owned.append(obj)
        return obj

    def _click_option(self, menu, index):
        row = index // menu._cols
        col = index % menu._cols
        gx, gy = menu._grid_origin()
        row_from_bottom = menu._rows - 1 - row
        x = gx + (col + 0.5) * menu._cell_w
        y = gy + (row_from_bottom + 0.5) * menu._cell_h
        menu._on_mouse_click(x, y, Mouse.BTN_LEFT)
        return x, y

    def test_pick_order_callback_and_bound_value(self):
        st.nave = "Azul"
        order = []
        def escolher(opcao):
            order.append(("choose", opcao, st.nave, keyp("A")))
        self.keys._press("A")
        menu = self.track(Menu(
            st["nave"], options=["Azul", "Vermelha"], on_choose=escolher, title="Nave",
        ))
        self.assertFalse(keyp("A"))
        self.assertIsNone(menu._ink)
        self._click_option(menu, 1)
        # Chrome (including the mask) is already gone before on_choose runs.
        self.assertEqual(order, [("choose", "Vermelha", "Vermelha", True)])
        self.assertFalse(menu.is_alive)
        self.assertTrue(keyp("A"))
        self.assertIsNone(self.wm.modal_widget)

    def test_same_choice_fires_again(self):
        seen = []
        menu = Menu(options=["Sim"], on_choose=lambda o: seen.append(o))
        self._click_option(menu, 0)
        menu = Menu(options=["Sim"], on_choose=lambda o: seen.append(o))
        self._click_option(menu, 0)
        self.assertEqual(seen, ["Sim", "Sim"])

    def test_destroy_is_none_and_skips_callback(self):
        seen = []
        menu = self.track(Menu(options=["A", "B"], on_choose=lambda o: seen.append(o)))
        menu.destroy()
        self.assertEqual(seen, [])
        self.assertIsNone(menu.choice)
        self.assertFalse(self.keys._input_masked)

    def test_second_modal_raises_nonmodal_replaces(self):
        first = self.track(Menu(options=["A"], title="Um"))
        with self.assertRaises(RuntimeError) as ctx:
            Menu(options=["B"], title="Dois")
        self.assertIn("Um", str(ctx.exception))
        self.assertTrue(first.is_alive)
        other = self.track(Menu(options=["C"], modal=False, title="Livre"))
        again = self.track(Menu(options=["D"], modal=False, title="Nova"))
        self.assertFalse(other.is_alive)
        self.assertIsNone(other.choice)
        self.assertTrue(again.is_alive)
        self.assertTrue(first.is_alive)
        self.assertFalse(keyp("A") if self.keys._pressed_keys else False)

    def test_modal_over_nonmodal_blocks_input(self):
        free = self.track(Menu(options=["Perto"], modal=False))
        self.keys._press("A")
        self.assertTrue(keyp("A"))
        modal = self.track(Menu(options=["Pausa"], title="P"))
        self.assertTrue(free.is_alive)
        self.assertFalse(keyp("A"))
        modal.destroy()
        self.assertTrue(keyp("A"))
        self.assertTrue(free.is_alive)

    def test_pause_restores_previous_scale(self):
        self.clock.scale = 0.5
        menu = self.track(Menu(options=["Ok"], pause=True))
        self.assertTrue(self.clock.paused)
        menu.destroy()
        self.assertFalse(self.clock.paused)
        self.assertAlmostEqual(self.clock.scale, 0.5)
        self.clock.paused = True
        menu = self.track(Menu(options=["Ok"], pause=True, modal=False))
        self.assertTrue(self.clock.paused)
        menu.destroy()
        self.assertTrue(self.clock.paused)

    def test_await_returns_choice_or_none(self):
        host = self.track(Entity())
        got = []

        async def asking(e):
            menu = Menu(options=["Sim", "Não"])
            got.append(await menu)

        host.mode = asking
        _frame(0.01)
        menu = self.wm._open_modal_menu
        self.assertIsNotNone(menu)
        self._click_option(menu, 0)
        _frame(0.01)
        self.assertEqual(got, ["Sim"])

        async def closing(e):
            menu = Menu(options=["Fica"])
            got.append(await menu)

        host.mode = closing
        _frame(0.01)
        self.wm._open_modal_menu.destroy()
        _frame(0.01)
        self.assertEqual(got, ["Sim", None])

    def test_leaving_mode_destroys_menu(self):
        host = self.track(Entity())

        async def asking(e):
            await Menu(options=["Espera"])

        async def other(e):
            return

        host.mode = asking
        _frame(0.01)
        self.assertIsNotNone(self.wm._open_modal_menu)
        host.mode = other
        _frame(0.01)
        self.assertIsNone(self.wm._open_modal_menu)
        self.assertFalse(self.keys._input_masked)

    def test_grid_hit_partial_row(self):
        menu = self.track(Menu(options=[1, 2, 3, 4, 5], cols=3, modal=False))
        self.assertEqual(menu._rows, 2)
        seen = []
        menu._on_choose = lambda o: seen.append(o)
        # bypass settle by clicking through on_mouse before replacing callback... already constructed
        # rebind and click index 4
        menu._settled = False
        def grab(o):
            seen.append(o)
        menu._on_choose = grab
        menu._on_choose_arity = 1
        # click would settle and destroy. Use index probe only plus one real click.
        for i in range(5):
            row = i // 3
            col = i % 3
            gx, gy = menu._grid_origin()
            y = gy + (menu._rows - 1 - row + 0.5) * menu._cell_h
            x = gx + (col + 0.5) * menu._cell_w
            self.assertEqual(menu._option_index_at(x, y), i)
        self._click_option(menu, 4)
        self.assertEqual(seen, [5])

    def test_box_shrinks_and_warns(self):
        from scena import Box
        tiny = Box(center=(400, 300), width=40, height=30)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            menu = self.track(Menu(
                options=["Uma opcao bem comprida"],
                box=tiny, font_size=48,
            ))
        self.assertTrue(any("clipping" in str(w.message) for w in caught))
        self.assertLessEqual(menu._option_size, menu._theme.menu_min_font_size + 0.1)
        self.assertAlmostEqual(menu.width, 40, places=3)

    def test_clamp_to_view(self):
        menu = self.track(Menu(options=["A"], center=(0, 0), modal=False))
        self.assertGreaterEqual(menu._x1, 0)
        self.assertGreaterEqual(menu._y1, 0)

    def test_center_lambda_follows(self):
        st.px = 100.0
        st.py = 200.0
        menu = self.track(Menu(
            options=["A"], modal=False,
            center=lambda: (st.px, st.py),
        ))
        st.px = 500.0
        menu._layout()
        self.assertAlmostEqual(menu._x1 + menu.width * 0.5, 500.0, places=3)

    def test_open_next_from_callback(self):
        opened = []
        def escolher(opcao):
            if opcao == "Proximo":
                opened.append(Menu(options=["Ok"], on_choose=lambda o: opened.append(o)))
        Menu(options=["Proximo"], on_choose=escolher)
        menu = self.wm._open_modal_menu
        self._click_option(menu, 0)
        self.assertEqual(len(opened), 1)
        self.assertTrue(opened[0].is_alive)
        opened[0].destroy()

    def test_bad_options_and_arity(self):
        with self.assertRaises(ValueError):
            Menu(options=[])
        with self.assertRaises(TypeError):
            Menu(options="Jogar")
        with self.assertRaises(TypeError):
            Menu(options=["A"], cols=0)
        with self.assertRaises(TypeError) as ctx:
            Menu(options=["A"], on_choose=lambda a, b: None)
        self.assertIn("escolher", str(ctx.exception))
        with self.assertRaises(TypeError):
            Menu(options=["A"], center=(1, 1), box=Attribute(1))

    def test_choice_is_read_only_and_callback_runs_after_close(self):
        menu = self.track(Menu(options=["A", "B"], modal=False))
        with self.assertRaises(AttributeError):
            menu.choice = "A"
        self.keys._press("Z")

        def boom(opcao):
            self.assertEqual(opcao, "B")
            self.assertFalse(self.keys._input_masked)
            self.assertFalse(modal.is_alive)
            raise RuntimeError("depois")

        modal = Menu(options=["A", "B"], on_choose=boom)
        with self.assertRaises(RuntimeError):
            self._click_option(modal, 1)
        self.assertFalse(self.keys._input_masked)
        self.assertTrue(keyp("Z"))

    def test_grid_cols_one_and_full_row(self):
        vertical = self.track(Menu(options=["a", "b", "c"], cols=1, modal=False))
        self.assertEqual(vertical._rows, 3)
        self.assertEqual(self._index_at(vertical, 1), 1)
        wide = self.track(Menu(options=["a", "b", "c"], cols=3, modal=False))
        self.assertEqual(wide._rows, 1)
        self.assertEqual(self._index_at(wide, 2), 2)

    def _index_at(self, menu, index):
        row = index // menu._cols
        col = index % menu._cols
        gx, gy = menu._grid_origin()
        y = gy + (menu._rows - 1 - row + 0.5) * menu._cell_h
        x = gx + (col + 0.5) * menu._cell_w
        return menu._option_index_at(x, y)

    def test_font_file_changes_measure(self):
        from tests.font_support import system_font_file
        path = system_font_file()
        if path is None:
            self.skipTest("no system .ttf found (tests/font_support.py)")
        plain = self.track(Menu(options=["Agora"], modal=False))
        filed = self.track(Menu(options=["Agora"], modal=False, font=path))
        self.assertNotAlmostEqual(plain._cell_w, filed._cell_w, places=2)

    def test_icons_length_missing_and_cell(self):
        import tempfile
        import skia
        with self.assertRaises(ValueError) as ctx:
            Menu(options=["A", "B"], icons=["only.png"])
        self.assertIn("icons=", str(ctx.exception))
        with self.assertRaises(TypeError):
            Menu(options=["A"], icons=[12])

        bare = self.track(Menu(options=["Azul", "Vermelha"], modal=False))
        with tempfile.TemporaryDirectory() as tmp:
            png = os.path.join(tmp, "azul.png")
            info = skia.ImageInfo.Make(8, 8, skia.kRGBA_8888_ColorType, skia.kPremul_AlphaType)
            surface = skia.Surface.MakeRaster(info)
            surface.getCanvas().clear(skia.ColorBLUE)
            surface.makeImageSnapshot().save(png, skia.kPNG)
            missing = os.path.join(tmp, "no-such.png")
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                menu = self.track(Menu(
                    options=["Azul", "Vermelha"],
                    icons=[png, missing],
                    modal=False,
                ))
            self.assertTrue(any("checkerboard" in str(w.message) for w in caught))
            self.assertEqual(len(menu._icon_images), 2)
            self.assertGreater(menu._cell_h, bare._cell_h)
            self.assertGreater(menu._icon_side, 0)
            info = skia.ImageInfo.Make(800, 600, skia.kRGBA_8888_ColorType, skia.kPremul_AlphaType)
            menu._hover_index = 0
            menu.draw(skia.Surface.MakeRaster(info).getCanvas())
            seen = []
            menu._on_choose = lambda o: seen.append(o)
            menu._on_choose_arity = 1
            self._click_option(menu, 0)
            self.assertEqual(seen, ["Azul"])

    def test_title_widens_panel_and_separates(self):
        from scena.uiwidget import measure_text, text_baseline_centered
        import skia

        bare = self.track(Menu(options=["A", "B"], modal=False))
        bare_w, bare_h = bare.width, bare.height
        bare.destroy()

        menu = self.track(Menu(
            options=["A", "B"],
            title="Titulo bem mais largo que as opcoes",
            modal=False,
        ))
        tw = measure_text(menu._title_font, menu.title)
        pad = menu._theme.menu_pad
        self.assertGreater(menu.width, bare_w)
        self.assertGreaterEqual(menu.width, tw + pad * 2 - 0.5)
        self.assertAlmostEqual(menu.height - bare_h, menu._title_h + pad, places=3)
        tx = menu._x1 + (menu.width - tw) * 0.5
        self.assertGreaterEqual(tx, menu._x1 - 0.01)
        self.assertLessEqual(tx + tw, menu._x2 + 0.01)

        band = menu._header_band_rect()
        self.assertIsNotNone(band)
        self.assertAlmostEqual(band.y(), menu._y2 - pad - menu._title_h, places=3)
        self.assertAlmostEqual(band.height(), pad + menu._title_h, places=3)
        self.assertAlmostEqual(band.width(), menu.width, places=3)
        gx, gy = menu._grid_origin()
        grid_top = gy + menu._grid_h
        self.assertAlmostEqual(band.y() - grid_top, gy - menu._y1, places=3)
        self.assertAlmostEqual(band.y() - grid_top, menu._theme.menu_option_pad, places=3)
        low = text_baseline_centered(menu._y2 - pad - menu._title_h, menu._title_h, menu._title_font)
        ascent_only = text_baseline_centered(band.y(), band.height(), menu._title_font)
        bounds = skia.Rect()
        menu._title_font.measureText(menu.title, bounds=bounds)
        tight = band.y() + band.height() * 0.5 + (bounds.fTop + bounds.fBottom) * 0.5
        self.assertAlmostEqual(menu._title_baseline(), tight, places=3)
        self.assertGreater(menu._title_baseline(), ascent_only)
        self.assertGreater(menu._title_baseline(), low)
        self.assertEqual(menu._option_index_at(menu._x1 + menu.width * 0.5, band.y() + 2), -1)
        self.assertIsNone(bare._header_band_rect())

        info = skia.ImageInfo.Make(800, 600, skia.kRGBA_8888_ColorType, skia.kPremul_AlphaType)
        menu.draw(skia.Surface.MakeRaster(info).getCanvas())

    def test_box_shrinks_to_fit_title(self):
        from scena import Box
        region = Box(center=(400, 300), width=160, height=240)
        short = self.track(Menu(
            options=["A"], title="Hi", box=region, font_size=40, modal=False,
        ))
        short_size = short._option_size
        short.destroy()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            long = self.track(Menu(
                options=["A"],
                title="Um titulo muito mais largo que a caixa",
                box=region, font_size=40, modal=False,
            ))
        self.assertTrue(any("clipping" in str(w.message) for w in caught))
        self.assertLess(long._option_size, short_size)
        self.assertAlmostEqual(long.width, 160, places=3)

    def test_options_center_under_header_and_in_box(self):
        from scena import Box
        roomy = Box(center=(400, 300), width=420, height=360)
        bare = self.track(Menu(options=["Uma", "Outra"], box=roomy, modal=False))
        gx, gy = bare._grid_origin()
        self.assertAlmostEqual(gy + bare._grid_h * 0.5, bare._y1 + bare.height * 0.5, places=3)
        self.assertGreater(gy, bare._y1 + bare._theme.menu_pad)
        bare.destroy()

        titled = self.track(Menu(
            options=["Uma", "Outra"], title="Topo", box=roomy, modal=False,
        ))
        band = titled._header_band_rect()
        gx, gy = titled._grid_origin()
        grid_mid = gy + titled._grid_h * 0.5
        well_mid = (titled._y1 + band.y()) * 0.5
        self.assertAlmostEqual(grid_mid, well_mid, places=3)
        self.assertAlmostEqual(band.y() - (gy + titled._grid_h), gy - titled._y1, places=3)
        self.assertAlmostEqual(band.y() + band.height(), titled._y2, places=3)

    def test_int_options_pass_the_value(self):
        seen = []
        menu = Menu(options=range(1, 4), cols=3, modal=False, on_choose=lambda n: seen.append(n))
        self._click_option(menu, 2)
        self.assertEqual(seen, [3])
        self.assertIsInstance(seen[0], int)


def _render(menu, w=800, h=600):
    """Raster of ``menu.draw`` on black (no flipY: row index == widget y)."""
    import skia
    info = skia.ImageInfo.Make(w, h, skia.kRGBA_8888_ColorType, skia.kPremul_AlphaType)
    surface = skia.Surface.MakeRaster(info)
    canvas = surface.getCanvas()
    canvas.clear(skia.ColorBLACK)
    menu.draw(canvas)
    return surface.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)


def _split_image(left, right, w=64, h=32):
    """In-memory image: left half ``left``, right half ``right`` (RGB 0-255)."""
    import numpy as np
    import skia
    px = np.zeros((h, w, 4), dtype=np.uint8)
    px[:, : w // 2, :3] = left
    px[:, w // 2:, :3] = right
    px[:, :, 3] = 255
    return skia.Image.fromarray(px, colorType=skia.kRGBA_8888_ColorType)


class MenuBackgroundTest(unittest.TestCase):
    """``background=`` paints the panel: color, Gradient, or Texture.

    A29: a material drawn with its raw shader sat at the view origin, so a
    Gradient panel was its last stop and a Texture a 48-unit sprite far away.
    These tests sample pixels, not paint types.
    """

    setUp = MenuTest.setUp
    tearDown = MenuTest.tearDown
    track = MenuTest.track

    def _px(self, img, x, y):
        return tuple(int(v) for v in img[int(y), int(x)][:3])

    def assertNear(self, got, want, tol=40):
        for g, w in zip(got, want):
            self.assertLessEqual(abs(g - w), tol, f"{got} is not near {want}")

    def _edges(self, menu):
        img = _render(menu)
        ym = (menu._y1 + menu._y2) * 0.5
        xm = (menu._x1 + menu._x2) * 0.5
        return img, {
            "left": self._px(img, menu._x1 + 2, ym),
            "mid": self._px(img, xm, ym),
            "right": self._px(img, menu._x2 - 3, ym),
            "low": self._px(img, xm, menu._y1 + 2),
            "high": self._px(img, xm, menu._y2 - 3),
        }

    def test_linear_gradient_spans_the_panel(self):
        from scena import Gradient
        menu = self.track(Menu(options=list("ABCD"), modal=False,
                               background=Gradient("red", "yellow")))
        _, e = self._edges(menu)
        self.assertNear(e["left"], (255, 0, 0))
        self.assertNear(e["right"], (255, 255, 0))
        self.assertNear(e["low"], (255, 128, 0))

    def test_gradient_follows_the_panel_off_center(self):
        from scena import Gradient
        menu = self.track(Menu(options=list("AB"), modal=False, center=(640, 470),
                               background=Gradient("red", "yellow")))
        _, e = self._edges(menu)
        self.assertNear(e["left"], (255, 0, 0))
        self.assertNear(e["right"], (255, 255, 0))

    def test_angle_radial_and_sized_gradients(self):
        from scena import Gradient
        vertical = self.track(Menu(options=list("ABCD"), modal=False,
                                   background=Gradient("red", "yellow", angle=90)))
        _, e = self._edges(vertical)
        self.assertNear(e["left"], e["right"], tol=6)
        self.assertNear(e["low"], (255, 0, 0))
        self.assertNear(e["high"], (255, 255, 0))
        vertical.destroy()

        radial = self.track(Menu(options=list("ABCD"), modal=False,
                                 background=Gradient("red", "yellow", type="radial")))
        _, e = self._edges(radial)
        self.assertNear(e["mid"], (255, 0, 0))
        self.assertNear(e["left"], (255, 255, 0))
        radial.destroy()

        # size= is measured from the panel center: the panel is narrower than
        # the ±200 ramp, so the middle is the midpoint and the edges are not ends.
        sized = self.track(Menu(options=["A"], modal=False,
                                background=Gradient("red", "yellow", size=200)))
        _, e = self._edges(sized)
        self.assertNear(e["low"], (255, 128, 0), tol=12)
        self.assertGreater(e["left"][1], 40)
        self.assertLess(e["right"][1], 215)

    def test_texture_fits_the_panel_with_alpha(self):
        from scena import Texture
        tex = Texture(_split_image((255, 0, 0), (0, 0, 255)), fit="stretch")
        menu = self.track(Menu(options=list("ABCD"), modal=False, center=(600, 420),
                               background=tex))
        _, e = self._edges(menu)
        self.assertNear(e["left"], (255, 0, 0), tol=8)
        self.assertNear(e["right"], (0, 0, 255), tol=8)
        menu.destroy()

        faded = Texture(_split_image((255, 0, 0), (0, 0, 255)), fit="stretch").set_alpha(0.5)
        menu = self.track(Menu(options=list("ABCD"), modal=False, background=faded))
        _, e = self._edges(menu)
        self.assertNear(e["left"], (128, 0, 0), tol=12)

    def test_solid_background_unchanged(self):
        menu = self.track(Menu(options=["A"], modal=False, background="navy"))
        _, e = self._edges(menu)
        self.assertNear(e["low"], (0, 0, 128), tol=6)

    def test_bad_background_raises_at_construction(self):
        import scena
        bad = [42, object(), scena.Neon()]
        if hasattr(scena, "WaterFill"):
            bad.append(scena.WaterFill())
        for value in bad:
            with self.subTest(value=type(value).__name__):
                with self.assertRaises(TypeError) as ctx:
                    Menu(options=["A"], modal=False, background=value)
                self.assertIn("background=", str(ctx.exception))
                self.assertIsNone(self.wm._open_nonmodal_menu)

    def test_gradient_color_points_to_background(self):
        from scena import Gradient
        with self.assertRaises(TypeError) as ctx:
            Menu(options=["A"], modal=False, color=Gradient("red", "blue"))
        self.assertIn("background=Gradient", str(ctx.exception))

    def test_highlight_takes_the_material_tone(self):
        from scena import Gradient, Texture
        grad = Gradient("red", "yellow")
        menu = self.track(Menu(options=["A"], modal=False, background=grad))
        want = grad.mean_color().lighter(0.45).with_alpha(0.5).color4f
        got = menu._highlight_paint().getColor4f()
        for g, w in zip((got.fR, got.fG, got.fB, got.fA), (want.fR, want.fG, want.fB, want.fA)):
            self.assertAlmostEqual(g, w, places=4)
        menu.destroy()

        tex = Texture(_split_image((255, 0, 0), (0, 0, 255)))
        menu = self.track(Menu(options=["A"], modal=False, background=tex))
        want = tex.color.lighter(0.45).with_alpha(0.5).color4f
        got = menu._highlight_paint().getColor4f()
        self.assertAlmostEqual(got.fR, want.fR, places=4)
        self.assertAlmostEqual(got.fB, want.fB, places=4)



class TestRegistryDestroySettlesTheMenu(MenuTest):
    """HD5 (Testing Design, HD): every destroy path (an act change, a layer
    drain, a group destroy go through ``registry.destroy``, not
    ``Menu.destroy``) closes the menu: chrome, modal mask, pause, handle."""

    def test_registry_destroy_closes_a_modal_paused_menu(self):
        from scena.canvas import ScenaCanvas
        menu = Menu(options=["um", "dois"], on_choose=lambda v: None, pause=True)
        self.assertIs(self.wm._open_modal_menu, menu)
        self.assertTrue(self.clock.paused)
        ScenaCanvas.get_current().registry.destroy(menu)
        self.assertFalse(menu.is_alive)
        self.assertIsNone(self.wm._open_modal_menu)
        self.assertIsNone(self.wm.modal_widget)
        self.assertFalse(self.keys._input_masked)
        self.assertFalse(self.clock.paused)
        h = menu._choice_handle
        self.assertTrue(h._done or h._cancelled)
        again = self.track(Menu(options=["x"], on_choose=lambda v: None))   # no "already open"
        self.assertIs(self.wm._open_modal_menu, again)


if __name__ == "__main__":
    unittest.main()
