"""System lifetime suite: destroy, churn, clone, park, modes — across subsystems.

Each scenario runs real frames (``ScenaFramework._simulate_frame`` + raster
draw) on an actor wired into every subsystem (``system_support.kitchen_sink``:
timers, tween, async mode, ``on_update``, sound, transient, stamp, Contrail,
method ``@when``, ``@collide_with`` / pair handler, ``@leave_playfield``,
``move_along``, ``@=`` in and out). Contracts checked (Scena Design § Construct
-to-place, Actors Design § Protections / Ownership, Reactive Design § Destroy):

* no author hook runs for a destroyed owner (``Probe.dead_calls``);
* no registry keeps a destroyed actor (``zombies``);
* once everything is destroyed, every registry is back to its baseline
  (``census``) and the actor is garbage (``assert_collected``);
* ``on_destroy`` runs once; an outbound ``@=`` dependent keeps its last value.

Findings this suite surfaced (fixed; regression tests live in the owning
``test_<area>.py``): S1 ``@leave_playfield`` method pinned its actor forever
(bound method as a WeakKeyDictionary value); S2 an idle scheduler never pumped
the offline mixer (cancelled voice stayed); S3 ``every()`` flood-site keys grew
per actor; S4 the scheduler's dense mode / ``on_update`` snapshots kept the
last destroyed owner alive.

    python -m unittest tests.test_sys_lifetime -v
"""
from __future__ import annotations

import gc
import os
import sys
import unittest
import weakref

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from system_support import (  # noqa: E402
    SystemTestCase, assert_collected, census, describe_new_live, diff_census,
    format_diff, roster_snapshot, kitchen_sink, quiet, system_world, tone, zombies,
)

from scena import (  # noqa: E402
    Circle, Entity, after, canvas, collide, group, leave_playfield, wait, when,
)
from scena.process import get_scheduler  # noqa: E402

# Bounded by design (flood-detector memory, swept past a threshold): not a
# per-actor holder.
CENSUS_IGNORE = ("sched.every_sites",)


def _destroy_rest(sink) -> None:
    with quiet():
        for o in (sink.partner, sink.source, sink.dependent, sink.track, sink.contrail):
            if o is not None and getattr(o, "is_alive", True):
                o.destroy()


class LifetimeChecks:
    """Assertions shared by the scenario tests (mixed into a TestCase)."""

    def check_after_death(self, w, sink, *, mirror_before=None):
        a = sink.actor
        self.assertFalse(a.is_alive, "actor survived its destroy context")
        w.step(10)
        dead = w.probe.dead_calls()
        self.assertEqual(dead, [], f"hooks ran for the destroyed actor: {dead}")
        z = w.zombies()
        self.assertEqual(z, [], "registries still hold the destroyed actor: "
                         + ", ".join(f"{h}: {type(o).__name__}" for h, o in z))
        self.assertEqual(w.probe.count("on_destroy"), 1)
        if sink.dependent is not None and mirror_before is not None:
            self.assertEqual(sink.dependent.mirror, mirror_before,
                             "outbound @= dependent lost its last value")

    def check_baseline(self, w, sink, base, what="actor", ignore=()):
        ref = weakref.ref(sink.actor)
        _destroy_rest(sink)
        sink.actor = sink.partner = sink.source = sink.dependent = None
        sink.track = sink.contrail = None
        sink.handles.clear()
        w.objects.clear()
        w.step(3)
        d = diff_census(base, census(), CENSUS_IGNORE + tuple(ignore))
        self.assertEqual(d, {}, "registries did not return to baseline: " + format_diff(d))
        assert_collected(self, ref, what)


# --------------------------------------------------------------------------
# 1. Destroy from every context
# --------------------------------------------------------------------------

def _ctx_update(w, s):
    a = s.actor
    w.on_update(lambda dt: a.destroy() if a.is_alive else None)


def _ctx_own_timer(w, s):
    s.actor.after(0.1, s.actor.destroy)


def _ctx_other_timer(w, s):
    other = w.track(Entity())
    a = s.actor
    other.after(0.1, lambda: a.destroy())


def _ctx_scene_timer(w, s):
    a = s.actor
    after(0.1, lambda: a.destroy())


def _ctx_own_on_update(w, s):
    s.actor.on_update = lambda e, dt: e.destroy()


