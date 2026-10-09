"""Stateful system test: random game sessions over real frames (Hypothesis).

A ``RuleBasedStateMachine`` plays an author: spawn actors wired into several
subsystems (timers, tween, mode, ``on_update``, sound, transient, method
``@when``, ``@collide_with`` / ``@collide_with_exit``, ``@leave_playfield``),
destroy them now or from inside another subsystem's callback (timer, ``@when``,
collision, another actor's ``on_destroy``, transient ``on_done``), park /
resume, clone, change mode, ``cancel_process()``, link ink with ``@=``, toggle
``collidable``, move into overlap or off the playfield, destroy a group — and
step frames with ``dt`` in {0, 1/60, 1/30, 0.3}.

M4 adds (Testing Design — World machine): kinds ``sprite`` (with a hitbox
part) and ``text``; custom layers (create / delete with and without
``destroy_shapes`` / soft and hard clear); ``layer =`` on live and dead actors;
an ``on_destroy`` that spawns onto its own layer (also during a layer drain);
``@=`` links whose outcome is checked, not swallowed.

Invariants after every step (Actors Design § Protections, Collision Design §
Handlers, Reactive Design § Destroy, Canvas Design):

* no author hook runs for a destroyed owner (``Probe.dead_calls``);
* no registry holds a destroyed actor (``zombies``);
* the collision index holds exactly the enrolled actors that are alive, active
  and collidable (a live, active, collidable ``HypActor`` is always enrolled);
* hitbox parts die with their host;
* draw lists and groups match the shared registry model (``hyp_models``): one
  layer per live actor, painter order, join order, no destroyed actor anywhere;
* a live link equals a fresh recompute; the dependent of a destroyed source
  keeps its last value;
* the frame batch is closed and the dirty stack empty between frames;
* ``on_destroy`` runs at most once per actor, exactly once once it is dead.

Teardown: destroy everything, step, and every registry is back to the
baseline census; every actor is garbage.

    python -m unittest tests.test_sys_hyp_world -v
    SCENA_HYPOTHESIS_PROFILE=deep python -m unittest tests.test_sys_hyp_world
"""
from __future__ import annotations

import gc
import os
import sys
import unittest
import weakref

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis import note, strategies as hst  # noqa: E402
from hypothesis.stateful import (  # noqa: E402
    Bundle, RuleBasedStateMachine, invariant, precondition, rule,
)

from hyp_models import RegistryModel  # noqa: E402
from system_support import (  # noqa: E402
    SystemWorld, census, describe_new_live, diff_census, format_diff, full_collect,
    roster_snapshot, quiet, tone,
)

from scena import (  # noqa: E402
    Circle, Entity, Rect, Sparks, Sprite, Text, after, canvas, collide, collide_with,
    collide_with_exit, group, leave_playfield, wait, when,
)
from scena import hitbox as _hitbox  # noqa: E402
from scena.collision import get_collision_system  # noqa: E402
from scena.process import get_scheduler  # noqa: E402
from scena.state import DestroyedError, get_scena_system  # noqa: E402

TAGS = ["hs_a", "hs_b"]
LAYERS = ["wl_a", "wl_b"]   # custom layers this machine creates / deletes
DTS = [0.0, 1 / 60, 1 / 30, 0.3]
CENSUS_IGNORE = ("sched.every_sites",)

# The probe of the running machine (class hooks are defined once, at import).
_PROBE = [None]

# Reach counters for the M4 paths (vacuity guard: TestWorldMachineReach).
import collections  # noqa: E402
HITS: "collections.Counter[str]" = collections.Counter()


def _rec(tag, owner):
    probe = _PROBE[0]
    if probe is not None:
        probe.hit(tag, owner)


class HypActor(Circle):
    """A Circle with every class-level hook the machine can trigger."""

    @when(lambda self: getattr(self, "hp", 5) <= 0)
    def low(self):
        _rec("when", self)

    @collide_with("hs_b")
    def hit(self, other, info=None):
        _rec("collide", self)

    @collide_with_exit("hs_b")
    def unhit(self, other, info=None):
        _rec("collide_exit", self)

    @leave_playfield
    def left(self):
        _rec("leave", self)


