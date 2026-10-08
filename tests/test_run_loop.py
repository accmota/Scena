"""``run()`` frame order: camera / background after ``update`` (F8) and the
frame batch covering the pre-draw ticks (F9).

Headless: the real loop runs for a fixed number of frames on a raster Skia
surface; GLFW / GL / audio are mocked. ``canvas.effects`` and ``post_draw``
live on the ``ScenaFramework`` singleton and survive other modules, so this
fixture clears the stack and requires the direct framebuffer path (a mocked
GL context cannot create the scene render target).

    python -m unittest tests.test_run_loop -v
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import skia

import scena.audio_mixer as audio_mixer
import scena.orchestration as orch
from scena import canvas, init
from scena.events import cleanup_global_event_system, when
from scena.orchestration import ScenaFramework
from scena.state import Attribute, get_scena_system


class RunLoopTestCase(unittest.TestCase):
    """Drive ``ScenaFramework.run()`` for ``frames`` iterations."""

    def setUp(self):
        init(width=400, height=300)
        canvas.reset_view()
        # HitFeedback and other post effects survive the module that created
        # them. An active stack takes the GPU scene-RT path.
        canvas.effects.clear()
        self.fw = fw = ScenaFramework.get_instance()
        self._saved = dict(
            setup=fw.setup, update=fw.update, post_draw=fw.post_draw,
            _context=fw._context, _running=fw._running, _fx_auto=fw._fx_auto,
            _drawing_surface=fw._drawing_surface,
            _drawing_canvas=fw._drawing_canvas,
            skia_canvas=fw._scena_draw.skia_canvas,
            _was_using_post=fw._was_using_post,
        )
        fw.setup = lambda scena_canvas: None
        fw.update = lambda dt, scena_canvas: None
        fw.post_draw = lambda skia_canvas, scene_image=None: None
        fw._fx_auto = False
        fw._was_using_post = False
        fw._context = mock.Mock()
        self.assertFalse(
            fw._needs_scene_rt(),
            "leaked post state: run-loop tests require the direct FB path "
            "(GL context is mocked)",
        )
        surface = skia.Surface(int(fw.fb_width), int(fw.fb_height))
        fw._drawing_surface = surface
        fw._drawing_canvas = surface.getCanvas()
        fw._scena_draw.skia_canvas = fw._drawing_canvas
        self.frames = 1
        self._frame_i = 0

        def should_close(_window):
            self._frame_i += 1
            return self._frame_i > self.frames

        for target, attr, kwargs in (
            (orch.glfw, "window_should_close", {"side_effect": should_close}),
            (orch.glfw, "poll_events", {}),
            (orch.glfw, "swap_buffers", {}),
            (orch.glfw, "terminate", {}),
            (orch.GL, "glViewport", {}),
            (audio_mixer, "get_mixer", {"return_value": mock.Mock()}),
        ):
            p = mock.patch.object(target, attr, **kwargs)
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        fw = self.fw
        for label in (fw._system_label, fw._error_label):
            if label is not None and getattr(label, "is_alive", False):
                label.destroy()
        fw._system_label = fw._error_label = None
        fw._scena_draw.skia_canvas = self._saved.pop("skia_canvas")
        for k, v in self._saved.items():
            setattr(fw, k, v)
        canvas.reset_view()
        canvas.effects.clear()
        cleanup_global_event_system()

    def run_frames(self, n):
        self.frames = n
        self._frame_i = 0
        self.fw.run()


class TestCameraAfterUpdate(RunLoopTestCase):
    """F8: background + camera CTM are applied after ``update`` (no lag)."""

    def test_background_once_per_frame_after_update(self):
        events = []
        fw = self.fw
        fw.update = lambda dt: events.append("update")
        real_bg = fw._draw_background

        def bg(sk):
            events.append("bg")
            real_bg(sk)

        with mock.patch.object(fw, "_draw_background", side_effect=bg):
            self.run_frames(2)
        self.assertEqual(events, ["update", "bg", "update", "bg"])

    def test_scene_ctm_uses_this_frames_camera(self):
        fw = self.fw
        fw.update = lambda dt: canvas.pan_to(333, 222)
        seen = {}
        real_draw = fw._scena_draw.draw

        def draw(*args, **kwargs):
            seen["ctm"] = fw._drawing_canvas.getTotalMatrix()
            seen["bg_pan"] = fw._camera_sample_for_background().pan_x
            return real_draw(*args, **kwargs)

        with mock.patch.object(fw._scena_draw, "draw", side_effect=draw):
            self.run_frames(1)
        # Expected CTM: view transform with the camera as it is after update.
        probe = skia.Surface(int(fw.fb_width), int(fw.fb_height)).getCanvas()
        fw._apply_view_transform(probe)
        for got, want in zip(seen["ctm"].get9(), probe.getTotalMatrix().get9()):
            self.assertAlmostEqual(got, want, places=4)
        # And it is not the pre-update (identity-camera) CTM.
        canvas.reset_view()
        stale = skia.Surface(int(fw.fb_width), int(fw.fb_height)).getCanvas()
        fw._apply_view_transform(stale)
        self.assertNotEqual(seen["ctm"].get9(), stale.getTotalMatrix().get9())
        self.assertAlmostEqual(seen["bg_pan"], 333.0)

    def test_post_path_samples_once_after_update(self):
        fw = self.fw
        calls = []
        fw.update = lambda dt: calls.append("update")
        real_needs = fw._needs_scene_rt

        def needs():
            calls.append("sample")
            return real_needs()

        with mock.patch.object(fw, "_needs_scene_rt", side_effect=needs):
            self.run_frames(1)
        self.assertEqual(calls, ["update", "sample"])

    def test_dead_scene_blit_flag_is_gone(self):
        self.assertFalse(hasattr(self.fw, "_prefer_scene_blit"))


class TestPreDrawInsideBatch(RunLoopTestCase):
    """F9: pre-draw ticks run inside the frame batch; their writes reach
    ``@when`` at the next frame's flush, not eagerly per write."""

    def test_pre_draw_ticks_run_while_deferring(self):
        ss = get_scena_system()
        seen = []
        real = orch.tick_all_transients

        def tick():
            seen.append(ss.update_manager.deferring)
            real()

        with mock.patch.object(orch, "tick_all_transients", side_effect=tick):
            self.run_frames(1)
        self.assertEqual(seen, [True])
        self.assertFalse(ss.update_manager.deferring)  # batch closed after

    def test_pre_draw_write_fires_when_at_next_flush(self):
        a = Attribute(0.0)
        fired = []

        @when(lambda: a.value > 1)
        def on_high():
            fired.append(self._frame_i)

        real = orch.tick_all_transients
        state = {"frame": 0}

        def tick():
            state["frame"] += 1
            if state["frame"] == 1:
                a.value = 5  # e.g. an author on_done write
                fired.append("after-write")
            real()

        with mock.patch.object(orch, "tick_all_transients", side_effect=tick):
            self.run_frames(2)
        # Not fired synchronously inside the write; fired by frame 2's flush.
        self.assertEqual(fired, ["after-write", 2])


if __name__ == "__main__":
    unittest.main()