def _ctx_own_mode(w, s):
    async def dying(e):
        await wait(0.05)
        e.destroy()
    s.actor.mode = dying


def _ctx_pair_handler(w, s):
    a, rock = s.actor, s.partner

    @collide(a, rock)
    def _boom(x, y, info=None):
        x.destroy()

    rock.move_to(a.center)


def _ctx_tag_handler_other_side(w, s):
    a, rock = s.actor, s.partner

    @collide("rock", "sink")
    def _boom(r, other, info=None):
        other.destroy()

    rock.move_to(a.center)


def _ctx_script_when(w, s):
    a = s.actor

    @when(lambda: a.hp <= 0)
    def _die():
        a.destroy()

    after(0.05, lambda: setattr(a, "hp", 0))


def _ctx_on_destroy_of_other(w, s):
    other = w.track(Entity())
    a = s.actor
    other.on_destroy = lambda: a.destroy()
    after(0.05, other.destroy)


def _ctx_transient_on_done(w, s):
    a = s.actor
    s.partner.flash(0.05, on_done=lambda: a.destroy())


def _ctx_cover_on_done(w, s):
    a = s.actor
    canvas.fade_out(0.05, on_done=lambda: a.destroy())


def _ctx_group_destroy(w, s):
    after(0.05, lambda: group["sink"].destroy())


def _ctx_while_parked(w, s):
    a = s.actor
    a.active = False
    after(0.1, lambda: a.destroy())


def _ctx_leave_playfield(w, s):
    @leave_playfield("sink")
    def _gone(item):
        item.destroy()

    a = s.actor
    after(0.05, lambda: a.move_to(5000, 5000))


CONTEXTS = {
    "update": (_ctx_update, {}),
    "own_timer": (_ctx_own_timer, {}),
    "other_timer": (_ctx_other_timer, {}),
    "scene_timer": (_ctx_scene_timer, {}),
    "own_on_update": (_ctx_own_on_update, {}),
    "own_mode": (_ctx_own_mode, {}),
    "pair_handler": (_ctx_pair_handler, {"path": False}),
    "tag_handler_other_side": (_ctx_tag_handler_other_side, {"path": False}),
    "script_when": (_ctx_script_when, {}),
    "on_destroy_of_other": (_ctx_on_destroy_of_other, {}),
    "transient_on_done": (_ctx_transient_on_done, {}),
    "cover_on_done": (_ctx_cover_on_done, {}),
    "group_destroy": (_ctx_group_destroy, {}),
    "while_parked": (_ctx_while_parked, {}),
    "leave_playfield": (_ctx_leave_playfield, {"path": False}),
}
# Contexts that write the watched source right before the death: the outbound
# dependent keeps the value of the source's FINAL state (``hp = 0`` → mirror
# ``hp + 1 = 1``), not the last value someone happened to read (D8).
EXPECT_MIRROR = {"script_when": 1}

# Script-level registrations a context installs on purpose (scene-scoped:
# they outlive the actor by design).
CONTEXT_IGNORE = {
    "leave_playfield": ("bounds.group_handlers",),
    "tag_handler_other_side": ("collision.pair_handlers",),
}


class TestDestroyFromEveryContext(LifetimeChecks, unittest.TestCase):
    """Wherever ``destroy()`` is called from, the teardown is the same."""

    def _run(self, kind, name):
        arm, kw = CONTEXTS[name]
        with system_world() as w:
            base = census()
            s = kitchen_sink(w, kind=kind, **kw)
            w.step(5)
            mirror = s.dependent.mirror
            arm(w, s)
            with quiet():
                w.step_until(lambda: not s.actor.is_alive, max_frames=120)
            w.on_update(None)
            self.check_after_death(w, s, mirror_before=EXPECT_MIRROR.get(name, mirror))
            self.check_baseline(w, s, base, what=f"{kind} destroyed from {name}",
                                ignore=CONTEXT_IGNORE.get(name, ()))

    def test_circle(self):
        for name in CONTEXTS:
            with self.subTest(context=name):
                self._run("circle", name)

    def test_sprite(self):
        for name in CONTEXTS:
            with self.subTest(context=name):
                self._run("sprite", name)

    def test_layer_delete_and_hard_clear(self):
        for how in ("delete", "clear_hard"):
            with self.subTest(how=how):
                with system_world() as w:
                    base = census()
                    layer = canvas.layers.create("sys_life")
                    s = kitchen_sink(w, layer="sys_life")
                    w.step(5)
                    mirror = s.dependent.mirror
                    with quiet():
                        if how == "delete":
                            layer.delete()
                        else:
                            layer.clear(hard=True)
                    self.check_after_death(w, s, mirror_before=mirror)
                    if how == "clear_hard":
                        canvas.layers["sys_life"].delete()
                    self.check_baseline(w, s, base)

    def test_partner_gets_exactly_one_exit(self):
        with system_world() as w:
            s = kitchen_sink(w, path=False)
            exits = []
            a, rock = s.actor, s.partner

            @collide(rock, a)
            def _touch(r, other, info=None):
                w.probe.hit("rock_enter", r)

            rock.on_collide_exit = lambda me, other, info=None: exits.append(other)
            rock.move_to(a.center)
            w.step(3)
            self.assertEqual(w.probe.count("rock_enter"), 1)
            with quiet():
                a.destroy()
            w.step(5)
            self.assertEqual(len(exits), 1, "the survivor must see one exit for a destroyed partner")