KINDS = ["hyp", "circle", "rect", "entity", "sparks", "sprite", "text"]
GRAPHIC = ("hyp", "circle", "rect", "sprite", "text")   # placed on a layer
ATTACH = ["after", "every", "tween", "mode", "on_update", "sound", "flash", "on_destroy"]


async def _roam(e):
    while True:
        await wait(0.05)
        _rec("mode", e)


def _calm(e):
    _rec("mode_enter", e)


class WorldMachine(RuleBasedStateMachine):
    actors = Bundle("actors")

    def __init__(self):
        super().__init__()
        self.w = SystemWorld(draw=False)
        self.probe = self.w.probe
        _PROBE[0] = self.probe
        self.base = census()
        self.base_ids = roster_snapshot()
        self.refs = []
        # The bundle carries int handles, not actors: Hypothesis keeps bundle
        # values alive until the run ends, which would hide leaks.
        self.pool = {}
        self.on_destroy_hooked = {}  # id(actor) -> weakref (hook installed)
        self.snd = tone(0.4)
        self.sm = RegistryModel(TAGS)       # placement / membership of tracked actors
        self.kind_of = {}                # key -> kind
        self.custom_layers = set()
        self.links = {}                  # dst key -> [src key, frozen value or None]
        self.tearing_down = False

    # -- helpers ------------------------------------------------------------
    def _spawn(self, kind, tag, xy, attach):
        with quiet():
            if kind == "hyp":
                a = HypActor(center=xy, radius=6, group=tag)
            elif kind == "circle":
                a = Circle(center=xy, radius=6, group=tag)
            elif kind == "rect":
                a = Rect(center=xy, width=10, height=6, group=tag)
            elif kind == "entity":
                a = Entity(group=tag)
            elif kind == "sprite":
                a = Sprite(center=xy, group=tag)
                part = a.add_hitbox()   # a part: must die with the host
                # A linked active (round 2): must leave _LINKED_PARTS with it.
                part["active"] @= lambda host=a: host.showing(0)
            elif kind == "text":
                a = Text("w", center=xy, group=tag)
            else:
                a = Sparks(center=xy, radius=8, rate=10)
        self.w.track(a)
        self.refs.append(weakref.ref(a))
        a.hp = 5
        hook = self.probe.hook
        graphic = kind in ("hyp", "circle", "rect")   # tween / flash targets
        for what in attach:
            if what == "after":
                a.after(0.1, hook("after", a))
            elif what == "every":
                a.every(0.05, hook("every", a))
            elif what == "tween" and graphic:
                a.tween(a["angle"] if kind != "rect" else a["width"], 20, time=0.3,
                        loops="forever", yoyo=True)
            elif what == "mode":
                a.mode = _roam
            elif what == "on_update":
                a.on_update = lambda e, dt: _rec("on_update", e)
            elif what == "sound":
                a.play_sound(self.snd, on_done=hook("sound_done", a))
            elif what == "flash" and graphic:
                a.flash(0.1, on_done=hook("flash_done", a))
            elif what == "on_destroy":
                a.on_destroy = hook("on_destroy", a)
                self.on_destroy_hooked[id(a)] = weakref.ref(a)
        key = len(self.refs) - 1
        self.pool[key] = a
        self.kind_of[key] = kind
        if kind in GRAPHIC:
            self.sm.track(a, kind, "default", [tag])
        elif kind == "entity":
            self.sm.track(a, kind, None, [tag])
        note(f"spawn {kind}#{key} tag={tag} attach={sorted(attach)}")
        return key

    def _adopt(self, obj, kind, layer, groups):
        """Track an actor the machine did not spawn through ``_spawn``."""
        self.w.track(obj)
        key = len(self.refs)
        self.refs.append(weakref.ref(obj))
        self.pool[key] = obj
        self.kind_of[key] = kind
        self.sm.track(obj, kind, layer, groups)
        obj.hp = 5   # clone does not copy ink; every actor is a link source
        return key

    def get(self, key):
        return self.pool[key]

    # -- rules --------------------------------------------------------------
    @precondition(lambda self: sum(1 for r in self.refs if r() is not None and r().is_alive) < 12)
    @rule(target=actors, kind=hst.sampled_from(KINDS), tag=hst.sampled_from(TAGS),
          xy=hst.tuples(hst.integers(-60, 60), hst.integers(-60, 60)),
          attach=hst.sets(hst.sampled_from(ATTACH), max_size=5))
    def spawn(self, kind, tag, xy, attach):
        return self._spawn(kind, tag, (float(xy[0]), float(xy[1])), attach)

    @rule(a=actors)
    def destroy_now(self, a):
        note(f"destroy #{a}")
        a = self.get(a)
        with quiet():
            a.destroy()

    @rule(a=actors, ctx=hst.sampled_from(["timer", "scene_timer", "when", "on_destroy_of",
                                           "collision", "flash_done", "on_update"]),
          other=actors)
    def destroy_later(self, a, ctx, other):
        note(f"destroy #{a} from {ctx} (other #{other})")
        a, other = self.get(a), self.get(other)
        if not a.is_alive:
            return
        ref = weakref.ref(a)

        def kill():
            x = ref()
            if x is not None and x.is_alive:
                x.destroy()

        with quiet():
            if ctx == "timer":
                a.after(0.05, kill)
            elif ctx == "scene_timer":
                after(0.05, kill)
            elif ctx == "when":
                a.hp = 5

                @when(lambda: ref() is not None and ref().hp <= 0)
                def _die():
                    kill()

                a.after(0.02, lambda: setattr(ref(), "hp", 0))
            elif ctx == "on_destroy_of":
                if other is a or not other.is_alive:
                    return
                prev = other.on_destroy

                def chained(*args, _prev=prev):
                    if callable(_prev):
                        _prev()
                    kill()
                other.on_destroy = chained
                other.after(0.05, other.destroy)
            elif ctx == "collision":
                if other is a or not other.is_alive or not hasattr(other, "center") \
                        or not hasattr(a, "center") or isinstance(a, Sparks) \
                        or isinstance(other, Sparks):
                    return

                @collide(a, other)
                def _boom(x, y, info=None):
                    kill()

                other.move_to(a.center)
            elif ctx == "flash_done":
                if not hasattr(a, "flash"):
                    return
                a.flash(0.06, on_done=kill)
            elif ctx == "on_update":
                a.on_update = lambda e, dt: kill()

    @rule(a=actors, on=hst.booleans())
    def park(self, a, on):
        a = self.get(a)
        with quiet():
            if a.is_alive:
                a.active = on

    @rule(target=actors, a=actors)
    def clone(self, a):
        key_a = a
        a = self.get(a)
        if not a.is_alive or not hasattr(a, "clone") or isinstance(a, Sparks):
            return key_a
        with quiet():
            b = a.clone()
        # Clone copies art / groups, not placement: class-default layer (a
        # world Text / shape / sprite lands on "default"); Entity stays unplaced.
        kind = self.kind_of[key_a]
        layer = "default" if kind in GRAPHIC else None
        groups = list(self.sm[a].groups) if a in self.sm else []
        key = self._adopt(b, kind, layer, groups)
        note(f"clone #{key_a} -> #{key}")
        return key

    @rule(src=actors, dst=actors, how=hst.sampled_from(["now", "group", "frame"]))
    def link_then_kill_source(self, src, dst, how):
        """Install a link, then destroy its source (``links_consistent``
        freezes the value; the dependent must keep it); a second ``@=`` from
        the dead source is refused (W2). A dead or repeated pick is replaced
        by a fresh actor: most bundle entries are dead (``destroy_group``
        halves the world), so random picks alone leave this path marginal
        (Testing Design — World machine, reach guard)."""
        if not self.get(src).is_alive:
            src = self._spawn("circle", TAGS[0], (0.0, 0.0), set())
        if src == dst or not self.get(dst).is_alive:
            dst = self._spawn("circle", TAGS[1], (0.0, 0.0), set())
        s_obj = self.get(src)
        self.link(src, dst)
        if not s_obj.is_alive:
            return
        with quiet():
            if how == "now":
                s_obj.destroy()
            elif how == "group" and s_obj.group:
                group[sorted(s_obj.group)[0]].destroy()   # .group is a set
            else:
                s_obj.after(0.0, s_obj.destroy)
                self.w.step(2, dt=1 / 60)
        if not s_obj.is_alive:
            self.link(src, dst)   # dead source: must raise DestroyedError

    @rule(a=actors, which=hst.sampled_from(["roam", "calm", None]))
    def set_mode(self, a, which):
        a = self.get(a)
        if not a.is_alive:
            return
        with quiet():
            a.mode = {"roam": _roam, "calm": _calm, None: None}[which]

    @rule(a=actors, verb=hst.sampled_from(["after", "every", "flash", "sound", "mode",
                                            "on_update", "tween", "layer", "tag"]))
    def poke(self, a, verb):
        """A verb on any actor — dead ones included (use after destroy). A
        dead actor may refuse with ``DestroyedError``; it must never run the
        hook or re-register (``no_dead_calls`` / ``no_zombies``)."""
        from scena.state import DestroyedError
        a = self.get(a)
        hook = self.probe.hook
        with quiet():
            try:
                if verb == "after":
                    a.after(0.02, hook("poke_after", a))
                elif verb == "every":
                    a.every(0.02, hook("poke_every", a))
                elif verb == "flash" and hasattr(a, "flash"):
                    a.flash(0.06, on_done=hook("poke_flash", a))
                elif verb == "sound":
                    a.play_sound(self.snd, on_done=hook("poke_sound", a))
                elif verb == "mode":
                    a.mode = _calm
                elif verb == "on_update":
                    a.on_update = lambda e, dt: _rec("poke_update", e)
                elif verb == "tween" and hasattr(a, "flash"):
                    a.tween(a["angle"] if not isinstance(a, Rect) else a["width"], 5,
                            time=0.1, on_done=hook("poke_tween", a))
                elif verb == "layer" and hasattr(a, "flash"):
                    a.layer = "top"
                    if a in self.sm:
                        self.sm.move(a, "top")
                elif verb == "tag":
                    a.tag("hs_b")
                    if a in self.sm:
                        self.sm.join(a, "hs_b")
            except DestroyedError:
                assert not a.is_alive, "DestroyedError on a live actor"
            except Exception as exc:
                if a.is_alive:
                    raise
                raise AssertionError(f"{verb} on a dead actor raised {exc!r}, "
                                     f"not DestroyedError") from exc

    @rule(a=actors)
    def cancel_process(self, a):
        a = self.get(a)
        if a.is_alive:
            a.cancel_process()

    @rule(src=actors, dst=actors)
    def link(self, src, dst):
        """``dst["mirror"] @= src.hp + 1`` (Reactive Design): a dead source or a
        dead target raises ``DestroyedError`` (W2) and installs nothing;
        otherwise the link installs and ``links_consistent`` checks it."""
        key_src, key_dst = src, dst
        src, dst = self.get(src), self.get(dst)
        if src is dst:
            return
        try:
            with quiet():
                dst["mirror"] @= (lambda s=src: s.hp + 1)
        except DestroyedError:
            assert not (src.is_alive and dst.is_alive), \
                f"@= raised DestroyedError with both #{key_src} and #{key_dst} alive"
            HITS["link_refused_dead"] += 1
            return
        assert src.is_alive and dst.is_alive, (
            f"@= accepted with a destroyed {'source' if not src.is_alive else 'target'}")
        self.links[key_dst] = [key_src, None]
        HITS["link_installed"] += 1

    @rule(a=actors, on=hst.booleans())
    def collidable(self, a, on):
        a = self.get(a)
        if a.is_alive and hasattr(a, "collidable") and not isinstance(a, Sparks):
            with quiet():
                a.collidable = on

    @rule(a=actors, where=hst.sampled_from(["origin", "near", "far"]))
    def move(self, a, where):
        a = self.get(a)
        if not a.is_alive or not hasattr(a, "move_to") or isinstance(a, Sparks):
            return
        xy = {"origin": (0.0, 0.0), "near": (5.0, 3.0), "far": (5000.0, 5000.0)}[where]
        with quiet():
            try:
                a.move_to(*xy)
            except Exception:
                pass  # a persistent driver may own the pose (documented raise)

    @rule(a=actors, dest=hst.sampled_from(["default", "top", *LAYERS]))
    def set_layer_rule(self, a, dest):
        self.set_layer(a, dest)

    def set_layer(self, a, dest):
        """``layer =`` on live and dead actors; a missing custom layer raises."""
        key = a
        a = self.get(a)
        if self.kind_of.get(key) not in GRAPHIC:
            return
        try:
            with quiet():
                a.layer = dest
        except DestroyedError:
            assert not a.is_alive, "DestroyedError on a live actor"
            return
        except ValueError:
            assert dest in LAYERS and dest not in self.custom_layers, \
                f"layer = {dest!r} refused with the layer present"
            return
        assert a.is_alive, f"layer = {dest!r} on a destroyed actor accepted"
        assert dest not in LAYERS or dest in self.custom_layers, \
            f"layer = {dest!r} (missing) accepted"
        self.sm.move(a, dest)
        HITS["layer_to_custom" if dest in LAYERS else "layer_set"] += 1

    @precondition(lambda self: self.custom_layers)
    @rule(a=actors, data=hst.data())
    def move_to_custom_layer(self, a, data):
        """``layer =`` into a layer that exists (drains need occupants)."""
        name = data.draw(hst.sampled_from(sorted(self.custom_layers)), label="layer")
        self.set_layer(a, name)

    @rule(name=hst.sampled_from(LAYERS), z=hst.integers(-5, 50))
    def create_layer(self, name, z):
        if name in self.custom_layers:
            return
        canvas.layers.create(name, z=z)
        self.custom_layers.add(name)

    @precondition(lambda self: self.custom_layers)
    @rule(data=hst.data(), destroy_shapes=hst.booleans())
    def delete_layer(self, data, destroy_shapes):
        name = data.draw(hst.sampled_from(sorted(self.custom_layers)))
        on_it = list(self.sm.order.get(name, []))
        with quiet():
            canvas.layers[name].delete(destroy_shapes=destroy_shapes)
        self.custom_layers.discard(name)
        if destroy_shapes:
            # A drain: on_destroy spawns onto the drained layer die too.
            HITS["drain_nonempty" if on_it else "drain_empty"] += 1
            self.sm.forget_dead(lambda o: not o.is_alive)
            left = [o for o in self.sm.order.get(name, []) if o.is_alive]
            assert not left, f"delete(destroy_shapes=True) left {left} alive on {name!r}"
        else:
            for obj in on_it:
                self.sm.unplace(obj)
        self.sm.order.pop(name, None)

    @precondition(lambda self: self.custom_layers)
    @rule(data=hst.data(), hard=hst.booleans())
    def clear_layer(self, data, hard):
        name = data.draw(hst.sampled_from(sorted(self.custom_layers)))
        on_it = list(self.sm.order.get(name, []))
        with quiet():
            canvas.layers[name].clear(hard=hard)
        if hard:
            HITS["drain_nonempty" if on_it else "drain_empty"] += 1
            self.sm.forget_dead(lambda o: not o.is_alive)
            left = [o for o in self.sm.order.get(name, []) if o.is_alive]
            assert not left, f"clear(hard=True) left {left} alive on {name!r}"
        else:
            for obj in on_it:
                self.sm.unplace(obj)

    @rule(a=actors, how=hst.sampled_from(["delete", "clear"]), arm=hst.booleans())
    def drain_occupied_layer(self, a, how, arm):
        """A layer drain with an occupant — optionally one whose ``on_destroy``
        spawns back onto the drained layer (the drain must reach a fixed
        point). Random rule order almost never lines this up by itself."""
        key = a
        obj = self.get(a)
        if not obj.is_alive or self.kind_of.get(key) not in GRAPHIC:
            key = self._spawn("circle", TAGS[0], (0.0, 0.0), set())   # a fresh occupant
        name = LAYERS[0]
        if name not in self.custom_layers:
            self.create_layer(name, 5)
        self.set_layer(key, name)
        if arm:
            self.arm_spawner(key)
        class _Pick:   # the drain rules draw the layer name
            def draw(self_, strat, label=None):
                return name
        if how == "delete":
            self.delete_layer(_Pick(), True)
        else:
            self.clear_layer(_Pick(), True)

    @rule(a=actors)
    def arm_spawner(self, a):
        """``on_destroy`` spawns a Circle onto the dying actor's own layer."""
        key = a
        a = self.get(a)
        if not a.is_alive or self.kind_of.get(key) not in GRAPHIC:
            return
        if self.sm[a].spawn_on_destroy:
            return
        self.sm[a].spawn_on_destroy = True
        ref = weakref.ref(a)
        prev = a.on_destroy

        def spawner(*args, _prev=prev):
            if callable(_prev):
                _prev()
            me = ref()
            if self.tearing_down or me is None or me.layer is None:
                return
            with quiet():
                child = Circle(center=(1, 1), radius=2, layer=me.layer)
            self._adopt(child, "circle", me.layer, [])
            HITS["spawned_on_destroy"] += 1
            if me.layer in LAYERS:
                HITS["spawned_onto_custom_layer"] += 1
            note(f"on_destroy spawned onto {me.layer!r}")

        with quiet():
            a.on_destroy = spawner

    @rule(tag=hst.sampled_from(TAGS))
    def destroy_group(self, tag):
        with quiet():
            group[tag].destroy()

    @rule(n=hst.integers(1, 6), dt=hst.sampled_from(DTS))
    def step(self, n, dt):
        with quiet():
            self.w.step(n, dt=dt)

    @rule()
    def draw_one(self):
        with quiet():
            self.w.step(1, draw=True)

    # -- invariants ---------------------------------------------------------
    @invariant()
    def no_dead_calls(self):
        dead = self.probe.dead_calls()
        assert dead == [], f"hooks ran for a destroyed owner: {dead}"

    @invariant()
    def no_zombies(self):
        z = self.w.zombies()
        assert z == [], "registries hold destroyed actors: " + ", ".join(
            f"{h}: {type(o).__name__}" for h, o in z)

    @invariant()
    def parked_and_dead_are_out_of_collision_tags(self):
        col = get_collision_system()
        for tag, lst in col._tag_colliders.items():
            for c in lst:
                ident = c._identity
                if ident is None:
                    continue
                if not getattr(ident, "is_alive", True):
                    raise AssertionError(f"dead {ident!r} in collision tag {tag}")
                if getattr(ident, "active", True) is False:
                    raise AssertionError(f"parked {ident!r} in collision tag {tag}")

    @invariant()
    def collision_index_matches_state(self):
        """In ``_colliders`` ⇔ alive ∧ active ∧ collidable ∧ enrolled. A
        ``HypActor`` is always enrolled (class ``@collide_with``)."""
        col = get_collision_system()
        enrolled = set()
        for c in col._colliders:
            ident = c._identity
            if ident is None:
                continue
            enrolled.add(id(ident))
            assert getattr(ident, "is_alive", True), f"dead {ident!r} in _colliders"
            assert getattr(ident, "active", True) is not False, f"parked {ident!r} in _colliders"
            assert getattr(ident, "collidable", True) is not False, \
                f"collidable=False {ident!r} in _colliders"
        for key, a in self.pool.items():
            if (self.kind_of.get(key) == "hyp" and a.is_alive and a.active
                    and a.collidable):
                assert id(a) in enrolled, f"live, active, collidable HypActor #{key} not enrolled"

    @invariant()
    def linked_hitbox_parts_are_alive(self):
        for part in list(_hitbox._LINKED_PARTS):
            assert part.is_alive, f"dead hitbox part {part!r} still linked"

    @invariant()
    def hitbox_parts_die_with_their_host(self):
        for part in list(_hitbox._LIVE_PARTS):
            if not part.is_alive:
                continue
            host = part.host
            assert host is not None and host.is_alive, f"live hitbox part {part!r} of a dead host"

    @invariant()
    def draw_lists_and_groups_match_model(self):
        from system_support import registry
        self.sm.forget_dead(lambda o: not o.is_alive)
        self.sm.check_draw_lists(registry())
        with quiet():   # group[g] warns for a name nobody joined yet
            self.sm.check_groups(TAGS, lambda g: list(group[g]))

    @invariant()
    def links_consistent(self):
        """A live link equals a fresh recompute; after its source dies the
        dependent keeps the value it had (Reactive Design — Destroy)."""
        for key_dst, rec in list(self.links.items()):
            dst = self.pool.get(key_dst)
            if dst is None or not dst.is_alive:
                self.links.pop(key_dst, None)
                continue
            src = self.pool.get(rec[0])
            with quiet():
                got = dst.mirror
            if src is not None and src.is_alive:
                assert got == src.hp + 1, f"#{key_dst}.mirror {got} != #{rec[0]}.hp + 1 ({src.hp + 1})"
            elif rec[1] is None:
                rec[1] = got   # first look after the source died: freeze
                HITS["link_source_died"] += 1
            else:
                assert got == rec[1], f"#{key_dst}.mirror moved after its source died: {rec[1]} -> {got}"

    @invariant()
    def frame_batch_closed(self):
        ss = get_scena_system()
        assert not ss.update_manager.deferring, "frame batch left open"

    @invariant()
    def on_destroy_once(self):
        n = self.probe.count("on_destroy")
        dead_hooked = sum(1 for r in self.on_destroy_hooked.values()
                          if r() is not None and not r().is_alive)
        # Collected actors were dead too; count them via the probe total bound.
        assert n >= dead_hooked, f"on_destroy missed: {n} < {dead_hooked}"
        assert n <= len(self.on_destroy_hooked), "on_destroy ran more than once"

    # -- teardown -----------------------------------------------------------
    def teardown(self):
        self.tearing_down = True   # spawners stop spawning
        # A rule that raised is still propagating: its traceback pins the
        # actors, so a residue check here would report that instead of the
        # real error. Clean up, but only assert on a clean run.
        failing = sys.exc_info()[0] is not None
        try:
            with quiet():
                for r in self.refs:
                    if r() is not None and r().is_alive:
                        r().destroy()  # no local: it would pin the last actor
                self.w.step(5)
                # A finite sound rings out past its destroyed owner, released
                # to the game (Sound Design — When the owner ends): no owner,
                # no callback. Let the 0.4 s tones end before the census.
                for h in list(get_scheduler()._sound):
                    assert h.owner is None and h.scope == "game", (
                        f"sound still owned after every actor died: {h!r}")
                    assert h._fn is None and h._then is None, (
                        f"released sound kept its callback: {h!r}")
                self.w.seconds(0.5)
            self.w.objects.clear()
            # Hypothesis keeps bundle values (actors_0, …) referenced until the
            # run ends; drop them so the census sees only engine-held objects.
            self.pool.clear()
            self.sm.clear()     # the model holds strong references
            self.links.clear()
            with quiet():
                for name in list(self.custom_layers):
                    canvas.layers[name].delete()
            self.custom_layers.clear()
            full_collect()
            if failing:
                return
            d = diff_census(self.base, census(), CENSUS_IGNORE)
            assert d == {}, ("session left residue: " + format_diff(d)
                             + " | new: " + describe_new_live(self.base_ids))
            alive = [r() for r in self.refs if r() is not None]
            assert not alive, f"{len(alive)} actors never collected: {alive[:3]!r}"
        finally:
            _PROBE[0] = None
            self.w.teardown()
            gc.collect()


