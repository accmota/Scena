"""Stateful property tests for the registry: Graphic creation, layers, groups, removal, destroy.

A Hypothesis ``RuleBasedStateMachine`` plays random author sessions against the
registry and checks it against a small model after every step.

Rules (author verbs): construct each kind (with layer / group / id choices),
``destroy`` (also twice, also on a dead object), ``undraw``, ``layer =``,
``tag`` / ``untag`` / ``group =``, ``visible``, ``active`` park / resume,
``clone``, ``move_to_front`` / ``move_to_back``, ``canvas.layers.create``,
layer ``delete`` / ``clear`` (soft and hard), ``group[...].destroy()``, and an
``on_destroy`` that spawns onto its own layer.

Invariants (from Scena Design / Canvas Design / Actors Design):

* A live object sits on exactly the layer it reports, once; painter order on
  each layer is creation / move order.
* A destroyed object is **nowhere**: no draw list, no group, no id, not
  ``active`` — and no later verb on the dead reference brings it back.
* ``group[name]`` walks members in join order (re-tag after untag goes last).
* ``on_destroy`` fires exactly once per destroyed object, never for live ones.
* Parking hides; resuming restores the prior ``visible``.
* A layer drain (``delete`` / ``clear(hard=True)`` / ``destroy_all``) reaches a
  fixed point: an ``on_destroy`` spawn onto the drained layer dies too.

    python -m unittest tests.test_hyp_canvas -v
    SCENA_HYPOTHESIS_PROFILE=deep python -m unittest tests.test_hyp_canvas
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis_support import (  # noqa: E402
    AUTHOR_ERRORS, GROUP_POOL, LAYER_POOL, WorldTracker, boot, custom_layer_names,
    group_names, new_in_roster, numeric_layers, roster_mark, quiet, registry,
)
from hyp_models import RegistryModel  # noqa: E402
from hypothesis import note, strategies as hst  # noqa: E402
from hypothesis.stateful import (  # noqa: E402
    Bundle, RuleBasedStateMachine, invariant, multiple, precondition, rule,
)

from scena import (  # noqa: E402
    Circle, Ellipse, Entity, Line, Polygon, Rect, Text, canvas, group,
)
from scena.registry import entity_parts  # noqa: E402
from scena.state import DestroyedError  # noqa: E402

boot()

KINDS = {
    "Circle": lambda **kw: Circle(center=(0, 0), radius=5, **kw),
    "Rect": lambda **kw: Rect(center=(0, 0), width=8, height=4, **kw),
    "Ellipse": lambda **kw: Ellipse(**kw),
    "Line": lambda **kw: Line(p1=(0, 0), p2=(5, 5), **kw),
    "Polygon": lambda **kw: Polygon(points=[(0, 0), (10, 0), (0, 10)], **kw),
    # World Text (any layer but ``ui``) needs center=; HUD Text stacks on ``ui``.
    "Text": lambda **kw: Text("hyp", **({"center": (0, 0)} if kw.get("layer", "ui") != "ui"
                                        else {}), **kw),
    "Entity": lambda **kw: Entity(**kw),
}
# Where each kind lands when layer= is omitted (construct-to-place defaults).
DEFAULT_LAYER = {"Text": "ui", "Entity": None}
DRAWABLE = [k for k in KINDS if k != "Entity"]


class RegistryMachine(RuleBasedStateMachine):
    objs = Bundle("objs")

    def __init__(self):
        super().__init__()
        self.world = WorldTracker()
        self.sm = RegistryModel(GROUP_POOL)   # shared with test_sys_hyp_world
        self.model = self.sm.info          # obj -> Model
        self.order = self.sm.order         # layer key -> [obj] painter order (tracked only)
        self.members = self.sm.members     # join order
        self.custom_layers = set()
        self.numeric_layers = set()
        self.fired = {}          # obj -> on_destroy count
        self.parts = {}          # obj -> its Point parts, captured at creation
        self._pending_spawns = self.sm.pending_spawns

    def teardown(self):
        self.parts.clear()
        self.world.teardown()

    # ------------------------------------------------------------------ model
    def _place(self, obj, layer):
        self.sm.place(obj, layer)

    def _unplace(self, obj):
        self.sm.unplace(obj)

    def _join(self, obj, g):
        self.sm.join(obj, g)

    def _leave(self, obj, g):
        self.sm.leave(obj, g)

    def _model_destroy(self, obj):
        """Model side of a successful ``destroy()`` (incl. an on_destroy spawn)."""
        return self.sm.destroy(obj)

    def _existing_layer_keys(self):
        return ["default", "top", "ui", *sorted(self.custom_layers),
                *sorted(self.numeric_layers)]

    def _on_destroy_handler(self, obj):
        def handler():
            self.fired[obj] = self.fired.get(obj, 0) + 1
            m = self.model[obj]
            if m.spawn_on_destroy and obj.layer is not None:
                # Spawn onto our own layer while still fully alive.
                child = Circle(center=(1, 1), radius=2, layer=obj.layer)
                self._register_new(child, "Circle", obj.layer, [])
                self._pending_spawns[obj] = child
        return handler

    def _register_new(self, obj, kind, layer, groups):
        self.world.track(obj)
        self.sm.track(obj, kind, layer, groups)
        self.parts[obj] = entity_parts(obj)
        self.fired[obj] = 0
        obj.on_destroy = self._on_destroy_handler(obj)

    # ------------------------------------------------------------------ rules
    @rule(target=objs,
          kind=hst.sampled_from(sorted(KINDS)),
          layer=hst.one_of(hst.just("__omit__"), hst.sampled_from(["default", "top"]),
                           numeric_layers, custom_layer_names),
          groups=hst.lists(group_names, max_size=2, unique=True))
    def create(self, kind, layer, groups):
        if kind == "Entity":
            layer = "__omit__"  # bare Entity never draws
        kwargs = {}
        if layer != "__omit__":
            kwargs["layer"] = layer
        if groups:
            kwargs["group"] = groups
        layer_missing = isinstance(layer, str) and layer in LAYER_POOL \
            and layer not in self.custom_layers
        if layer_missing:
            before = self._census()
            mark = roster_mark()
            try:
                with quiet():
                    stray = KINDS[kind](**kwargs)
            except ValueError:
                pass
            else:
                self.world.track(stray)
                raise AssertionError(
                    f"{kind}(**{kwargs}) should raise ValueError "
                    f"(unknown layer)")
            assert self._census() == before, \
                f"failed {kind}(**{kwargs}) left a trace in the registry"
            assert new_in_roster(mark) == [], \
                f"failed {kind}(**{kwargs}) left a roster entry"
            return consumes_nothing()
        with quiet():
            obj = KINDS[kind](**kwargs)
        want_layer = DEFAULT_LAYER.get(kind, "default") if layer == "__omit__" else layer
        if isinstance(layer, int):
            self.numeric_layers.add(layer)
        self._register_new(obj, kind, want_layer, groups)
        return obj

    @rule(obj=objs)
    def destroy(self, obj):
        m = self.model[obj]
        was_alive = m.alive
        obj.destroy()   # idempotent: a second destroy is a quiet no-op
        if was_alive:
            self._model_destroy(obj)

    @rule(obj=objs)
    def undraw(self, obj):
        m = self.model[obj]
        if not m.alive:
            self._verb_on_dead(obj, "undraw()", lambda: obj.undraw())
            return
        obj.undraw()
        self._unplace(obj)

    @rule(obj=objs, dest=hst.one_of(hst.none(), hst.sampled_from(["default", "top"]),
                                      numeric_layers, custom_layer_names))
    def set_layer(self, obj, dest):
        m = self.model[obj]
        if not m.alive:
            self._verb_on_dead(obj, f"layer = {dest!r}", lambda: setattr(obj, "layer", dest))
            return
        if m.kind == "Entity" and dest is not None:
            return  # Entity layer placement is out of scope for this machine
        if isinstance(dest, str) and dest in LAYER_POOL and dest not in self.custom_layers:
            try:
                obj.layer = dest
            except ValueError:
                return
            raise AssertionError(f"layer = {dest!r} (missing) accepted")
        obj.layer = dest
        if isinstance(dest, int):
            self.numeric_layers.add(dest)
        if dest != m.layer:
            self._unplace(obj)
            self._place(obj, dest)

    @rule(obj=objs, g=group_names)
    def tag(self, obj, g):
        m = self.model[obj]
        if not m.alive:
            self._verb_on_dead(obj, f"tag({g!r})", lambda: obj.tag(g))
            return
        obj.tag(g)
        self._join(obj, g)

    @rule(obj=objs, g=group_names)
    def untag(self, obj, g):
        m = self.model[obj]
        if not m.alive:
            self._verb_on_dead(obj, f"untag({g!r})", lambda: obj.untag(g))
            return
        obj.untag(g)
        self._leave(obj, g)

    @rule(obj=objs, gs=hst.lists(group_names, max_size=3, unique=True))
    def assign_groups(self, obj, gs):
        m = self.model[obj]
        if not m.alive:
            self._verb_on_dead(obj, f"group = {gs!r}", lambda: setattr(obj, "group", gs))
            return
        obj.group = gs
        for g in list(m.groups):
            if g not in gs:
                self._leave(obj, g)
        for g in sorted(gs):
            self._join(obj, g)

    @rule(obj=objs)
    def show_handles(self, obj):
        # Puts Point parts on ``top`` as draggable handles (untracked by the
        # draw-list model); ``parts_follow_their_owner`` checks they leave.
        if self.model[obj].alive and hasattr(obj, "show_handles"):
            obj.show_handles()

    @rule(obj=objs, value=hst.booleans())
    def set_visible(self, obj, value):
        m = self.model[obj]
        if not m.alive or m.parked or m.kind == "Entity":
            return
        obj.visible = value
        m.visible = value

    @rule(obj=objs)
    def park_toggle(self, obj):
        m = self.model[obj]
        if not m.alive:
            obj.active = True  # documented: does not revive
            return
        if not m.parked:
            obj.active = False
            m.parked = True
            m.saved_visible = m.visible
            m.visible = False
        else:
            obj.active = True
            m.parked = False
            m.visible = m.saved_visible
            m.saved_visible = None

    @rule(target=objs, obj=objs)
    def clone(self, obj):
        m = self.model[obj]
        if not m.alive or m.kind == "Entity":
            return consumes_nothing()
        with quiet():
            c = obj.clone()
        # Clone copies art / style / groups / visible, not placement or park:
        # class-default layer, active. A HUD Text clone stays a HUD caption;
        # a world Text clone is a world caption (default layer).
        if m.kind == "Text":
            want = "ui" if m.layer == "ui" else "default"
        else:
            want = DEFAULT_LAYER.get(m.kind, "default")
        self._register_new(c, m.kind, want, list(m.groups))
        self.model[c].visible = m.visible
        return c

    @rule(obj=objs, front=hst.booleans())
    def restack(self, obj, front):
        m = self.model[obj]
        if not m.alive or m.layer is None:
            return
        sc = registry()
        (sc.move_to_front if front else sc.move_to_back)(obj)
        self.sm.restack(obj, front)

    @rule(obj=objs)
    def arm_spawner(self, obj):
        m = self.model[obj]
        if m.alive and m.kind != "Entity":
            m.spawn_on_destroy = True

    @rule(name=custom_layer_names, z=hst.integers(-20, 100))
    def create_layer(self, name, z):
        if name in self.custom_layers:
            try:
                canvas.layers.create(name, z=z)
            except ValueError:
                return
            raise AssertionError(f"layers.create({name!r}) twice accepted")
        canvas.layers.create(name, z=z)
        self.custom_layers.add(name)

    @precondition(lambda self: self.custom_layers)
    @rule(data=hst.data(), destroy_shapes=hst.booleans())
    def delete_layer(self, data, destroy_shapes):
        name = data.draw(hst.sampled_from(sorted(self.custom_layers)))
        on_it = list(self.order.get(name, []))
        registry().layers[name].delete(destroy_shapes=destroy_shapes)
        self.custom_layers.discard(name)
        if destroy_shapes:
            self._model_drain(name, on_it)
        else:
            for obj in on_it:
                self._unplace(obj)
        self.order.pop(name, None)

    @rule(data=hst.data(), hard=hst.booleans())
    def clear_layer(self, data, hard):
        name = data.draw(hst.sampled_from(self._existing_layer_keys()))
        on_it = list(self.order.get(name, []))
        others_before = self._untracked_on(name)
        if hard and others_before:
            return  # never destroy objects other test modules left on built-ins
        registry().layers[name].clear(hard=hard)
        if hard:
            self._model_drain(name, on_it)
        else:
            for obj in on_it:
                self._unplace(obj)

    @rule(g=group_names)
    def destroy_group(self, g):
        members = list(self.members[g])
        group[g].destroy()
        for obj in members:
            self._model_destroy(obj)  # a spawn stays alive: plain destroy, not a drain

    # ---------------------------------------------------------------- helpers
    def _model_drain(self, name, on_it):
        """Destroy everything on ``name`` to a fixed point (spawns included)."""
        self.sm.drain(name, on_it)

    def _untracked_on(self, name):
        layer = registry().layers.get(name)
        if layer is None:
            return []
        layer._compact()
        return [o for o in layer._objects if o not in self.model]

    def _verb_on_dead(self, obj, label, fn):
        """A verb on a destroyed reference may raise DestroyedError or no-op — never revive."""
        try:
            with quiet():
                fn()
        except (DestroyedError, *AUTHOR_ERRORS):
            return
        note(f"{label} on destroyed {obj!r} returned without DestroyedError")

    def _census(self):
        sc = registry()
        out = {}
        for key in list(sc.layers):
            layer = sc.layers.get(key)
            layer._compact()
            out[key] = len(layer._objects)
        groups = {g: sc.group_live_count(g) for g in GROUP_POOL}
        return out, groups

    # ------------------------------------------------------------- invariants
    @invariant()
    def registry_matches_model(self):
        sc = registry()
        for obj, m in self.model.items():
            label = f"{m.kind} {obj!r}"
            assert obj.is_alive == m.alive, f"{label}: is_alive={obj.is_alive}, model {m.alive}"
            if m.alive:
                assert obj.layer == m.layer, f"{label}: layer {obj.layer!r}, model {m.layer!r}"
                assert set(obj.group) == set(m.groups), \
                    f"{label}: groups {obj.group}, model {m.groups}"
                assert sc.is_live(obj), f"{label}: alive but not in the roster"
                if m.kind != "Entity":
                    assert obj.visible == m.visible, \
                        f"{label}: visible {obj.visible}, model {m.visible}"
                assert obj.active == (not m.parked), f"{label}: active {obj.active}"
                assert self.fired[obj] == 0, f"{label}: on_destroy fired while alive"
            else:
                assert obj.active is False, f"{label}: destroyed but active"
                assert not sc.is_live(obj), f"{label}: destroyed but still in the roster"
                assert self.fired[obj] == 1, \
                    f"{label}: on_destroy fired {self.fired[obj]} times"

    @invariant()
    def parts_follow_their_owner(self):
        # P1: a part leaves with its owner (roster, every layer, pointer lists);
        # a parked owner's parts are parked too (off every layer and pointer list).
        sc = registry()
        for obj, parts in self.parts.items():
            alive = self.model[obj].alive
            for part in parts:
                label = f"{self.model[obj].kind} part {part!r}"
                assert part.is_alive == alive, f"{label}: is_alive={part.is_alive}, owner {alive}"
                assert sc.is_live(part) == alive, f"{label}: roster disagrees with owner"
                if alive:
                    parked = self.model[obj].parked
                    assert part.active == (not parked), f"{label}: active {part.active}, owner parked {parked}"
                if not alive or self.model[obj].parked:
                    for key in list(sc.layers):
                        layer = sc.layers.get(key)
                        assert part not in layer._interactive, f"{label}: still clickable on {key!r}"
                        layer._compact()
                        assert part not in layer._objects, f"{label}: still drawn on {key!r}"

    @invariant()
    def draw_lists_match_model(self):
        self.sm.check_draw_lists(registry())

    @invariant()
    def groups_match_model(self):
        self.sm.check_groups(GROUP_POOL, lambda g: group[g])

    @invariant()
    def custom_layers_exist(self):
        for name in LAYER_POOL:
            assert (name in canvas.layers) == (name in self.custom_layers), \
                f"layer {name!r} existence mismatch"


def consumes_nothing():
    """A rule with ``target=`` that makes nothing returns ``multiple()`` (empty)."""
    return multiple()


TestRegistryLifecycle = RegistryMachine.TestCase


if __name__ == "__main__":
    unittest.main()