# --------------------------------------------------------------------------
# 2. Spawn / destroy churn
# --------------------------------------------------------------------------

class TestChurn(LifetimeChecks, unittest.TestCase):
    """A spawner feeding bullets that die by collision, leaving, or timeout."""

    FRAMES = 600
    SAMPLE = 60

    def test_registries_plateau_and_drain_to_baseline(self):
        from scena import Sparks, collide_with, leave_playfield as lp

        with system_world() as w:
            base = census()
            base_ids = roster_snapshot()
            spawned = []
            debris_n = [0]

            class Bullet(Circle):
                @collide_with("wall")
                def hit(self, other, info=None):
                    w.probe.hit("bullet_hit", self)
                    self.destroy()

                @lp
                def gone(self):
                    w.probe.hit("bullet_left", self)
                    self.destroy()

            wall = w.track(Circle(center=(150, 0), radius=20, group="wall"))
            snd = tone(0.05)
            state = {"on": True, "i": 0}

            def fire():
                if not state["on"]:
                    return
                state["i"] += 1
                i = state["i"]
                with quiet():
                    b = Bullet(center=(0, (i % 7) * 10 - 30), radius=3, group="bullet")
                b.every(0.1, w.probe.hook("bullet_every", b))
                heading = (400, (i % 5) * 40 - 80) if i % 3 else (150, 0)
                b.move_to(*heading, time=1.5)
                b.after(0.8 + (i % 4) * 0.2, b.destroy)
                b.play_sound(snd)
                b.flash(0.05)

                def spawn_debris(b=b):
                    if debris_n[0] < 40 and b.center.x > -50:
                        debris_n[0] += 1
                        fx = Sparks(center=(b.center.x, b.center.y), radius=6, rate=20)
                        fx.after(0.2, fx.destroy)
                b.on_destroy = spawn_debris
                spawned.append(weakref.ref(b))

            gun = w.track(Entity())
            gun.every(0.05, fire)
            samples = []
            for f in range(self.FRAMES):
                w.step(1, draw=(f % 10 == 0))
                if f and f % self.SAMPLE == 0:
                    samples.append(census())
            # Plateau: the second half of the run holds no more than the first.
            half = len(samples) // 2
            for key in ("graph.nodes", "sched.handles", "collision.colliders",
                        "registry.live", "registry.draw_live", "fx.spatial_fx",
                        "mixer.voices", "events.all"):
                early = max(s[key] for s in samples[:half])
                late = max(s[key] for s in samples[half:])
                self.assertLessEqual(late, early + 3, f"{key} keeps growing: {early} → {late}")
            self.assertEqual(w.probe.dead_calls(), [])
            self.assertGreater(len(spawned), 100)
            # Drain.
            state["on"] = False
            with quiet():
                gun.destroy()
            w.step(240, draw=False)
            self.assertEqual(w.zombies(), [])
            with quiet():
                wall.destroy()
            w.objects.clear()
            gun = wall = None
            w.step(3)
            d = diff_census(base, census(), CENSUS_IGNORE)
            self.assertEqual(d, {}, "churn left residue: " + format_diff(d)
                             + " | new: " + describe_new_live(base_ids))
            gc.collect()
            alive = [r for r in spawned if r() is not None]
            self.assertEqual(alive, [], f"{len(alive)} bullets never collected")