TestWorldMachine = WorldMachine.TestCase


class TestWorldMachineReach(unittest.TestCase):
    """Vacuity guard: the M4 paths must actually run (a machine that never
    installs a link or never spawns onto a drained layer checks nothing)."""

    REQUIRED = ("link_installed", "link_refused_dead", "link_source_died",
                "layer_to_custom", "drain_nonempty", "spawned_on_destroy")
    # A floor, not "> 0": a counter drifting toward marginal fails here before
    # a source edit flips it. Lowest measured over 20 seeds is 9 (Testing Design).
    MIN_HITS = 3

    def test_new_paths_are_reached(self):
        from hypothesis import settings as hsettings
        from hypothesis_support import require_canaries
        require_canaries(self)  # fixed 80-example run: a test of the test
        HITS.clear()
        run = hsettings(max_examples=80, derandomize=True, database=None,
                        stateful_step_count=50)(WorldMachine).TestCase
        result = unittest.TestResult()
        unittest.defaultTestLoader.loadTestsFromTestCase(run).run(result)
        self.assertTrue(result.wasSuccessful(), result.failures or result.errors)
        low = [k for k in self.REQUIRED if HITS[k] < self.MIN_HITS]
        self.assertEqual(low, [], f"reached < {self.MIN_HITS} times: {low}; hits {dict(HITS)}")



