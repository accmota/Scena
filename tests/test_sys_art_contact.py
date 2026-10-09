"""Art change × trigger phase × contact frame: a hitbox whose ``active``
follows the cell on show enters collision on the frame the strike cell is
drawn, whichever author hook started the clip.

Interaction campaign, class 12 (design/Testing Design.md, "Interaction
campaign"). ``test_hitbox_round2.TestLinkedActiveFrames`` starts the clip
from ``update`` and from an ``on_update``; here the clip starts from every
author hook (update, a timer, a tween ``on_done``, another pair's collision
handler, a ``@when``, a transient ``on_done``) with a flash and a stamp alive
on the sprite, and the oracle has no model: the enter edge fires in the
first frame whose drawn cell is a strike cell, and the exit edge in the first
frame after the last one (both read at draw time of the same frame).

    python -m unittest tests.test_sys_art_contact -v
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from typing import Callable, Dict, List
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from system_support import SystemTestCase, quiet  # noqa: E402
from test_sprite import _write_rect_png  # noqa: E402

from scena import Circle, Entity, Sheet, Sprite, after, clock, collide, collide_exit, tween, when  # noqa: E402
from scena.hitbox import _LINKED_PARTS  # noqa: E402

N = 5           # the frame the trigger runs in
STRIKE = (2, 3)


def trig_update(tc, fire):
    tc.w.on_update(lambda dt: fire() if clock.frame == N else None)


def trig_timer(tc, fire):
    after((N - 1) / 60.0 + 1e-6, fire)


def trig_tween_on_done(tc, fire):
    e = tc.track(Entity())
    e.x = 0.0
    tween(e["x"], 1.0, time=(N - 1) / 60.0 + 1e-6, on_done=fire)


def trig_collision_handler(tc, fire):
    a = tc.track(Circle(center=(400, 400), radius=5, group="ta"))
    b = tc.track(Circle(center=(400, 400), radius=5, group="tb"))

    @collide("ta", "tb")
    def _hit(x, y, info=None):
        fire()
    tc.w.on_update(lambda dt: b.move_to(400, 400) if clock.frame == N else None)
    b.move_to(700, 400)


def trig_when(tc, fire):
    e = tc.track(Entity())
    e.go = False

    @when(lambda: e.go)
    def _go():
        fire()
    tc.w.on_update(lambda dt: setattr(e, "go", True) if clock.frame == N else None)


def trig_flash_on_done(tc, fire):
    c = tc.track(Circle(center=(500, 500), radius=5))
    # 0.06 s started at N-4 ends in frame N's pre-draw tick (test_sys_frame_order)
    tc.w.on_update(lambda dt: c.flash(0.06, on_done=fire) if clock.frame == N - 4 else None)


TRIGGERS: Dict[str, Callable] = {
    "update": trig_update,
    "timer": trig_timer,
    "tween on_done": trig_tween_on_done,
    "collision handler": trig_collision_handler,
    "@when": trig_when,
    "flash on_done": trig_flash_on_done,
}


class TestArtChangeContact(SystemTestCase, unittest.TestCase):
    world_draw = True

    def setUp(self):
        super().setUp()
        self.addCleanup(_LINKED_PARTS.clear)
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        path = os.path.join(self._dir.name, "fighter.png")
        _write_rect_png(path, 32 * 6, 32)
        self.sheet = Sheet(path, cols=6, fps=60)
        self.sheet.clip("idle", [0], fps=60)
        self.sheet.clip("punch", [1, 2, 3, 4], fps=60)
        with quiet():
            self.hero = self.track(Sprite(self.sheet, frame=0, width=32, height=32,
                                          center=(0, 0), group="hero", hitbox_shape="rect"))
        self.fist = self.hero.add_hitbox(group="attack", px_rect=(0, 0, 32, 32))
        self.fist["active"] @= lambda: self.hero.showing(STRIKE)
        self.dummy = self.track(Circle(center=(0, 0), radius=3, group="dummy"))
        self.hero.flash(10.0)            # a transient alive across the change
        self.hero.glow = "red"           # a stamp alive across the change
        self.log: List[tuple] = []
        self.shown: Dict[int, bool] = {}

        @collide("attack", "dummy")
        def _hit(a, b, info):
            self.log.append(("enter", clock.frame))

        @collide_exit("attack", "dummy")
        def _gone(a, b, info):
            self.log.append(("exit", clock.frame))

        fw = self.w.fw
        real_draw = fw._draw_frame

        def draw():
            self.shown[clock.frame] = bool(self.hero.showing(STRIKE))
            real_draw()
        p = mock.patch.object(fw, "_draw_frame", side_effect=draw)
        p.start()
        self.addCleanup(p.stop)

    def _cell(self, trigger: str) -> None:
        fired = []

        def fire():
            if not fired:
                fired.append(clock.frame)
                self.hero.play("punch", loops=1, next="idle")
        TRIGGERS[trigger](self, fire)
        self.w.step(N + 8)
        self.assertEqual(fired, [N], f"{trigger}: the clip started at {fired}, want frame {N}")
        frames = sorted(self.shown)
        strike = [f for f in frames if self.shown[f]]
        self.assertTrue(strike, f"{trigger}: the strike cells never showed")
        first, last = strike[0], strike[-1]
        want = [("enter", first), ("exit", last + 1)]
        self.assertEqual(self.log, want,
                         f"{trigger}: contact {self.log}, strike cells drawn in frames {strike}")
        self.assertTrue(self.hero.is_alive and self.hero.glow is not None)



for _name in TRIGGERS:
    setattr(TestArtChangeContact,
            "test_" + "".join(ch if ch.isalnum() else "_" for ch in _name),
            (lambda n: lambda self: self._cell(n))(_name))


if __name__ == "__main__":
    unittest.main()