# --------------------------------------------------------------------------
# 3. Drop without destroy (GC backstop inside a running loop)
# --------------------------------------------------------------------------

class TestDropWithoutDestroy(SystemTestCase, unittest.TestCase):
    world_draw = False

    def test_off_registry_containers_leave_no_graph_residue(self):
        from scena import Attribute, Box, History, Point, Vec2

        w = self.w
        anchor = self.track(Circle(center=(0, 0), radius=4))
        w.step(2)
        base = census()
        for _ in range(200):
            v = Vec2(1, 2)
            at = Attribute(3.0)
            bx = Box(center=(0, 0), width=10, height=10)
            h = History(max_points=4)
            h.add(1)
            p = Point(0, 0)
            p["x"] @= (lambda: anchor.center.x + 1)
            _ = p.x + v.x + float(at.value) + bx.width
            del v, at, bx, h, p
            w.step(1)
        w.step(2)
        self.assertCensusEqual(base, ignore=CENSUS_IGNORE)
        # The anchor still moves and pulls cleanly (no edge into a dead node).
        anchor.move_by(5, 0)
        w.step(1)
        self.assertEqual(anchor.center.x, 5)


# --------------------------------------------------------------------------
# 4. Clone isolation
# --------------------------------------------------------------------------

class TestCloneIsolation(LifetimeChecks, unittest.TestCase):

    def test_clone_shares_no_work_with_its_original(self):
        for victim in ("original", "clone"):
            with self.subTest(destroy=victim):
                with system_world() as w:
                    base = census()
                    s = kitchen_sink(w, path=False, partner=False, links=False)
                    a = s.actor
                    with quiet():
                        b = w.track(a.clone(center=(50, 50)))
                    b.every(0.05, w.probe.hook("clone_every", b))
                    w.step(5)
                    sch = get_scheduler()
                    owned_a = set(sch._by_owner.get(id(a), {}))
                    owned_b = set(sch._by_owner.get(id(b), {}))
                    self.assertFalse(owned_a & owned_b, "clone shares handles")
                    owned_a = owned_b = None  # handles hold their owners
                    dead, keep = (a, b) if victim == "original" else (b, a)
                    with quiet():
                        dead.destroy()
                    before = w.probe.count("clone_every" if keep is b else "every")
                    w.step(30)
                    after_n = w.probe.count("clone_every" if keep is b else "every")
                    self.assertGreater(after_n, before, "survivor stopped working")
                    self.assertTrue(keep.is_alive)
                    self.assertEqual(w.probe.dead_calls(), [])
                    self.assertEqual(w.zombies(), [])
                    ref_a, ref_b = weakref.ref(a), weakref.ref(b)
                    with quiet():
                        keep.destroy()
                    a = b = dead = keep = None
                    s.actor = None
                    s.handles.clear()
                    _destroy_rest(s)
                    s.contrail = None
                    w.objects.clear()
                    w.step(3)
                    d = diff_census(base, census(), CENSUS_IGNORE)
                    self.assertEqual(d, {}, format_diff(d))
                    assert_collected(self, ref_a, "original")
                    assert_collected(self, ref_b, "clone")


# --------------------------------------------------------------------------
# 5. Park / resume across subsystems
# --------------------------------------------------------------------------

class TestParkAcrossSubsystems(SystemTestCase, unittest.TestCase):

    def test_park_freezes_process_time_and_collision_not_watches(self):
        w = self.w
        a = self.track(Circle(center=(0, 0), radius=10, group="p"))
        rock = self.track(Circle(center=(0, 0), radius=10, group="r"))
        a.hp = 5
        counts = {"enter": 0, "stay": 0, "exit": 0, "when": 0}

        @collide("r", "p")
        def _enter(r, other, info=None):
            counts["enter"] += 1

        rock.on_collide_stay = lambda *args: counts.__setitem__("stay", counts["stay"] + 1)
        rock.on_collide_exit = lambda *args: counts.__setitem__("exit", counts["exit"] + 1)

        @when(lambda: a.hp <= 0)
        def _low():
            counts["when"] += 1

        h = a.tween(a["radius"], 30, time=1.0)
        w.step(10)
        self.assertEqual(counts["enter"], 1)
        r_before = a.radius
        a.active = False
        w.step(1)
        self.assertEqual(counts["exit"], 1, "parking must end the contact")
        stays = counts["stay"]
        a.hp = 0
        w.step(30)
        self.assertEqual(counts["stay"], stays, "a parked body must not collide")
        self.assertEqual(a.radius, r_before, "a parked actor's tween must freeze")
        self.assertEqual(counts["when"], 1, "@when still polls a parked source")
        a.active = True
        w.step(1)
        self.assertEqual(counts["enter"], 2, "resuming re-enters the overlap")
        w.seconds(1.0)
        self.assertTrue(h.done)
        self.assertAlmostEqual(a.radius, 30)

    def test_destroy_while_parked_is_clean(self):
        w = self.w
        base = census()
        s = kitchen_sink(w)
        w.step(5)
        s.actor.active = False
        w.step(5)
        with quiet():
            s.actor.destroy()
        LifetimeChecks.check_after_death(self, w, s)
        LifetimeChecks.check_baseline(self, w, s, base)