# ---------------------------------------------------------------------------
# Canaries — put a known bug back; the machine must fail (Testing Design)
# ---------------------------------------------------------------------------

def _unguarded_scheduler_add():
    """``Scheduler.add`` rebuilt from source minus the S9 dead-owner refusal."""
    import inspect
    import textwrap
    from scena import process as pr
    src = textwrap.dedent(inspect.getsource(pr.Scheduler.add))
    start = src.index("    if owner is not None and _is_entity(owner)")
    end = src.index("        return handle\n", start) + len("        return handle\n")
    ns: dict = {}
    exec(compile(src[:start] + src[end:], pr.__file__, "exec"), pr.__dict__, ns)
    return ns["add"]


def _retire_part_noop(self, part, host):
    """P1 put back: ``destroy()`` leaves the owner's Point parts registered."""
    return None


def _remove_live_noop(self, obj):
    """Roster leak: ``destroy()`` leaves the actor in ``Registry.live``."""
    return None


class TestSystemCanaries(unittest.TestCase):
    """Each known bug, monkeypatched back, must make its machine fail. The run
    uses a fresh copy of the module under the ``canary`` profile
    (``diff_support.assert_catches``)."""

    WORLD = "test_sys_hyp_world.TestWorldMachine.runTest"
    REGISTRY = "test_hyp_canvas.TestRegistryLifecycle.runTest"

    def _catch(self, test_id, patches, what):
        from diff_support import assert_catches
        assert_catches(self, test_id, patches, what)

    def test_p1_part_outlives_its_owner(self):
        from scena.registry import Registry
        self._catch(self.REGISTRY, [(Registry, "retire_part", _retire_part_noop)],
                    "retire_part that leaves parts registered (P1)")

    def test_destroy_keeps_a_roster_entry(self):
        # H3 (a stale destroy dropped a reused id) cannot recur: roster keys
        # are serials, never reused. The roster check itself must still bite.
        from scena.registry import Registry
        self._catch(self.REGISTRY, [(Registry, "remove_live", _remove_live_noop)],
                    "remove_live that never removes")

    def test_s1_class_leave_playfield_keeps_the_dead(self):
        # S1's bound-method variant only pins an actor that is dropped without
        # destroy(), which this machine never does (guard: test_leave_playfield
        # S1 test, test_sys_lifetime). Here: the destroy-time forget is removed.
        from scena.bounds import BoundsSystem
        self._catch(self.WORLD, [(BoundsSystem, "forget_item", lambda self, item: None)],
                    "@leave_playfield handlers not forgotten at destroy (S1 class)")

    def test_s6_pair_targets_keep_the_dead(self):
        from scena.collision import CollisionSystem
        # Two paths drop a dead side from ``_pair_targets`` since review
        # 2026-10-09 S8-7: the destroy-time forget, and the tag retirement
        # that prunes the members of a tag whose last rule went. The plant
        # removes both.
        self._catch(self.WORLD, [(CollisionSystem, "_forget_pair_target", lambda self, identity: None),
                                 (CollisionSystem, "retire_unused_pair_tags", lambda self: None)],
                    "_pair_targets not pruned at destroy (S6)")

    def test_s9_work_scheduled_on_a_dead_owner(self):
        from scena.process import Scheduler
        self._catch(self.WORLD, [(Scheduler, "add", _unguarded_scheduler_add())],
                    "after / every on a destroyed owner (S9)")

    def test_destroy_skips_the_collision_system(self):
        from scena.collision import CollisionSystem
        self._catch(self.WORLD, [(CollisionSystem, "forget_destroyed_item", lambda self, item: None)],
                    "forget_destroyed_item skipped in _destroy_teardown")

    def test_w2_link_onto_a_dead_actor(self):
        self._catch(self.WORLD, [("scena.state", "_refuse_link_on_dead", lambda container, action: None)],
                    "@= onto a destroyed actor accepted (W2)")


if __name__ == "__main__":
    unittest.main()