# --------------------------------------------------------------------------
# 6. Modes
# --------------------------------------------------------------------------

class TestModes(SystemTestCase, unittest.TestCase):
    world_draw = False

    def test_mode_scoped_work_dies_entity_scoped_survives(self):
        from scena import every, exit_mode, play_sound

        w = self.w
        a = self.track(Circle())
        log = []
        snd = tone(10)

        def calm(e):
            pass

        def angry(e):
            every(0.05, lambda: log.append("mode_every"))
            after(0.5, lambda: log.append("mode_after"))
            play_sound(snd, loops="forever")  # a finite one would ring out
            e.every(0.05, lambda: log.append("entity_every"))

        @exit_mode(angry)
        def _leave(e):
            log.append("exit")

        a.mode = angry
        w.step(10)
        sch = get_scheduler()
        self.assertEqual(len(sch._sound), 1)
        a.mode = calm
        self.assertEqual(log.count("exit"), 1)
        self.assertEqual(len(sch._sound), 0, "mode-scoped sound must stop on leave")
        n_mode = log.count("mode_every")
        n_ent = log.count("entity_every")
        w.step(40)
        self.assertEqual(log.count("mode_every"), n_mode)
        self.assertNotIn("mode_after", log)
        self.assertGreater(log.count("entity_every"), n_ent)
        self.assertEqual(log.count("exit"), 1)

    def test_async_mode_gets_cancelled_on_leave(self):
        from scena import Cancelled

        w = self.w
        a = self.track(Circle())
        seen = []

        async def waiting(e):
            try:
                await wait(10)
            except Cancelled:
                seen.append("cancelled")
                raise

        a.mode = waiting
        w.step(3)
        a.mode = None
        w.step(3)
        self.assertEqual(seen, ["cancelled"])

    def test_mode_ping_pong_does_not_accumulate(self):
        from scena import every

        w = self.w
        a = self.track(Circle())

        def one(e):
            every(0.05, lambda: None, name="beat")
            after(0.02, lambda: setattr(e, "mode", two))

        def two(e):
            every(0.05, lambda: None, name="beat")
            after(0.02, lambda: setattr(e, "mode", one))

        a.mode = one
        w.step(30)
        early = census()
        w.step(600)
        d = diff_census(early, census(), CENSUS_IGNORE)
        self.assertEqual(d, {}, "mode switching accumulates: " + format_diff(d))


# --------------------------------------------------------------------------
# 7. Interned caches
# --------------------------------------------------------------------------

class TestInternedCaches(SystemTestCase, unittest.TestCase):

    def test_same_look_reassigned_does_not_grow_caches(self):
        from scena import Neon
        import scena.recipes as recipes
        import scena.visuals as visuals
        import scena.filters as filters

        caches = [(m, n) for m in (recipes, visuals, filters)
                  for n in dir(m) if n.endswith("_CACHE") and isinstance(getattr(m, n), dict)]
        self.assertTrue(caches, "no intern caches found — update this test")
        w = self.w
        c = self.track(Circle(center=(0, 0), radius=10))
        c.visual = Neon("cyan")
        c.glow = "red"
        w.step(2)
        sizes = {f"{m.__name__}.{n}": len(getattr(m, n)) for m, n in caches}
        for _ in range(300):
            c.visual = Neon("cyan")
            c.glow = "red"
        w.step(2)
        after_sizes = {f"{m.__name__}.{n}": len(getattr(m, n)) for m, n in caches}
        self.assertEqual(sizes, after_sizes)


if __name__ == "__main__":
    unittest.main()
